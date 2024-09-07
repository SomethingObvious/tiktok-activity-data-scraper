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

# Function to write the results to separate text files
def write_frequencies_to_text_files(frequencies: Dict[str, Counter], output_dir: str) -> None:
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    for key, counter in frequencies.items():
        sorted_counter = counter.most_common()  # Sort by frequency
        file_path = os.path.join(output_dir, f"{key}.txt")
        with open(file_path, 'w', encoding='utf-8') as file:
            for item, count in sorted_counter:
                file.write(f"{item}: {count}\n")

# Function to write the results to separate JSON files
def write_frequencies_to_json_files(frequencies: Dict[str, Counter], json_output_dir: str) -> None:
    # Ensure the JSON output directory exists
    os.makedirs(json_output_dir, exist_ok=True)

    for key, counter in frequencies.items():
        sorted_counter = dict(counter.most_common())  # Convert to dictionary and sort by frequency
        file_path = os.path.join(json_output_dir, f"{key}.json")
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(sorted_counter, file, ensure_ascii=False, indent=4)

# Main function to load data, count frequencies, and write them to files
def main(json_file_path: str) -> None:
    # Define the parent directory
    parent_dir = 'scraper_data'
    text_output_dir = os.path.join(parent_dir, 'post_processing/output_directory')
    json_output_dir = os.path.join(parent_dir, 'post_processing/json_output_directory')
    
    # Load data, count frequencies, and write them to text and JSON files
    data = load_json(json_file_path)
    frequencies = count_frequencies(data)
    write_frequencies_to_text_files(frequencies, text_output_dir)
    write_frequencies_to_json_files(frequencies, json_output_dir)

# Define the path to the JSON file in the new directory structure
json_file_path = os.path.join('scraper_data', 'scraper_output', 'post_data.json')
main(json_file_path)
