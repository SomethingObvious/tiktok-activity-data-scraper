"""Filter, WordNet-tag, and merge the hashtag frequency table.

Takes the hashtag counts from ``post_data_collection.py``, drops generic/spam
tags and anything below a frequency threshold, looks up a WordNet synset for
each remaining hashtag (plus a hand-curated ``custom_synsets.json`` for slang and
names WordNet doesn't know), and merges hashtags that share a synset so ``#cats``
and ``#kitten`` land in the same bucket. Writes JSON and plain-text reports under
``processed_data/``.

    python post_processing/data_processor.py
    python post_processing/data_processor.py --min-percentage 0.25 --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from loguru import logger as log
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from tqdm import tqdm

DEFAULT_HASHTAGS = Path("scraper_data/post_processing/json_output_directory/hashtagName.json")
DEFAULT_VERIFIED = Path("scraper_data/post_processing/output_directory/verified.txt")
DEFAULT_CUSTOM_SYNSETS = Path("post_processing/custom_synsets.json")
DEFAULT_OUTPUT_DIR = Path("processed_data")
DEFAULT_MIN_PERCENTAGE = 0.15

# Generic/spam hashtags that carry no topical meaning.
NOISE_HASHTAGS = re.compile(
    r"fyp|foryou|funny|viral|xyz|stich|comedy|meme|greenscreen|skit|trend|"
    r"stitch|duet|relatable|blowthisup|edit",
    re.IGNORECASE,
)

_LEMMATIZER = WordNetLemmatizer()


@cache
def synsets_for(word: str) -> tuple[str, ...]:
    """WordNet synset names for a word (cached; WordNet applies its own Morphy)."""
    return tuple(synset.name() for synset in wordnet.synsets(word))


@cache
def lemmatize(word: str) -> str:
    """Reduce a word to its noun (then verb) lemma.

    Unlike WordNet's built-in Morphy, this also lets an inflected hashtag match a
    singular key in ``custom_synsets.json`` (e.g. "cats" -> "cat"), which is a
    plain dict lookup that never goes through Morphy.
    """
    noun = _LEMMATIZER.lemmatize(word, pos="n")
    return noun if noun != word else _LEMMATIZER.lemmatize(word, pos="v")


class Hashtag:
    """A hashtag plus the WordNet/custom synsets it matches."""

    def __init__(self, name: str, value: int, percentage: float = 0.0) -> None:
        self.name = name
        self.value = value
        self.percentage = percentage
        self.synsets: list[str] = []
        self.unique_synsets: set[str] = set()

    def _add(self, synset_name: str) -> bool:
        if synset_name in self.unique_synsets:
            return False
        self.synsets.append(synset_name)
        self.unique_synsets.add(synset_name)
        return True

    def add_synsets(self, custom_synsets: dict[str, list[str]]) -> None:
        word = extract_largest_word(self.name, custom_synsets)
        if word:
            self.apply_synsets(word, custom_synsets)

    def apply_synsets(self, word: str, custom_synsets: dict[str, list[str]]) -> None:
        # Exact custom match on the surface form or its lemma.
        lemma = lemmatize(word)
        for key in [word, lemma] if lemma != word else [word]:
            for synset_name in custom_synsets.get(key, []):
                if self._add(synset_name):
                    log.debug(f"custom synset {synset_name} -> #{self.name}")

        # Custom entries that appear as a substring of the word.
        for custom_word, names in custom_synsets.items():
            if len(custom_word) > 5 and custom_word in word:
                for synset_name in names:
                    if self._add(synset_name):
                        log.debug(f"custom synset {synset_name} ({custom_word}) -> #{self.name}")

        # WordNet synsets.
        for synset_name in synsets_for(word):
            self._add(synset_name)

    def __repr__(self) -> str:
        return f"{self.name}: {self.value}, {self.percentage:.2f}%"


def extract_largest_word(name: str, custom_synsets: dict[str, list[str]]) -> str | None:
    """Longest substring (>=4 chars) of ``name`` that WordNet or the custom list knows.

    Hashtags are run-together words ("guitarpedals"), so this finds the longest
    embedded real word to tag on.
    """
    max_word = ""
    length = len(name)
    for start in range(length):
        for end in range(start + 4, length + 1):
            substring = name[start:end]
            if len(substring) <= len(max_word):
                continue
            if (
                synsets_for(substring)
                or substring in custom_synsets
                or lemmatize(substring) in custom_synsets
            ):
                max_word = substring
    return max_word or None


def load_custom_synsets(path: Path) -> dict[str, list[str]]:
    if path.exists():
        with path.open(encoding="utf-8") as file:
            result: dict[str, list[str]] = json.load(file)
            return result
    log.warning(f"No custom synsets at {path}")
    return {}


def load_hashtags(path: Path) -> list[Hashtag]:
    hashtags: list[Hashtag] = []
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    for name, value in data.items():
        if not name:
            continue
        try:
            hashtags.append(Hashtag(name, int(value)))
        except ValueError:
            log.warning(f"Skipping entry due to invalid value: {name}: {value}")
    return hashtags


def read_verified_count(path: Path) -> int:
    """Total post count = sum of the verified/unverified tallies."""
    with path.open(encoding="utf-8") as file:
        return sum(int(line.strip().split(": ")[1]) for line in file)


def filter_and_score(
    hashtags: list[Hashtag], total_posts: int, min_percentage: float
) -> list[Hashtag]:
    """Drop noise and low-frequency tags, then renormalize percentages to 100%."""
    kept = [ht for ht in hashtags if not NOISE_HASHTAGS.search(ht.name) and ht.name.lower() != "fy"]

    for ht in kept:
        ht.percentage = (ht.value / total_posts) * 100 if total_posts else 0.0
    kept = [ht for ht in kept if ht.percentage >= min_percentage]

    total = sum(ht.percentage for ht in kept)
    if total:
        for ht in kept:
            ht.percentage = (ht.percentage / total) * 100
    return kept


def combine_hashtags(hashtags: list[Hashtag]) -> dict[str, Hashtag]:
    """Merge hashtags into buckets by shared synset (connected components).

    Two hashtags that share any synset land in the same bucket, transitively:
    if #cat shares a synset with #kitten and #kitten with #feline, all three
    merge. Each bucket is named after its highest-count member and carries the
    sum of its members' value/percentage and the union of their synsets, so no
    value is dropped or double-counted.
    """
    parent = {ht.name: ht.name for ht in hashtags}

    def find(name: str) -> str:
        root = name
        while parent[root] != root:
            root = parent[root]
        while parent[name] != root:  # path compression
            parent[name], name = root, parent[name]
        return root

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    # Link every pair of hashtags that share a synset, via a synset -> names index.
    by_synset: defaultdict[str, list[str]] = defaultdict(list)
    for ht in hashtags:
        for synset in ht.unique_synsets:
            by_synset[synset].append(ht.name)
    for names in by_synset.values():
        first = names[0]
        for other in names[1:]:
            log.debug(f"Combining {first} with {other}")
            union(first, other)

    groups: defaultdict[str, list[Hashtag]] = defaultdict(list)
    for ht in hashtags:
        groups[find(ht.name)].append(ht)

    combined: dict[str, Hashtag] = {}
    for members in groups.values():
        winner = max(members, key=lambda ht: ht.value)
        bucket = Hashtag(
            name=winner.name,
            value=sum(ht.value for ht in members),
            percentage=sum(ht.percentage for ht in members),
        )
        for ht in members:
            bucket.unique_synsets.update(ht.unique_synsets)
        combined[winner.name] = bucket
    return combined


def _dump(path: Path, obj: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(obj, file, ensure_ascii=False, indent=4)


def write_outputs(
    filtered: list[Hashtag],
    combined: dict[str, Hashtag],
    output_dir: Path,
    total_posts: int,
) -> None:
    """Write every JSON and text report to ``output_dir``."""
    json_dir = output_dir / "json"
    txt_dir = output_dir / "txt"
    json_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    filtered_by_value = sorted(filtered, key=lambda ht: ht.value, reverse=True)
    filtered_data = [
        {
            "name": ht.name,
            "value": ht.value,
            "percentage": ht.percentage,
            "synsets": list(ht.synsets),
            "unique_synsets": list(ht.unique_synsets),
        }
        for ht in filtered_by_value
    ]
    # filteredHashtags and hashtags hold the same table (kept for compatibility).
    for stem in ("filteredHashtags", "hashtags"):
        _dump(json_dir / f"{stem}.json", filtered_data)
        with (txt_dir / f"{stem}.txt").open("w", encoding="utf-8") as file:
            for ht in filtered_by_value:
                file.write(f"{ht.name}: {ht.value}, {ht.percentage:.2f}%\n")

    combined_data = [
        {
            "name": ht.name,
            "value": ht.value,
            "percentage": ht.percentage,
            "synsets": list(ht.unique_synsets),
        }
        for ht in sorted(combined.values(), key=lambda ht: ht.value, reverse=True)
    ]
    _dump(json_dir / "combinedHashtags.json", combined_data)
    with (txt_dir / "combinedHashtags.txt").open("w", encoding="utf-8") as file:
        for item in combined_data:
            file.write(f"{item['name']}: {item['value']}, {item['percentage']:.2f}%\n")

    # Per-synset frequencies, sorted by combined value.
    synsets_data: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "hashtags": defaultdict(int), "combined_value": 0}
    )
    for ht in filtered:
        for synset in ht.unique_synsets:
            synsets_data[synset]["count"] += 1
            synsets_data[synset]["hashtags"][ht.name] += ht.value
            synsets_data[synset]["combined_value"] += ht.value
    sorted_synsets = dict(
        sorted(synsets_data.items(), key=lambda item: item[1]["combined_value"], reverse=True)
    )
    _dump(
        json_dir / "frequencies.json",
        {
            synset: {
                "frequency": data["count"],
                "hashtags": dict(data["hashtags"]),
                "total_combined_value": data["combined_value"],
            }
            for synset, data in sorted_synsets.items()
        },
    )
    with (txt_dir / "frequencies.txt").open("w", encoding="utf-8") as file:
        for synset, data in sorted_synsets.items():
            hashtags_list = ", ".join(f"{n}: {v}" for n, v in data["hashtags"].items())
            count, value = data["count"], data["combined_value"]
            file.write(f"{synset}: {count} Total Combined Value: {value}\n")
            file.write(f"  Hashtags: {hashtags_list}\n")

    # Which hashtags share a synset with which.
    overlapping: defaultdict[str, set[str]] = defaultdict(set)
    for ht1 in filtered:
        for ht2 in filtered:
            if ht1.name != ht2.name and ht1.unique_synsets & ht2.unique_synsets:
                overlapping[ht1.name].add(ht2.name)
    _dump(json_dir / "synsets.json", {k: list(v) for k, v in overlapping.items()})
    with (txt_dir / "synsets.txt").open("w", encoding="utf-8") as file:
        for ht1_name, overlaps in overlapping.items():
            file.write(f"{ht1_name} overlaps with: {', '.join(overlaps)}\n")

    total_value = sum(ht.value for ht in filtered)
    log.info(f"Filtered to {len(filtered)} hashtags, merged into {len(combined)} buckets")
    log.info(f"Total combined value of filtered hashtags: {total_value}")
    log.info(f"Total post count: {total_posts}")


def process(
    hashtags_path: Path,
    verified_path: Path,
    custom_synsets_path: Path,
    output_dir: Path,
    min_percentage: float,
) -> None:
    custom_synsets = load_custom_synsets(custom_synsets_path)
    hashtags = load_hashtags(hashtags_path)
    total_posts = read_verified_count(verified_path)

    filtered = filter_and_score(hashtags, total_posts, min_percentage)
    for ht in tqdm(filtered, desc="matching synsets", unit="tag"):
        ht.add_synsets(custom_synsets)

    combined = combine_hashtags(filtered)
    write_outputs(filtered, combined, output_dir, total_posts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_HASHTAGS), help="hashtagName.json")
    parser.add_argument("--verified", default=str(DEFAULT_VERIFIED), help="verified.txt")
    parser.add_argument(
        "--custom-synsets", default=str(DEFAULT_CUSTOM_SYNSETS), help="custom_synsets.json"
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="report directory")
    parser.add_argument(
        "--min-percentage",
        type=float,
        default=DEFAULT_MIN_PERCENTAGE,
        help="drop hashtags below this %% of posts",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log.remove()
    log.add(sys.stderr, level="DEBUG" if args.verbose else "INFO")
    process(
        Path(args.input),
        Path(args.verified),
        Path(args.custom_synsets),
        Path(args.output_dir),
        args.min_percentage,
    )


if __name__ == "__main__":
    main()
