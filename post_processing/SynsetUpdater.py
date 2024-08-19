import json
import os
import nltk
import re
from nltk.corpus import wordnet as wn

# Ensure the necessary NLTK data is downloaded
nltk.download('wordnet')

def load_custom_synsets(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}

def save_custom_synsets(file_path, custom_synsets):
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(custom_synsets, file, ensure_ascii=False, indent=4)

def print_custom_synsets_size(file_path, stage):
    custom_synsets = load_custom_synsets(file_path)
    print(f"Custom synsets size at {stage}: {len(custom_synsets)}")

def add_synsets(words, file_path):
    custom_synsets = load_custom_synsets(file_path)
    
    new_entries = {}
    for word in words:
        synset_key = f"{word}.s.1".lower()
        if word.lower() in custom_synsets:
            print(f"'{word}' already exists in custom_synsets.")
        else:
            custom_synsets[word.lower()] = [synset_key]
            new_entries[word.lower()] = synset_key
            print(f"Added new word: '{word}' with synset: '{synset_key}'")

    # Save changes if any new entries were added
    if new_entries:
        save_custom_synsets(file_path, custom_synsets)
        print("Custom synsets updated.")
    else:
        print("No new synsets were added.")

def remove_existing_words(file_path):
    custom_synsets = load_custom_synsets(file_path)
    words_to_remove = [word for word in custom_synsets if wn.synsets(word)]
    
    if words_to_remove:
        for word in words_to_remove:
            del custom_synsets[word]
            print(f"Removed '{word}' from custom_synsets as it exists in WordNet.")
        
        save_custom_synsets(file_path, custom_synsets)
        print("Updated custom_synsets.json after removing existing words.")
    else:
        print("No words in custom_synsets found in WordNet.")

def clean_punctuation(file_path):
    custom_synsets = load_custom_synsets(file_path)
    cleaned_synsets = {}
    changes_made = False
    
    for word, synsets in custom_synsets.items():
        # Remove punctuation and special characters from the word
        cleaned_word = re.sub(r'[^\w\s]', '', word).lower()
        if cleaned_word != word:
            cleaned_synsets[cleaned_word] = [s.lower() for s in synsets]
            print(f"Cleaned word: '{word}' to '{cleaned_word}'")
            changes_made = True
        else:
            cleaned_synsets[word] = [s.lower() for s in synsets]

    if changes_made:
        save_custom_synsets(file_path, cleaned_synsets)
        print("Updated custom_synsets.json after cleaning punctuation.")
    else:
        print("No words needed cleaning.")

def remove_short_words(file_path):
    custom_synsets = load_custom_synsets(file_path)
    filtered_synsets = {word: synsets for word, synsets in custom_synsets.items() if len(word) >= 4}
    
    if len(filtered_synsets) < len(custom_synsets):
        removed_words = set(custom_synsets) - set(filtered_synsets)
        for word in removed_words:
            print(f"Removed short word: '{word}' from custom_synsets.")
        
        save_custom_synsets(file_path, filtered_synsets)
        print("Updated custom_synsets.json after removing short words.")
    else:
        print("No short words were found to remove.")

def convert_to_lowercase(file_path):
    custom_synsets = load_custom_synsets(file_path)
    lowercased_synsets = {word.lower(): [s.lower() for s in synsets] for word, synsets in custom_synsets.items()}
    
    if lowercased_synsets != custom_synsets:
        save_custom_synsets(file_path, lowercased_synsets)
        print("Converted all words and synset keys to lowercase.")
    else:
        print("All words and synset keys are already in lowercase.")

def main():
    file_path = 'custom_synsets.json'
    
    # Print initial size
    print_custom_synsets_size(file_path, "start")

    start = len(load_custom_synsets(file_path))
    
    input_words = input("Enter words to add to custom synsets, separated by spaces: ")
    words = [word.strip() for word in input_words.split()]
    
    if words:
        add_synsets(words, file_path)
    else:
        print("No words entered.")
    
    remove_existing_words(file_path)
    clean_punctuation(file_path)
    remove_short_words(file_path)
    convert_to_lowercase(file_path)
    
    # Print final size
    print(f"Custom synsets size at start: {start}")
    print_custom_synsets_size(file_path, "end")

if __name__ == "__main__":
    main()
