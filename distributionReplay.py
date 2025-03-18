import carla
import pandas as pd
import os
import time
import random

# Input CSV file
input_csv = "bike_analysis_results.csv"

# CARLA log files for replay
left_recording_log = "C:/CARLA_0.9.15/WindowsNoEditor/PythonAPI/examples/Prototypes/left_recording.log"
right_recording_log = "C:/CARLA_0.9.15/WindowsNoEditor/PythonAPI/examples/Prototypes/right_recording.log"

# Function to replay a CARLA log file
def replay_carla_log(log_file):
    """
    Replays a CARLA log file using CARLA's replay functionality.
    """
    try:
        # Connect to the CARLA server
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)

        # Check if the recording file exists
        if not os.path.exists(log_file):
            print(f"Recording file not found: {log_file}")
            return

        print(f"Replaying recording: {log_file}")
        client.replay_file(log_file, 0.0, 0.0, 0)  # Replay from the beginning, for the full duration

        # Wait for the server to load the replay
        time.sleep(2)

        # Get the world and list all actors in the replay
        world = client.get_world()
        actors = world.get_actors()
        # print("Actors in the replay:")
        # for actor in actors:
        #     print(f"ID: {actor.id}, Type: {actor.type_id}, Location: {actor.get_transform().location}")

        # Set the spectator camera to the bike's position
        bike_location = carla.Location(x=99.500000, y=-30.000000, z=1.0)
        camera_height_offset = 10.0  # Adjust the height of the camera for better visibility
        spectator = world.get_spectator()
        spectator.set_transform(carla.Transform(
            bike_location + carla.Location(z=camera_height_offset),  # Add height offset
            carla.Rotation(pitch=-30, yaw=90)  # Adjust pitch for a better angle
        ))

        print(f"Camera moved to bike position: {bike_location}")

        # Optional: Let the replay run for a specific duration
        time.sleep(10)  # Adjust this to match the duration of your recording

        print("Replay finished.")

    except Exception as e:
        print(f"An error occurred during replay: {e}")

# Function to analyze the bike's movement and determine the direction
def analyze_bike_movement():
    """
    Analyzes the bike's movement around car2 and determines the distribution of left and right.
    """
    if not os.path.exists(input_csv):
        print(f"Input CSV file not found: {input_csv}")
        return None

    # Load the dataset
    data = pd.read_csv(input_csv)

    # Calculate the distribution of "left" and "right" for car2
    car2_distribution = data["direction around car 2"].value_counts(normalize=True)  # Get proportions

    # Print the distribution
    print("\nCar 2 Distribution (Proportions):")
    print(car2_distribution)

    # Return the proportions for "left" and "right"
    left_prob = car2_distribution.get("left", 0)
    right_prob = car2_distribution.get("right", 0)

    return left_prob, right_prob

# Main function
def main():
    # Analyze the bike's movement
    left_prob, right_prob = analyze_bike_movement()

    if left_prob == 0 and right_prob == 0:
        print("No valid data for direction around car 2. No replay will be performed.")
        return

    # Use random.choices to determine which log to replay
    direction = random.choices(
        ["left", "right"],
        weights=[left_prob, right_prob],
        k=1
    )[0]

    # Replay the appropriate recording based on the probabilistic choice
    if direction == "left":
        replay_carla_log(left_recording_log)
    elif direction == "right":
        replay_carla_log(right_recording_log)

if __name__ == "__main__":
    main()