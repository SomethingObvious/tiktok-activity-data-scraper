import os
import re
import json
from nltk.corpus import wordnet
from collections import defaultdict

# Ensure nltk wordnet is downloaded paste nltk.download('wordnet')
import nltk

# Define the Hashtag class
class Hashtag:
    def __init__(self, name, value, percentage=0):
        self.name = name
        self.value = value
        self.percentage = percentage
        self.synsets = []
        self.unique_synsets = set()
        self.custom_synsets = {}

    def load_custom_synsets(self):
        if os.path.exists('post_processing/custom_synsets.json'):
            with open('post_processing/custom_synsets.json', 'r', encoding='utf-8') as file:
                self.custom_synsets = json.load(file)

    def add_synsets(self):
        self.load_custom_synsets()
        largest_word = self.extract_largest_word()
        if largest_word:
            self.apply_synsets(largest_word)

    def extract_largest_word(self):
        max_word = ""
        length = len(self.name)
        for start in range(length):
            for end in range(start + 4, length + 1):  # Start with words of length 4
                substring = self.name[start:end]
                if wordnet.synsets(substring) or substring in self.custom_synsets:
                    if len(substring) > len(max_word):
                        max_word = substring
        return max_word if max_word else None

    def apply_synsets(self, word):
        # Check for exact word in custom_synsets
        if word in self.custom_synsets:
            custom_synsets = self.custom_synsets[word]
            for synset_name in custom_synsets:
                if synset_name not in self.synsets:
                    self.synsets.append(synset_name)
                    self.unique_synsets.add(synset_name)
                    print(f"Added custom synset: {synset_name} to hashtag: {self.name}")

        # Check for substrings in custom_synsets
        for custom_word in self.custom_synsets:
            if len(custom_word) > 5 and custom_word in word:
                custom_synsets = self.custom_synsets[custom_word]
                for synset_name in custom_synsets:
                    if synset_name not in self.synsets:
                        self.synsets.append(synset_name)
                        self.unique_synsets.add(synset_name)
                        print(f"Added custom synset: {synset_name} for substring: {custom_word} to hashtag: {self.name}")

        # Apply WordNet synsets
        synsets = wordnet.synsets(word)
        for synset in synsets:
            synset_name = synset.name()
            if synset_name not in self.synsets:
                self.synsets.append(synset_name)
                self.unique_synsets.add(synset_name)


    def __repr__(self):
        return f"{self.name}: {self.value}, {self.percentage:.2f}%"

# Create directories if they do not exist
os.makedirs('processed_data/json', exist_ok=True)
os.makedirs('processed_data/txt', exist_ok=True)

# Read hashtags from file with utf-8 encoding
hashtags = []

with open('scraper_data/json_output_directory/hashtagName.json', 'r', encoding='utf-8') as file:
    data = json.load(file)
    for name, value in data.items():
        if name:  # Ensure the hashtag name is not empty
            try:
                hashtags.append(Hashtag(name, int(value)))
            except ValueError:
                print(f"Skipping entry due to invalid value: {name}: {value}")

# Remove hashtags containing specific terms
filtered_hashtags = [ht for ht in hashtags if not re.search(r'fyp|foryou|funny|viral|xyz|stich|comedy|meme|greenscreen|skit|trend|stitch|duet|relatable|blowthisup|edit', ht.name, re.IGNORECASE)]

# Remove hashtags that are exactly "fy"
filtered_hashtags = [ht for ht in filtered_hashtags if ht.name.lower() != "fy"]

# Read verified counts from file with utf-8 encoding
with open('scraper_data/output_directory/verified.txt', 'r', encoding='utf-8') as file:
    verified_counts = sum(int(line.strip().split(': ')[1]) for line in file)

# Calculate initial percentages
total_count = sum(ht.value for ht in filtered_hashtags)
for ht in filtered_hashtags:
    ht.percentage = (ht.value / verified_counts) * 100

# Filter out hashtags with percentages less than 0.15%
filtered_hashtags = [ht for ht in filtered_hashtags if ht.percentage >= 0.15]

