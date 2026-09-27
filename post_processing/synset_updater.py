"""Add slang and names to custom_synsets.json and tidy up the list.

Each word you pass gets a placeholder synset like ``rizz.s.1``. Then every key is
lowercased and stripped of punctuation, and the entries that are too short, too
long, pronouns, or already in WordNet get dropped, since those need no custom entry.

    python post_processing/synset_updater.py situationship rizz
    python post_processing/synset_updater.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import nltk
from loguru import logger as log
from nltk.corpus import wordnet as wn

DEFAULT_FILE = Path("post_processing/custom_synsets.json")
MIN_LENGTH = 4
MAX_LENGTH = 30

PRONOUNS = {
    "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "itself", "they",
    "them", "their", "theirs", "themselves", "this", "that", "these", "those",
    "all", "another", "any", "anybody", "anyone", "anything", "both", "each",
    "either", "everybody", "everyone", "everything", "few", "many", "most",
    "neither", "nobody", "none", "noone", "nothing", "one", "other", "others",
    "several", "some", "somebody", "someone", "something", "such", "who", "whom",
    "whose", "which", "what", "whatever", "whoever", "whomever", "whichever",
}  # fmt: skip


def add_words(custom: dict[str, list[str]], words: list[str]) -> None:
    for word in words:
        key = word.lower()
        if key in custom:
            log.info(f"{word!r} is already in the list")
        else:
            custom[key] = [f"{key}.s.1"]
            log.info(f"Added {word!r} as {key}.s.1")


def tidy(custom: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return the list with clean keys and without the entries it doesn't need."""
    cleaned: dict[str, list[str]] = {}
    for word, synsets in custom.items():
        key = re.sub(r"[^\w\s]", "", word).lower()
        # Two spellings can clean up to the same key, and neither should lose its synsets.
        merged = cleaned.setdefault(key, [])
        merged.extend(s.lower() for s in synsets if s.lower() not in merged)

    # WordNet goes last, as a key only matches it once the punctuation is gone.
    tidied = {}
    for word, synsets in cleaned.items():
        if not MIN_LENGTH <= len(word) <= MAX_LENGTH:
            log.info(f"Dropped {word!r}, as it's under {MIN_LENGTH} or over {MAX_LENGTH} letters")
        elif word in PRONOUNS:
            log.info(f"Dropped the pronoun {word!r}")
        elif wn.synsets(word):
            log.info(f"Dropped {word!r}, as WordNet already knows it")
        else:
            tidied[word] = synsets
    return tidied


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("words", nargs="*", help="words to add before tidying")
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="the custom_synsets.json to edit")
    args = parser.parse_args(argv)

    try:
        wn.ensure_loaded()
    except LookupError:
        nltk.download("wordnet", quiet=True)

    path = Path(args.file)
    custom = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    before = dict(custom)
    add_words(custom, args.words)
    custom = tidy(custom)
    if custom != before:
        with path.open("w", encoding="utf-8") as file:
            json.dump(custom, file, ensure_ascii=False, indent=4)
    log.info(f"The list went from {len(before)} to {len(custom)} entries")


if __name__ == "__main__":
    main()
