import asyncio
from bleak import BleakScanner, BleakClient
from colorama import init, Fore
import time

# Initialize for colored print statements
init(autoreset=True)

# Shared data for BLE
shared_data = {
    "cumulative_wheel_revolutions": 0,
    "last_wheel_event_time": 0
}

# Constants
WHEEL_RADIUS_CM = 35  # Radius in cm
WHEEL_CIRCUMFERENCE_KM = 2 * 3.14159 * (WHEEL_RADIUS_CM / 100000)  # Circumference in km

# Variables to track speed
previous_revolutions = 0
previous_time = 0

def parse_csc_measurement(data):
    """
    Parse speed/cadence data from Wahoo sensor and calculate speed in km/h.
    """
    global shared_data, previous_revolutions, previous_time

    flags = data[0]
    cumulative_wheel_revolutions = int.from_bytes(data[1:5], byteorder='little')
    last_wheel_event_time_raw = int.from_bytes(data[5:7], byteorder='little')

    # Convert last wheel event time to seconds
    last_wheel_event_time_seconds = last_wheel_event_time_raw / 1024
    ms = (last_wheel_event_time_seconds * 1000) % 1000

    # Calculate speed
    if previous_time > 0:  # Ensure we have a previous time to calculate speed
        time_diff = last_wheel_event_time_seconds - previous_time
        if time_diff > 0:  # Avoid division by zero
            revolutions_diff = cumulative_wheel_revolutions - previous_revolutions
            speed_kmph = (WHEEL_CIRCUMFERENCE_KM * revolutions_diff) / (time_diff / 3600)
            print(Fore.CYAN + f"Speed: {speed_kmph:.2f} km/h")

    # Update shared data and previous values
    shared_data["cumulative_wheel_revolutions"] = cumulative_wheel_revolutions
    shared_data["last_wheel_event_time"] = last_wheel_event_time_seconds
    previous_revolutions = cumulative_wheel_revolutions
    previous_time = last_wheel_event_time_seconds

    # Print raw data
    print(Fore.GREEN + f"Flags: {flags}")
    print(Fore.GREEN + f"Cumulative Wheel Revolutions: {cumulative_wheel_revolutions}")
    print(Fore.GREEN + f"Last Wheel Event Time: {int(last_wheel_event_time_seconds)}s {int(ms)}ms")

async def find_and_connect_wahoo():
    """
    Discover and connect to the Wahoo speed sensor, then listen for notifications.
    """
    devices = await BleakScanner.discover()
    wahoo_device = None

    for device in devices:
        if device.name == "Wahoo SPEED C1E5":  # Replace with your device's name if different
            wahoo_device = device
            break

    if not wahoo_device:
        print(Fore.RED + "Wahoo SPEED C1E5 not found.")
        return

    print(Fore.BLUE + f"Found Wahoo device: {wahoo_device.name}, {wahoo_device.address}")

    async with BleakClient(wahoo_device.address) as client:
        print(Fore.BLUE + f"Connected to {wahoo_device.address}")

        # List available services and characteristics
        services = await client.get_services()
        for service in services:
            print(Fore.YELLOW + f"Service: {service.uuid}")
            for characteristic in service.characteristics:
                print(Fore.YELLOW + f"  Characteristic: {characteristic.uuid}")

        # CSC Measurement characteristic UUID
        characteristic_uuid = "00002a5b-0000-1000-8000-00805f9b34fb"

        # Start receiving notifications
        await client.start_notify(characteristic_uuid, notification_handler)

        print(Fore.BLUE + "Listening for notifications from Wahoo sensor...")
        await asyncio.sleep(30)  # Listen for 30 seconds
        await client.stop_notify(characteristic_uuid)

def notification_handler(sender, data):
    """
    Handle notifications from the Wahoo sensor.
    """
    parse_csc_measurement(data)

async def main():
    await find_and_connect_wahoo()

if __name__ == '__main__':
    asyncio.run(main())