"""Maintain ``custom_synsets.json``: add slang/names and tidy the list.

Adds any words you pass on the command line (each gets a placeholder
``word.s.1`` synset), then runs the cleanup passes: drop words WordNet already
knows, strip punctuation, drop words shorter than 4 or longer than 30 chars,
lowercase everything, and drop pronouns/determiners.

    python post_processing/synset_updater.py situationship rizz
    python post_processing/synset_updater.py            # just run the cleanup passes
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


def load_custom_synsets(file_path: Path) -> dict[str, list[str]]:
    if file_path.exists():
        with file_path.open(encoding="utf-8") as file:
            result: dict[str, list[str]] = json.load(file)
            return result
    return {}


def save_custom_synsets(file_path: Path, custom_synsets: dict[str, list[str]]) -> None:
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(custom_synsets, file, ensure_ascii=False, indent=4)


def add_synsets(words: list[str], file_path: Path) -> None:
    custom_synsets = load_custom_synsets(file_path)
    added = False
    for word in words:
        key = word.lower()
        if key in custom_synsets:
            log.info(f"'{word}' already exists in custom_synsets.")
        else:
            custom_synsets[key] = [f"{key}.s.1"]
            added = True
            log.info(f"Added '{word}' with synset '{key}.s.1'")
    if added:
        save_custom_synsets(file_path, custom_synsets)


def remove_existing_words(file_path: Path) -> None:
    custom_synsets = load_custom_synsets(file_path)
    to_remove = [word for word in custom_synsets if wn.synsets(word)]
    for word in to_remove:
        del custom_synsets[word]
        log.info(f"Removed '{word}' (already in WordNet).")
    if to_remove:
        save_custom_synsets(file_path, custom_synsets)


def clean_punctuation(file_path: Path) -> None:
    custom_synsets = load_custom_synsets(file_path)
    cleaned: dict[str, list[str]] = {}
    changed = False
    for word, synsets in custom_synsets.items():
        cleaned_word = re.sub(r"[^\w\s]", "", word).lower()
        if cleaned_word != word:
            log.info(f"Cleaned '{word}' to '{cleaned_word}'")
            changed = True
        cleaned[cleaned_word] = [s.lower() for s in synsets]
    if changed:
        save_custom_synsets(file_path, cleaned)


def remove_by_length(file_path: Path, *, min_len: int, max_len: int) -> None:
    custom_synsets = load_custom_synsets(file_path)
    kept = {w: s for w, s in custom_synsets.items() if min_len <= len(w) <= max_len}
    if len(kept) < len(custom_synsets):
        for word in set(custom_synsets) - set(kept):
            log.info(f"Removed out-of-range word: '{word}'")
        save_custom_synsets(file_path, kept)


def convert_to_lowercase(file_path: Path) -> None:
    custom_synsets = load_custom_synsets(file_path)
    lowered = {w.lower(): [s.lower() for s in syn] for w, syn in custom_synsets.items()}
    if lowered != custom_synsets:
        save_custom_synsets(file_path, lowered)
        log.info("Lowercased all words and synset keys.")


def remove_pronouns(file_path: Path) -> None:
    custom_synsets = load_custom_synsets(file_path)
    to_remove = [word for word in custom_synsets if word in PRONOUNS]
    for word in to_remove:
        del custom_synsets[word]
        log.info(f"Removed pronoun: '{word}'")
    if to_remove:
        save_custom_synsets(file_path, custom_synsets)


def clean(file_path: Path) -> None:
    """Run every tidy-up pass in order."""
    remove_existing_words(file_path)
    clean_punctuation(file_path)
    remove_by_length(file_path, min_len=4, max_len=30)
    convert_to_lowercase(file_path)
    remove_pronouns(file_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("words", nargs="*", help="words to add before cleaning")
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="custom_synsets.json path")
    args = parser.parse_args(argv)

    nltk.download("wordnet", quiet=True)
    file_path = Path(args.file)

    start = len(load_custom_synsets(file_path))
    if args.words:
        add_synsets(args.words, file_path)
    clean(file_path)
    log.info(f"custom_synsets: {start} -> {len(load_custom_synsets(file_path))} entries")


if __name__ == "__main__":
    main()
