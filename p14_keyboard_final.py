import asyncio
import threading
import carla
import math
import keyboard  # For capturing keypresses
import time
import csv
import os  # For checking file existence

############################
# Global Variables
############################

bike_actor = None
car_actor1 = None
car_actor2 = None
spectator_actor = None  # We'll store the spectator here
log_file = "bike_movement_log.csv"  # Log file name
recording_file = "C:/CARLA_0.9.15/WindowsNoEditor/PythonAPI/examples/Prototypes/simulation_recording.log"  # Recording file name
client = None  # CARLA client
is_running = True  # Flag to control the simulation loop

############################
# Arrow Key Control Logic
############################

def get_keyboard_input():
    """
    Get keyboard input for controlling the bike.
    Up Arrow: Throttle
    Down Arrow: Brake/Reverse
    Left Arrow: Steer Left
    Right Arrow: Steer Right
    """
    throttle = 0.0
    steer = 0.0

    if keyboard.is_pressed('up'):
        throttle = 1.0
    elif keyboard.is_pressed('down'):
        throttle = -1.0

    if keyboard.is_pressed('left'):
        steer = -1.0
    elif keyboard.is_pressed('right'):
        steer = 1.0

    return throttle, steer

############################
# Spectator Camera
############################

def update_spectator_camera(actor, spectator):
    """
    Dynamically position the camera behind and slightly above the bike.
    The camera will follow the bike in a third-person view.
    """
    if not actor:
        return

    transform = actor.get_transform()
    location = transform.location
    rotation = transform.rotation

    # Position the camera behind and slightly above the bike
    distance_behind = 6  # Distance behind the bike
    height = 2  # Height above the ground
    yaw_radians = math.radians(rotation.yaw)

    camera_x = location.x - distance_behind * math.cos(yaw_radians)
    camera_y = location.y - distance_behind * math.sin(yaw_radians)
    camera_z = location.z + height

    camera_location = carla.Location(x=camera_x, y=camera_y, z=camera_z)
    camera_rotation = carla.Rotation(pitch=-15, yaw=rotation.yaw, roll=0)  # Slight downward pitch
    spectator.set_transform(carla.Transform(camera_location, camera_rotation))

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

############################
# CARLA Control Loop
############################

async def carla_control_loop():
    global bike_actor, car_actor1, car_actor2, spectator_actor, client, is_running

    # Initialize the log file
    with open(log_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Time (s)", "Speed (km/h)", "X", "Y", "Z", "Distance to Car 1 (m)", "Distance to Car 2 (m)"])

    start_time = time.time()

    try:
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)
        world = client.get_world()

        # Get the blueprint library
        blueprint_library = world.get_blueprint_library()

        # Define blueprints for the vehicles
        bike_bp = blueprint_library.find('vehicle.diamondback.century')
        car1_bp = blueprint_library.find('vehicle.nissan.patrol')   # Car 1 = Nissan Patrol
        car2_bp = blueprint_library.find('vehicle.tesla.model3')    # Car 2 = Tesla Model 3

        # Define spawn locations
        bike_transform = carla.Transform(
            carla.Location(x=99.5, y=-25.0, z=1.0),  # Adjusted z to avoid collisions
            carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
        )

        car1_transform = carla.Transform(
            carla.Location(x=99.5, y=-11.0, z=1.0),  # Adjusted z to avoid collisions
            carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
        )

        car2_transform = carla.Transform(
            carla.Location(x=99.5, y=-5.0, z=1.0),  # Adjusted z to avoid collisions
            carla.Rotation(pitch=0.0, yaw=90.0, roll=0.0)
        )

        # Spawn the vehicles
        bike_actor = world.spawn_actor(bike_bp, bike_transform)
        print(f"Bike manually spawned at {bike_transform.location}")

        car_actor1 = world.spawn_actor(car1_bp, car1_transform)
        print(f"Car 1 (Nissan Patrol) manually spawned at {car1_transform.location}")
        car_actor1.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))

        car_actor2 = world.spawn_actor(car2_bp, car2_transform)
        print(f"Car 2 (Tesla Model 3) manually spawned at {car2_transform.location}")
        car_actor2.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))

        # Move the spectator camera to follow the bike
        spectator_actor = world.get_spectator()
        update_spectator_camera(bike_actor, spectator_actor)

        # Start recording the simulation
        print(f"Starting simulation recording: {recording_file}")
        client.start_recorder(recording_file)

        # Basic control loop
        while is_running:
            if keyboard.is_pressed('k'):  # Check if 'k' is pressed to stop the simulation
                print("Simulation ending as 'k' was pressed.")
                is_running = False
                break

            throttle, steer = get_keyboard_input()
            if bike_actor:
                # Apply control to the bike
                control = carla.VehicleControl(throttle=throttle, steer=steer)
                bike_actor.apply_control(control)

                # Update the spectator camera to follow the bike
                update_spectator_camera(bike_actor, spectator_actor)

                # Log the bike's data
                log_bike_data(bike_actor, car_actor1, car_actor2, start_time)

            await asyncio.sleep(0.05)  # 20 FPS control loop

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

        print("Destroyed bike and cars.")

############################
# Main Entry Point
############################

async def main():
    # Start CARLA control loop
    await carla_control_loop()

if __name__ == '__main__':
    asyncio.run(main())