"""Check whether a word has a WordNet entry, and print its senses.

Handy when curating ``custom_synsets.json``: if a word is already in WordNet you
don't need a custom entry for it.

    python post_processing/wordnet_search.py bagel
    python post_processing/wordnet_search.py            # prompts for a word
"""

from __future__ import annotations

import argparse

import nltk
from nltk.corpus import wordnet as wn


def lookup(word: str) -> list[tuple[str, str]]:
    """Return (synset name, definition) pairs for a word; empty if unknown."""
    return [(synset.name(), synset.definition()) for synset in wn.synsets(word)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("word", nargs="?", help="word to look up")
    args = parser.parse_args(argv)

    nltk.download("wordnet", quiet=True)
    word = (args.word or input("Enter a word to check: ")).strip()

    senses = lookup(word)
    if senses:
        print(f"The word '{word}' is in WordNet.")
        for name, definition in senses:
            print(f"Synset: {name}, Definition: {definition}")
    else:
        print(f"The word '{word}' is NOT in WordNet.")


if __name__ == "__main__":
    main()
