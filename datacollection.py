import json
import os
from collections import Counter
from typing import List, Dict, Any

# Function to read JSON data from a file
def load_json(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

# Function to count frequencies in the JSON data
def count_frequencies(data: List[Dict[str, Any]]) -> Dict[str, Counter]:
    uniqueId_counter = Counter()
    verified_counter = Counter()
    locationCreated_counter = Counter()
    diversificationLabels_counter = Counter()
    suggestedWords_counter = Counter()
    hashtagName_counter = Counter()

    for item in data:
        author = item.get('author')
        if author:
            uniqueId_counter[author.get('uniqueId', 'Unknown')] += 1
            verified_counter[author.get('verified', False)] += 1
        else:
            uniqueId_counter['Unknown'] += 1
            verified_counter[False] += 1

        locationCreated_counter[item.get('locationCreated', 'Unknown')] += 1

        for label in item.get('diversificationLabels') or []:
            diversificationLabels_counter[label] += 1

        for word in item.get('suggestedWords') or []:
            suggestedWords_counter[word] += 1

        for content in item.get('contents') or []:
            for text_extra in content.get('textExtra') or []:
                hashtagName_counter[text_extra.get('hashtagName', 'Unknown')] += 1

    return {
        'uniqueId': uniqueId_counter,
        'verified': verified_counter,
        'locationCreated': locationCreated_counter,
        'diversificationLabels': diversificationLabels_counter,
        'suggestedWords': suggestedWords_counter,
        'hashtagName': hashtagName_counter
    }

# Function to write the results to separate files
def write_frequencies_to_files(frequencies: Dict[str, Counter], output_dir: str) -> None:
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    for key, counter in frequencies.items():
        sorted_counter = counter.most_common()  # Sort by frequency
        file_path = os.path.join(output_dir, f"{key}.txt")
        with open(file_path, 'w', encoding='utf-8') as file:
            for item, count in sorted_counter:
                file.write(f"{item}: {count}\n")

# Main function to load data, count frequencies and write them to files
def main(json_file_path: str, output_dir: str) -> None:
    data = load_json(json_file_path)
    frequencies = count_frequencies(data)
    write_frequencies_to_files(frequencies, output_dir)

# Replace 'your_file_path.json' with the path to your JSON file
# Replace 'output_directory' with the path to the directory where you want to save the files
json_file_path = 'post_data.json'
output_dir = 'output_directory'
main(json_file_path, output_dir)