# Recalculate to ensure the sum of percentages is 100%
total_percentage = sum(ht.percentage for ht in filtered_hashtags)
for ht in filtered_hashtags:
    ht.percentage = (ht.percentage / total_percentage) * 100

# Add synsets (including custom synsets) to each hashtag
for ht in filtered_hashtags:
    ht.add_synsets()

# Combine hashtags with overlapping synsets iteratively
def combine_hashtags(hashtags):
    combined_hashtags = {}
    hashtags_dict = {ht.name: ht for ht in hashtags}
    combined_set = set()
    to_combine = True

    while to_combine:
        to_combine = False
        new_combined_hashtags = {}
        processed_pairs = set()

        # Iterate through all possible pairs
        for name1, ht1 in list(hashtags_dict.items()):
            if name1 in combined_set:
                continue
            for name2, ht2 in list(hashtags_dict.items()):
                if name1 != name2 and (name1, name2) not in processed_pairs and (name2, name1) not in processed_pairs:
                    overlapping_synsets = ht1.unique_synsets.intersection(ht2.unique_synsets)
                    if overlapping_synsets:
                        print(f"Combining {name1} with {name2}")

                        to_combine = True
                        combined_set.add(name1)
                        combined_set.add(name2)
                        processed_pairs.add((name1, name2))
                        
                        combined_name = name1 if ht1.value >= ht2.value else name2
                        
                        if combined_name not in new_combined_hashtags:
                            new_combined_hashtags[combined_name] = Hashtag(
                                name=combined_name,
                                value=ht1.value + ht2.value,
                                percentage=ht1.percentage + ht2.percentage
                            )
                            new_combined_hashtags[combined_name].unique_synsets.update(overlapping_synsets)
                        else:
                            if combined_name == name1:
                                new_combined_hashtags[combined_name].value += ht2.value
                                new_combined_hashtags[combined_name].percentage += ht2.percentage
                            else:
                                new_combined_hashtags[combined_name].value += ht1.value
                                new_combined_hashtags[combined_name].percentage += ht1.percentage
                            
                            new_combined_hashtags[combined_name].unique_synsets.update(overlapping_synsets)

        # Add hashtags that were not combined
        for name, ht in hashtags_dict.items():
            if name not in combined_set:
                combined_hashtags[name] = ht

        # Update combined hashtags with newly combined ones
        for name, ht in new_combined_hashtags.items():
            if name in combined_hashtags:
                combined_hashtags[name].value += ht.value
                combined_hashtags[name].percentage += ht.percentage
                combined_hashtags[name].unique_synsets.update(ht.unique_synsets)
            else:
                combined_hashtags[name] = ht

        hashtags_dict = {ht.name: ht for ht in combined_hashtags.values()}

    return combined_hashtags

# Execute combining hashtags
combined_hashtags = combine_hashtags(filtered_hashtags)

# Write filtered hashtags to JSON and TXT, sorted by value descending
filtered_hashtags_data = sorted([
    {
        "name": ht.name,
        "value": ht.value,
        "percentage": ht.percentage,
        "synsets": [synset for synset in ht.synsets],
        "unique_synsets": [synset for synset in ht.unique_synsets]
    }
    for ht in filtered_hashtags
], key=lambda x: x["value"], reverse=True)

with open('processed_data/json/filteredHashtags.json', 'w', encoding='utf-8') as file:
    json.dump(filtered_hashtags_data, file, ensure_ascii=False, indent=4)

with open('processed_data/txt/filteredHashtags.txt', 'w', encoding='utf-8') as file:
    for ht in filtered_hashtags:
        file.write(f"{ht.name}: {ht.value}, {ht.percentage:.2f}%\n")

# Write combined hashtags to JSON and TXT, sorted by value descending
combined_hashtags_data = sorted([
    {
        "name": ht.name,
        "value": ht.value,
        "percentage": ht.percentage,
        "synsets": [synset for synset in ht.unique_synsets]
    }
    for ht in combined_hashtags.values()
], key=lambda x: x["value"], reverse=True)

