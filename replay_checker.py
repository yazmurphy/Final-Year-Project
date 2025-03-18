import carla
import time
import os
def replay_recording():
    try:
        # Connect to the CARLA server
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)

        # Specify the recording file
        recording_file = "C:/CARLA_0.9.15/WindowsNoEditor/PythonAPI/examples/Prototypes/simulation_recording.log"

        # Check if the recording file exists
        if not os.path.exists(recording_file):
            print(f"Recording file not found: {recording_file}")
            return

        print(f"Replaying recording: {recording_file}")
        client.replay_file(recording_file, 0.0, 0.0, 0)  # Replay from the beginning, for the full duration

        # Wait for the server to load the replay
        time.sleep(2)

        # Get the world and list all actors in the replay
        world = client.get_world()
        actors = world.get_actors()
        print("Actors in the replay:")
        for actor in actors:
            print(f"ID: {actor.id}, Type: {actor.type_id}, Location: {actor.get_transform().location}")

        # Set the spectator camera to the bike's position
        bike_location = carla.Location(x=99.500000, y=-25.000000, z=1.0)
        camera_height_offset = 10.0  # Adjust the height of the camera for better visibility
        spectator = world.get_spectator()
        spectator.set_transform(carla.Transform(
            bike_location + carla.Location(z=camera_height_offset),  # Add height offset
            carla.Rotation(pitch=-30)  # Adjust pitch for a better angle
        ))

        print(f"Camera moved to bike position: {bike_location}")

        # Optional: Let the replay run for a specific duration
        time.sleep(10)  # Adjust this to match the duration of your recording

        print("Replay finished.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    replay_recording()