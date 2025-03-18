import asyncio
import threading
import socket
import time
import json  # For JSON parsing
import carla
import random
from colorama import init, Fore
from datetime import datetime
from bleak import BleakScanner, BleakClient
import math
import sys

# Initialize for colored print statements
init(autoreset=True)

############################
# Global Variables
############################

notification_count = 0
start_time = None

# Shared data (BLE <-> CARLA)
shared_data = {
    "cumulative_wheel_revolutions": 0,
    "last_wheel_event_time": 0
}

# Latest heading data from socket
latest_heading_data = None

# Global references to the main actors so camera can switch
bike_actor = None
car_actor1 = None
car_actor2 = None
spectator_actor = None  # We'll store the spectator here

############################
# Socket Server
############################

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
            start_time = time.time()
            data_count = 0
            buffer = ""

            while True:
                data = conn.recv(1024)
                if not data:
                    break

                data_count += 1
                elapsed_time = time.time() - start_time
                if elapsed_time > 0:
                    frequency = data_count / elapsed_time

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
                            print("Error parsing JSON:", e)
                            break
                except Exception as e:
                    print("Socket receive error:", e)

############################
# BLE / Wahoo
############################

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
    ms = (last_wheel_event_time_seconds * 1000) % 1000

    shared_data["cumulative_wheel_revolutions"] = cumulative_wheel_revolutions
    shared_data["last_wheel_event_time"] = last_wheel_event_time_seconds

    print(Fore.GREEN + f"Flags: {flags}")
    print(Fore.GREEN + f"Cumulative Wheel Revolutions: {cumulative_wheel_revolutions}")
    print(Fore.GREEN + f"Last Wheel Event Time: {int(last_wheel_event_time_seconds)}s {int(ms)}ms")

async def find_and_connect_wahoo():
    global start_time

    devices = await BleakScanner.discover()
    wahoo_device = None

    for device in devices:
        if device.name == "Wahoo SPEED C1E5":
            wahoo_device = device
            break

    if not wahoo_device:
        print("Wahoo SPEED C1E5 not found.")
        return

    print(f"Found Wahoo device: {wahoo_device.name}, {wahoo_device.address}")

    async with BleakClient(wahoo_device.address) as client:
        print(f"Connected to {wahoo_device.address}")

        services = await client.get_services()
        for service in services:
            print(f"Service: {service.uuid}")
            for characteristic in service.characteristics:
                print(f"  Characteristic: {characteristic.uuid}")

        characteristic_uuid = "00002a5b-0000-1000-8000-00805f9b34fb"
        await client.start_notify(characteristic_uuid, notification_handler)

        start_time = time.time()
        await asyncio.sleep(30)

def notification_handler(sender, data):
    global notification_count, start_time

    notification_count += 1
    parse_csc_measurement(data)

    elapsed_time = time.time() - start_time
    if elapsed_time > 0:
        data_rate_hz = notification_count / elapsed_time
        print(f"Data Rate: {data_rate_hz:.2f} Hz")

############################
# Steering/Throttle Logic
############################

def process_heading_data(data, last_print_time):
    try:
        heading = float(data.get("locationTrueHeading", 0.0))
        json_time = data.get("loggingTime", "Unknown")

        # Convert heading to steering
        steer = math.sin(math.radians(heading))
        steer = max(-1.0, min(1.0, steer))  # clamp

        # Steering descriptor
        if steer > 0.7:
            steering_description = "Full Right"
        elif 0.3 < steer <= 0.7:
            steering_description = "Slight Right"
        elif -0.3 <= steer <= 0.3:
            steering_description = "Straight"
        elif -0.7 <= steer < -0.3:
            steering_description = "Slight Left"
        else:
            steering_description = "Full Left"

        print(f"Heading: {heading}°, Steering: {steer:.2f} ({steering_description}), Time: {json_time}")

        # Use wheel revs as a simple throttle logic
        throttle = min(0.1 + shared_data["cumulative_wheel_revolutions"] * 0.01, 1.0)
        return steer, throttle, last_print_time
    except Exception as e:
        print(f"Error processing heading data: {e}")
        return 0.0, 0.1, last_print_time

############################
# Spectator Camera
############################

def update_spectator_camera(actor, spectator):
    """
    Position the camera behind and slightly above 'actor.'
    """
    if not actor:
        return

    transform = actor.get_transform()
    location = transform.location
    rotation = transform.rotation

    distance_behind = 4
    height = 2
    yaw_radians = math.radians(rotation.yaw)

    camera_x = location.x - distance_behind * math.cos(yaw_radians)
    camera_y = location.y - distance_behind * math.sin(yaw_radians)
    camera_z = location.z + height

    camera_location = carla.Location(x=camera_x, y=camera_y, z=camera_z)
    camera_rotation = carla.Rotation(pitch=-10, yaw=rotation.yaw)
    spectator.set_transform(carla.Transform(camera_location, camera_rotation))