with open('processed_data/json/combinedHashtags.json', 'w', encoding='utf-8') as file:
    json.dump(combined_hashtags_data, file, ensure_ascii=False, indent=4)

with open('processed_data/txt/combinedHashtags.txt', 'w', encoding='utf-8') as file:
    for ht in combined_hashtags_data:
        file.write(f"{ht['name']}: {ht['value']}, {ht['percentage']:.2f}%\n")

# Save hashtags to JSON and TXT, sorted by value descending
hashtags_data = sorted([
    {
        "name": ht.name,
        "value": ht.value,
        "percentage": ht.percentage,
        "synsets": [synset for synset in ht.synsets],
        "unique_synsets": [synset for synset in ht.unique_synsets]
    }
    for ht in filtered_hashtags
], key=lambda x: x["value"], reverse=True)

with open('processed_data/json/hashtags.json', 'w', encoding='utf-8') as file:
    json.dump(hashtags_data, file, ensure_ascii=False, indent=4)

with open('processed_data/txt/hashtags.txt', 'w', encoding='utf-8') as file:
    for ht in filtered_hashtags:
        file.write(f"{ht.name}: {ht.value}, {ht.percentage:.2f}%\n")

# Prepare synsets data with combined values
synsets_data = defaultdict(lambda: {'count': 0, 'hashtags': defaultdict(int), 'combined_value': 0})

for ht in filtered_hashtags:
    for synset in ht.unique_synsets:
        synsets_data[synset]['count'] += 1
        synsets_data[synset]['hashtags'][ht.name] += ht.value
        synsets_data[synset]['combined_value'] += ht.value

# Sort the frequencies by combined value in descending order
sorted_synsets_data = dict(sorted(synsets_data.items(), key=lambda item: item[1]['combined_value'], reverse=True))

# Write frequencies to JSON
frequencies_json_data = {
    synset: {
        'frequency': data['count'],
        'hashtags': dict(data['hashtags']),
        'total_combined_value': data['combined_value']
    }
    for synset, data in sorted_synsets_data.items()
}

with open('processed_data/json/frequencies.json', 'w', encoding='utf-8') as file:
    json.dump(frequencies_json_data, file, ensure_ascii=False, indent=4)

# Write frequencies to TXT
with open('processed_data/txt/frequencies.txt', 'w', encoding='utf-8') as file:
    for synset, data in sorted_synsets_data.items():
        hashtags_list = ', '.join([f"{name}: {value}" for name, value in data['hashtags'].items()])
        file.write(f"{synset}: {data['count']} Total Combined Value: {data['combined_value']}\n")
        file.write(f"  Hashtags: {hashtags_list}\n")



# Find overlapping synsets
overlapping_synsets = defaultdict(set)
for ht1 in filtered_hashtags:
    for ht2 in filtered_hashtags:
        if ht1.name != ht2.name:
            common_synsets = ht1.unique_synsets.intersection(ht2.unique_synsets)
            if common_synsets:
                overlapping_synsets[ht1.name].add(ht2.name)

# Convert overlapping_synsets to a serializable format
serializable_overlapping_synsets = {
    key: list(value) for key, value in overlapping_synsets.items()
}

# Write overlapping synsets to JSON
with open('processed_data/json/synsets.json', 'w', encoding='utf-8') as file:
    json.dump(serializable_overlapping_synsets, file, ensure_ascii=False, indent=4)

# Write overlapping synsets to TXT
with open('processed_data/txt/synsets.txt', 'w', encoding='utf-8') as file:
    for ht1, overlaps in overlapping_synsets.items():
        file.write(f"{ht1} overlaps with: {', '.join(overlaps)}\n")

# Verify the sum of all percentages
total_adjusted_percentage = sum(ht.percentage for ht in filtered_hashtags)
print(f"\nSum of all adjusted percentages: {total_adjusted_percentage:.2f}%")

# Calculate the total percentage of all filtered hashtags
total_filtered_percentage = sum(ht.value for ht in filtered_hashtags)

# Print the total value
print(f"Total combined value of filtered hashtags: {total_filtered_percentage}")

# Print verified value
print(f"Total post count: {verified_counts} \n")



