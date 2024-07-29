import json
import glob

# Literally just used to add together json files.

def append_json_files(directory):
    # Initialize an empty list to hold the combined data
    combined_data = []

    # Use glob to get all json files in the specified directory
    json_files = glob.glob(f"{directory}/*.json")

    for file in json_files:
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure the data is a list before extending the combined_data list
            if isinstance(data, list):
                combined_data.extend(data)
            else:
                print(f"File {file} does not contain a list. Skipping.")

    return combined_data

# Example usage
directory_path = r"\Users\paulz\Documents\Scaper\appender"
combined_data = append_json_files(directory_path)

# Optionally, save the combined data to a new JSON file
with open('combined_data.json', 'w', encoding='utf-8') as f:
    json.dump(combined_data, f, ensure_ascii=False, indent=4)

print(f"Combined data saved to combined_data.json")
