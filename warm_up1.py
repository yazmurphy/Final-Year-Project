import carla
import asyncio
import threading
import socket
import time
import math
import json
from bleak import BleakScanner, BleakClient
from numpy import random

# Global variables
bike_actor = None
spectator_actor = None
latest_heading_data = None
shared_data = {
    "cumulative_wheel_revolutions": 0,
    "last_wheel_event_time": 0,
    "last_throttle": 0.1  # Initial throttle value
}
vehicles_list = []
walkers_list = []
all_id = []
is_running = True
notification_count = 0
start_time = None

#### Socket Server ####
def run_socket_server():
    """
    Socket server that listens for incoming JSON data (heading, location, etc.)
    and updates `latest_heading_data`.
    """
    global latest_heading_data

    host = '0.0.0.0'
    port = 12345

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))
        s.listen()
        print(f"Listening on {host}:{port}")

        conn, addr = s.accept()
        with conn:
            print(f"Connected by {addr}")
            buffer = ""

            while True:
                data = conn.recv(1024)
                if not data:
                    break

                try:
                    decoded_data = data.decode()  # bytes -> string
                    buffer += decoded_data

                    # Attempt to parse JSON objects from buffer
                    while True:
                        try:
                            json_object, index = json.JSONDecoder().raw_decode(buffer)
                            buffer = buffer[index:].strip()
                            latest_heading_data = json_object  # Update global
                        except json.JSONDecodeError:
                            # Incomplete data, wait for more
                            break
                except Exception as e:
                    print("Socket receive error:", e)

#### BLE Wahoo Sensor ####
def parse_csc_measurement(data):
    """
    Parse speed/cadence data from Wahoo sensor.
    """
    global shared_data

    flags = data[0]
    cumulative_wheel_revolutions = int.from_bytes(data[1:5], byteorder='little')
    last_wheel_event_time_raw = int.from_bytes(data[5:7], byteorder='little')

    # Convert last wheel event time to seconds
    last_wheel_event_time_seconds = last_wheel_event_time_raw / 1024

    shared_data["cumulative_wheel_revolutions"] = cumulative_wheel_revolutions
    shared_data["last_wheel_event_time"] = last_wheel_event_time_seconds
no_rotation_count = 0  # Counts consecutive transmissions with no rotations

def notification_handler(sender, data):
    """
    Handle notifications from the BLE Wahoo sensor.
    """
    global notification_count, start_time, no_rotation_count

    notification_count += 1

    # Parse the BLE data
    previous_revolutions = shared_data["cumulative_wheel_revolutions"]
    parse_csc_measurement(data)
    current_revolutions = shared_data["cumulative_wheel_revolutions"]

    # Check if there are no new rotations
    if current_revolutions == previous_revolutions:
        no_rotation_count += 1
    else:
        no_rotation_count = 0  # Reset the counter if rotations are detected

