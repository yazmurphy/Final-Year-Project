import asyncio
import threading
import socket
import time
import json  
import carla
import random
from colorama import init, Fore
from datetime import datetime
from bleak import BleakScanner, BleakClient
import math
import sys
import os
import keyboard
import csv

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

bike_actor = None
car_actor1 = None
car_actor2 = None
spectator_actor = None  #storing spectator actor
log_file = "bike_movement_log.csv"  # Log file name
recording_file = "C:/CARLA_0.9.15/WindowsNoEditor/PythonAPI/examples/Prototypes/simulation_recording.log"  # Recording file name
client = None  # CARLA client
is_running = True  # Flag to control the simulation loop


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

    timeout_duration = 60  #Set the timeout duration to 60 seconds
    start_time = time.time()
    wahoo_device = None

    while time.time() - start_time < timeout_duration:
        print("Scanning for Wahoo device...")
        devices = await BleakScanner.discover()

        for device in devices:
            print(device)
            if device.name == "Wahoo SPEED C1E5":
                wahoo_device = device
                break

        if wahoo_device:
            break  #Exit the loop if the device is found

        await asyncio.sleep(5)  #Wait for 5 seconds before scanning again

    if not wahoo_device:
        print(f"Wahoo SPEED C1E5 not found after {timeout_duration} seconds.")
        return

    print(f"Found Wahoo device: {wahoo_device.name}, {wahoo_device.address}")

    #Retry connection if it fails
    for attempt in range(3):  #Retry up to 3 times
        try:
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
                return  # Exit the function if connection is successful
        except Exception as e:
            print(f"Connection attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(5)  # Wait before retrying

    print("Failed to connect to Wahoo device after 3 attempts.")   
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
        no_rotation_count = 0 


############################
# Steering/Throttle Logic
############################
def process_heading_data(data):
    """
    Process heading data to calculate steering and throttle for the bike.
    """
    global no_rotation_count

    try:
        heading = float(data.get("locationTrueHeading", 0.0))
        steer = math.sin(math.radians(heading)) * 0.5  # Reduce steering severity
        steer = max(-1.0, min(1.0, steer))  # Clamp steering value

        # Use wheel revolutions as a simple throttfle logic
        revolutions = shared_data["cumulative_wheel_revolutions"]

        if no_rotation_count >= 2:  # If no rotations for 3 transmissions
            throttle = max(0.0, shared_data["last_throttle"] * 0.3)  # Gradual deceleration
        elif revolutions < 5:  # Threshold for low revolutions
            throttle = max(0.0, shared_data["last_throttle"] * 0.9)  # Gradual deceleration
        else:
            throttle = min(0.1 + revolutions * 0.015, 1.0)  # Normal throttle calculation

        shared_data["last_throttle"] = throttle  # Store the last throttle value
        return steer, throttle
    except Exception as e:
        print(f"Error processing heading data: {e}")
        return 0.0, 0.1


############################
# First-Person Camera
############################
def update_spectator_camera(actor, spectator):
    """
    Dynamically position the camera at the cyclist's head for a first-person view.
    The camera will follow the bike in a first-person perspective.
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
# Manual Camera Switch - not really used anymore but useful for debug
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
# Logging Functionality
############################

def calculate_distance(actor1, actor2):
    """
    Calculate the Euclidean distance between two actors.
    """
    if not actor1 or not actor2:
        return float('inf')  # Return a large value if either actor is missing

    loc1 = actor1.get_location()
    loc2 = actor2.get_location()
    return math.sqrt((loc1.x - loc2.x) ** 2 + (loc1.y - loc2.y) ** 2 + (loc1.z - loc2.z) ** 2)

def log_bike_data(bike, car1, car2, start_time):
    """
    Log the bike's movement data to a CSV file.
    """
    if not bike:
        return

    # Get the current time
    current_time = time.time() - start_time

    # Get the bike's location and speed
    transform = bike.get_transform()
    velocity = bike.get_velocity()
    speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) * 3.6  # Convert m/s to km/h

    # Get the bike's position
    x, y, z = transform.location.x, transform.location.y, transform.location.z

    # Calculate proximity to other vehicles
    distance_to_car1 = calculate_distance(bike, car1)
    distance_to_car2 = calculate_distance(bike, car2)

    # Write data to the log file
    with open(log_file, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([current_time, speed, x, y, z, distance_to_car1, distance_to_car2])
        
async def carla_control_loop():
    global bike_actor, car_actor1, car_actor2, spectator_actor

    vehicle = None
    last_print_time = 0
    data_counter = 0
    process_every_nth = 5

    # Initialize the log file
    with open(log_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Time (s)", "Speed (km/h)", "X", "Y", "Z", "Distance to Car 1 (m)", "Distance to Car 2 (m)"])

    start_time = time.time()

    try:
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)
        world = client.get_world()

       
        blueprint_library = world.get_blueprint_library()
        bike_bp = blueprint_library.find('vehicle.diamondback.century')
        car1_bp = blueprint_library.find('vehicle.nissan.patrol')   # Car 1 = Nissan Patrol
        car2_bp = blueprint_library.find('vehicle.tesla.model3')    # Car 2 = Tesla Model 3

        # ----
        # MANUAL SPAWN LOCATIONS
        # ----
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
        # ----

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

        # Start recording the simulation
        print(f"Starting simulation recording: {recording_file}")
        client.start_recorder(recording_file)

        # Basic control loop
        while True:
            # Update the spectator camera to follow the bike dynamically
            if bike_actor and spectator_actor:
                update_spectator_camera(bike_actor, spectator_actor)

            # Check for keyboard input to stop the simulation
            if keyboard.is_pressed('k'):
                print('Simulation killed with k')
                break

            # Process heading data and control the bike
            if latest_heading_data:
                data = latest_heading_data.copy()
                data_counter += 1

                if data_counter % process_every_nth == 0:
                    steer, throttle = process_heading_data(data)  # Pass only `data`
                    if bike_actor:
                        control = carla.VehicleControl(throttle=throttle, steer=steer)
                        bike_actor.apply_control(control)

            # Log bike data
            log_bike_data(bike_actor, car_actor1, car_actor2, start_time)
            # print("Logged bike data to CSV.")  # Debugging statement

            # Sleep to control the update rate
            await asyncio.sleep(0.05)

    finally:
        # Stop recording the simulation
        print(f"Stopping simulation recording: {recording_file}")
        client.stop_recorder()

        # Check if the recording file was created
        if os.path.exists(recording_file):
            print(f"Recording saved successfully: {recording_file}")
        else:
            print(f"Error: Recording file {recording_file} was not created.")

        # Cleanup
        if bike_actor:
            bike_actor.destroy()
        if car_actor1:
            car_actor1.destroy()
        if car_actor2:
            car_actor2.destroy()

        client.stop_recorder()
        print("Destroyed bike and cars.")
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