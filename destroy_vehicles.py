import carla

def destroy_all_vehicles():
    """
    Connects to the CARLA server and destroys all vehicle actors.
    """
    try:
        # Connect to the CARLA server
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(10.0)

        # Get the world
        world = client.get_world()

        # Get all actors in the world
        actors = world.get_actors()

        # Filter for vehicle actors
        vehicles = actors.filter('vehicle.*')

        print(f"Found {len(vehicles)} vehicles. Destroying them...")

        # Destroy all vehicles
        for vehicle in vehicles:
            vehicle.destroy()

        print("All vehicles have been destroyed.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    destroy_all_vehicles()