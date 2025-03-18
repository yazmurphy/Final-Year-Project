import pandas as pd
import os

# Load the bike movement log
log_file = "bike_movement_log.csv"
data = pd.read_csv(log_file)

# Spawn coordinates of the cars
car1_spawn_x, car1_spawn_y = 99.5, -11.0
decision_y_threshold = -12.0  # Y-coordinate threshold for decision-making

# Output file for the results
output_file = "bike_analysis_results.csv"

# Determine the bike's movement classification
def classify_bike_movement(data, car1_x, decision_y_threshold):
    """
    Classify the bike's movement as 'left', 'right', or 'behind' based on its coordinates.
    """
    # Check if the bike is always behind
    if all(data['Y'] < decision_y_threshold):
        return "behind"

    # Filter the data to only include points after the bike passes the decision threshold
    post_decision_data = data[data['Y'] >= decision_y_threshold]

    # If there are no points after the threshold, default to "behind"
    if post_decision_data.empty:
        return "behind"

    # Check the bike's X coordinate after passing the threshold
    final_x = post_decision_data.iloc[-1]['X']  # Use the last X coordinate after the threshold
    if final_x > car1_x:
        return "left"
    else:
        return "right"

# Classify the bike's movement
bike_movement = classify_bike_movement(data, car1_spawn_x, decision_y_threshold)

# Calculate average speed
average_speed = data['Speed (km/h)'].mean()

# Calculate average distance to the cars
average_distance_car1 = data['Distance to Car 1 (m)'].mean()
average_distance_car2 = data['Distance to Car 2 (m)'].mean()

# Calculate smallest distance to the cars
smallest_distance_car1 = data['Distance to Car 1 (m)'].min()
smallest_distance_car2 = data['Distance to Car 2 (m)'].min()

# Determine the next ID
if os.path.exists(output_file):
    # If the file exists, read it and find the max ID
    existing_data = pd.read_csv(output_file)
    if 'id' in existing_data.columns:
        # Handle NaN values in the 'id' column
        max_id = existing_data['id'].dropna().max()
        next_id = int(max_id) + 1 if not pd.isna(max_id) else 1
    else:
        next_id = 1
else:
    # If the file doesn't exist, start with ID 1
    next_id = 1

# Prepare the results row
result_row = {
    "id": next_id,
    "direction around cars": bike_movement,
    "average speed": round(average_speed, 2),
    "average distance to car 1": round(average_distance_car1, 2),
    "average distance to car 2": round(average_distance_car2, 2),
    "smallest distance to car 1": round(smallest_distance_car1, 2),
    "smallest distance to car 2": round(smallest_distance_car2, 2),
}

# Write the results to a new CSV file
if not os.path.exists(output_file):
    # If the file doesn't exist, create it and write the header
    with open(output_file, mode='w', newline='') as file:
        header = [
            "id",
            "direction around cars",
            "average speed",
            "average distance to car 1",
            "average distance to car 2",
            "smallest distance to car 1",
            "smallest distance to car 2",
        ]
        file.write(",".join(header) + "\n")

# Append the results to the file
with open(output_file, mode='a', newline='') as file:
    file.write(
        f"{result_row['id']},{result_row['direction around cars']},"
        f"{result_row['average speed']},{result_row['average distance to car 1']},"
        f"{result_row['average distance to car 2']},{result_row['smallest distance to car 1']},"
        f"{result_row['smallest distance to car 2']}\n"
    )

# Output the results to the console
print("Analysis Results:")
print(f"Bike went around the cars on the {bike_movement} side.")
print(f"Average Speed: {average_speed:.2f} km/h")
print(f"Average Distance to Car 1: {average_distance_car1:.2f} m")
print(f"Average Distance to Car 2: {average_distance_car2:.2f} m")
print(f"Smallest Distance to Car 1: {smallest_distance_car1:.2f} m")
print(f"Smallest Distance to Car 2: {smallest_distance_car2:.2f} m")
print(f"Results have been saved to {output_file}.")