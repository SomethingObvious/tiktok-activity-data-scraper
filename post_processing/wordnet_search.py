"""Check whether WordNet knows a word, and list its senses if it does.

A word WordNet already knows doesn't need an entry in custom_synsets.json.

    python post_processing/wordnet_search.py bagel
    python post_processing/wordnet_search.py
"""

from __future__ import annotations

import argparse

import nltk
from nltk.corpus import wordnet as wn


def lookup(word: str) -> list[tuple[str, str]]:
    """(synset name, definition) pairs for a word, which is empty if WordNet doesn't know it."""
    return [(synset.name(), synset.definition()) for synset in wn.synsets(word)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("word", nargs="?", help="the word to look up (it asks if you leave it out)")
    args = parser.parse_args(argv)

    try:
        wn.ensure_loaded()
    except LookupError:
        nltk.download("wordnet", quiet=True)
    word = (args.word or input("Word to look up: ")).strip()

    senses = lookup(word)
    if not senses:
        print(f"WordNet doesn't know {word!r}, so it could use a custom entry.")
    for name, definition in senses:
        print(f"{name}: {definition}")


if __name__ == "__main__":
    main()
