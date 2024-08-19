import nltk
from nltk.corpus import wordnet as wn

# Make sure the WordNet data is downloaded
nltk.download('wordnet')

def check_word_in_wordnet(word):
    synsets = wn.synsets(word)
    if synsets:
        print(f"The word '{word}' is in WordNet.")
        for synset in synsets:
            print(f"Synset: {synset.name()}, Definition: {synset.definition()}")
    else:
        print(f"The word '{word}' is NOT in WordNet.")

# Example usage
word = input("Enter a word to check: ").strip()
check_word_in_wordnet(word)