############################
# Manual Camera Switch
############################

def camera_input_thread():
    """
    Runs in a separate thread. Waits for user input in the terminal.
    When the user types "bike", "car1", or "car2," move the spectator camera.
    Type "exit" or "quit" to end.
    """
    while True:
        user_cmd = input("\nType 'bike', 'car1', 'car2', or 'quit' to switch camera view:\n").strip().lower()
        if user_cmd in ["quit", "exit"]:
            print("Exiting camera input thread...")
            break
        elif user_cmd == "bike":
            if bike_actor and spectator_actor:
                update_spectator_camera(bike_actor, spectator_actor)
                print("Camera moved to Bike.")
            else:
                print("Bike or spectator not available.")
        elif user_cmd == "car1":
            if car_actor1 and spectator_actor:
                update_spectator_camera(car_actor1, spectator_actor)
                print("Camera moved to Car 1.")
            else:
                print("Car 1 or spectator not available.")
        elif user_cmd == "car2":
            if car_actor2 and spectator_actor:
                update_spectator_camera(car_actor2, spectator_actor)
                print("Camera moved to Car 2.")
            else:
                print("Car 2 or spectator not available.")
        else:
            print("Unknown command. Please type 'bike', 'car1', 'car2', or 'quit'.")

############################
# CARLA Control Loop
############################

async def carla_control_loop():
    global bike_actor, car_actor1, car_actor2, spectator_actor

    vehicle = None
    last_print_time = 0
    data_counter = 0
    process_every_nth = 5

    try:
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)
        world = client.get_world()

        # -------------- ONLY CHANGED LINES BELOW ----------------
        blueprint_library = world.get_blueprint_library()
        bike_bp = blueprint_library.find('vehicle.diamondback.century')
        car1_bp = blueprint_library.find('vehicle.nissan.patrol')   # Car 1 = Nissan Patrol
        car2_bp = blueprint_library.find('vehicle.tesla.model3')    # Car 2 = Tesla Model 3
        # -------------- /ONLY CHANGED LINES ABOVE ---------------

        # Start recording (adjusted to ensure all actors are recorded)
        recording_file_path = 'C:/CARLA_0.9.15/WindowsNoEditor/PythonAPI/examples/Prototypes/rec03.log'
        client.start_recorder(recording_file_path)
        print(f"Recording started: {recording_file_path}")

        # --------------------------------------------------------
        # MANUAL SPAWN LOCATIONS
        # --------------------------------------------------------
        bike_transform = carla.Transform(
            carla.Location(x=99.5, y=-25.0, z=0.5),
            carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
        )

        car1_transform = carla.Transform(
            carla.Location(x=99.5, y=-11.0, z=0.5),
            carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
        )

        car2_transform = carla.Transform(
            carla.Location(x=99.5, y=-5.0, z=0.5),
            carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
        )
        # --------------------------------------------------------

        # Spawn bike and cars using the chosen transforms:
        bike_actor = world.spawn_actor(bike_bp, bike_transform)
        print(f"Bike manually spawned at {bike_transform.location}")

        car_actor1 = world.spawn_actor(car1_bp, car1_transform)
        print(f"Car 1 (Nissan Patrol) manually spawned at {car1_transform.location}")
        car_actor1.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))

        car_actor2 = world.spawn_actor(car2_bp, car2_transform)
        print(f"Car 2 (Tesla Model 3) manually spawned at {car2_transform.location}")
        car_actor2.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))

        # Move spectator to bike by default
        spectator_actor = world.get_spectator()
        update_spectator_camera(bike_actor, spectator_actor)

        # Basic control loop
        while True:
            if latest_heading_data:
                data = latest_heading_data.copy()
                data_counter += 1

                if data_counter % process_every_nth == 0:
                    steer, throttle, last_print_time = process_heading_data(data, last_print_time)
                    if bike_actor:
                        control = carla.VehicleControl(throttle=throttle, steer=steer)
                        bike_actor.apply_control(control)

            await asyncio.sleep(0.05)

    finally:
        # Cleanup
        if bike_actor:
            bike_actor.destroy()
        if car_actor1:
            car_actor1.destroy()
        if car_actor2:
            car_actor2.destroy()

        client.stop_recorder()
        print("Destroyed bike and cars.")
        print("Recording stopped.")

############################
# Main Entry Point
############################

async def main():
    # Start the socket server in a background thread
    socket_thread = threading.Thread(target=run_socket_server, daemon=True)
    socket_thread.start()

    # Start the camera input thread in the background
    camera_thread = threading.Thread(target=camera_input_thread, daemon=True)
    camera_thread.start()

    # Start BLE + CARLA loops concurrently
    await asyncio.gather(
        find_and_connect_wahoo(),
        carla_control_loop()
    )

if __name__ == '__main__':
    asyncio.run(main())