async def find_and_connect_wahoo():
    """
    Find and connect to the Wahoo sensor.
    """
    global start_time

    timeout_duration = 60  # Timeout duration in seconds
    start_time = time.time()
    wahoo_device = None

    while time.time() - start_time < timeout_duration:
        print("Scanning for Wahoo device...")
        devices = await BleakScanner.discover()

        for device in devices:
            if device.name == "Wahoo SPEED C1E5":
                wahoo_device = device
                break

        if wahoo_device:
            break  # Exit the loop if the device is found

        await asyncio.sleep(5)  # Wait for 5 seconds before scanning again

    if not wahoo_device:
        print(f"Wahoo SPEED C1E5 not found after {timeout_duration} seconds.")
        return

    print(f"Found Wahoo device: {wahoo_device.name}, {wahoo_device.address}")

    # Retry connection if it fails
    for attempt in range(3):  # Retry up to 3 times
        try:
            async with BleakClient(wahoo_device.address) as client:
                print(f"Connected to {wahoo_device.address}")

                characteristic_uuid = "00002a5b-0000-1000-8000-00805f9b34fb"
                await client.start_notify(characteristic_uuid, notification_handler)

                # Keep the connection alive for the duration of the simulation
                while is_running:
                    await asyncio.sleep(1)
                return
        except Exception as e:
            print(f"Connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(5)  # Wait before retrying

    print("Failed to connect to Wahoo device after 3 attempts.")

#### Bike Control Logic ####
def process_heading_data(data):
    """
    Process heading data to calculate steering and throttle for the bike.
    """
    global no_rotation_count

    try:
        heading = float(data.get("locationTrueHeading", 0.0))
        steer = math.sin(math.radians(heading)) * 0.5  # Reduce steering severity
        steer = max(-1.0, min(1.0, steer))  # Clamp steering value

        # Use wheel revolutions as a simple throttle logic
        revolutions = shared_data["cumulative_wheel_revolutions"]

        if no_rotation_count >= 3:  # If no rotations for 3 transmissions
            throttle = max(0.0, shared_data["last_throttle"] * 0.8)  # Gradual deceleration
        elif revolutions < 5:  # Threshold for low revolutions
            throttle = max(0.0, shared_data["last_throttle"] * 0.9)  # Gradual deceleration
        else:
            throttle = min(0.1 + revolutions * 0.015, 1.0)  # Normal throttle calculation

        shared_data["last_throttle"] = throttle  # Store the last throttle value
        return steer, throttle
    except Exception as e:
        print(f"Error processing heading data: {e}")
        return 0.0, 0.1
    
#### First-Person Camera ####
def update_spectator_camera(actor, spectator):
    """
    Dynamically position the camera at the cyclist's head for a first-person view.
    """
    if not actor or not spectator:
        return

    # Get the transform of the actor (cyclist)
    transform = actor.get_transform()
    location = transform.location
    rotation = transform.rotation

    # Position the camera at the cyclist's head level
    head_offset = 1.75  # Height to simulate head level
    forward_offset = 0.4  # Slightly forward to simulate head position

    # Calculate the camera's position relative to the cyclist
    yaw_radians = math.radians(rotation.yaw)
    camera_x = location.x + forward_offset * math.cos(yaw_radians)
    camera_y = location.y + forward_offset * math.sin(yaw_radians)
    camera_z = location.z + head_offset

    # Set the camera's location and rotation
    camera_location = carla.Location(x=camera_x, y=camera_y, z=camera_z)
    camera_rotation = carla.Rotation(pitch=rotation.pitch, yaw=rotation.yaw, roll=rotation.roll)
    spectator.set_transform(carla.Transform(camera_location, camera_rotation))

#### Traffic Generation ####
def spawn_traffic(world, client, num_vehicles=30, num_walkers=10):
    """
    Spawns vehicles and pedestrians in the Carla world.
    """
    global vehicles_list, walkers_list, all_id

    # Access TrafficManager via the client
    traffic_manager = client.get_trafficmanager(8000)
    traffic_manager.set_global_distance_to_leading_vehicle(2.5)

    # Get blueprints for vehicles and pedestrians
    blueprints = world.get_blueprint_library().filter('vehicle.*')
    blueprints_walkers = world.get_blueprint_library().filter('walker.pedestrian.*')

    # Spawn vehicles
    spawn_points = world.get_map().get_spawn_points()
    random.shuffle(spawn_points)
    batch = []
    for n, transform in enumerate(spawn_points[:num_vehicles]):
        blueprint = random.choice(blueprints)
        if blueprint.has_attribute('color'):
            color = random.choice(blueprint.get_attribute('color').recommended_values)
            blueprint.set_attribute('color', color)
        blueprint.set_attribute('role_name', 'autopilot')
        batch.append(carla.command.SpawnActor(blueprint, transform)
                     .then(carla.command.SetAutopilot(carla.command.FutureActor, True, traffic_manager.get_port())))

    for response in client.apply_batch_sync(batch, True):
        if response.error:
            print(response.error)
        else:
            vehicles_list.append(response.actor_id)

    # Spawn pedestrians
    spawn_points = []
    for _ in range(num_walkers):
        loc = world.get_random_location_from_navigation()
        if loc:
            spawn_points.append(carla.Transform(loc))
    batch = []
    walker_speed = []
    for spawn_point in spawn_points:
        walker_bp = random.choice(blueprints_walkers)
        if walker_bp.has_attribute('speed'):
            walker_speed.append(walker_bp.get_attribute('speed').recommended_values[1])
        else:
            walker_speed.append(0.0)
        batch.append(carla.command.SpawnActor(walker_bp, spawn_point))
    results = client.apply_batch_sync(batch, True)
    for i, result in enumerate(results):
        if result.error:
            print(result.error)
        else:
            walkers_list.append({"id": result.actor_id, "speed": walker_speed[i]})

    # Spawn walker controllers
    walker_controller_bp = world.get_blueprint_library().find('controller.ai.walker')
    batch = []
    for walker in walkers_list:
        batch.append(carla.command.SpawnActor(walker_controller_bp, carla.Transform(), walker["id"]))
    results = client.apply_batch_sync(batch, True)
    for i, result in enumerate(results):
        if result.error:
            print(result.error)
        else:
            walkers_list[i]["controller"] = result.actor_id

    # Start walker controllers
    all_actors = world.get_actors([walker["controller"] for walker in walkers_list])
    for actor in all_actors:
        actor.start()
        actor.go_to_location(world.get_random_location_from_navigation())

    print(f"Spawned {len(vehicles_list)} vehicles and {len(walkers_list)} pedestrians.")

#### Main Simulation Loop ####
async def carla_control_loop():
    global bike_actor, spectator_actor

    client = carla.Client('127.0.0.1', 2000)
    client.set_timeout(10.0)
    world = client.get_world()

    # Spawn the bike
    blueprint_library = world.get_blueprint_library()
    bike_bp = blueprint_library.find('vehicle.diamondback.century')
    bike_transform = carla.Transform(
        carla.Location(x=99.5, y=-25.0, z=0.5),
        carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
    )
    bike_actor = world.spawn_actor(bike_bp, bike_transform)
    print(f"Bike spawned at {bike_transform.location}")

    # Move spectator to follow the bike
    spectator_actor = world.get_spectator()
    update_spectator_camera(bike_actor, spectator_actor)

    # Spawn traffic
    spawn_traffic(world, client)

    try:
        while is_running:
            # Update the spectator camera to follow the bike dynamically
            if bike_actor and spectator_actor:
                update_spectator_camera(bike_actor, spectator_actor)

            # Process heading data and control the bike
            if latest_heading_data:
                steer, throttle = process_heading_data(latest_heading_data)
                bike_actor.apply_control(carla.VehicleControl(throttle=throttle, steer=steer))

            # Sleep to control the update rate
            await asyncio.sleep(0.05)
    finally:
        # Cleanup
        if bike_actor:
            bike_actor.destroy()
        for vehicle_id in vehicles_list:
            world.get_actor(vehicle_id).destroy()
        for walker in walkers_list:
            world.get_actor(walker["id"]).destroy()
            world.get_actor(walker["controller"]).destroy()
        print("Simulation ended and all actors destroyed.")

#### Main Entry Point ####
async def main():
    # Start the socket server in a background thread
    socket_thread = threading.Thread(target=run_socket_server, daemon=True)
    socket_thread.start()

    # Start the BLE Wahoo sensor connection
    ble_task = asyncio.create_task(find_and_connect_wahoo())

    # Start the Carla control loop
    await asyncio.gather(ble_task, carla_control_loop())

if __name__ == '__main__':
    asyncio.run(main())