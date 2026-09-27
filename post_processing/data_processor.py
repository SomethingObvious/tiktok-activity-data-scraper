"""Tag each hashtag with a WordNet meaning and group the ones that mean the same thing.

Takes the hashtag counts from post_data_collection.py, drops filler tags like #fyp
and anything too rare to matter, then looks up each tag's meaning in WordNet (or in
custom_synsets.json for slang and names WordNet hasn't heard of). Tags that share a
main meaning, like #cat and #cats, end up in one topic. The results go to
processed_data/ as JSON and text.

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

import nltk
from loguru import logger as log
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from tqdm import tqdm

DEFAULT_HASHTAGS = Path("scraper_data/post_processing/json_output_directory/hashtagName.json")
DEFAULT_VERIFIED = Path("scraper_data/post_processing/output_directory/verified.txt")
DEFAULT_CUSTOM_SYNSETS = Path("post_processing/custom_synsets.json")
DEFAULT_OUTPUT_DIR = Path("processed_data")
DEFAULT_MIN_PERCENTAGE = 0.15

NOISE_WORDS = frozenset(
    {
        "fyp", "fy", "foryou", "funny", "viral", "xyz", "stich", "stitch", "comedy", "meme",
        "greenscreen", "skit", "trend", "duet", "relatable", "blowthisup", "edit",
    }
)  # fmt: skip
NOISE_PATTERN = re.compile("|".join(sorted(NOISE_WORDS - {"fy"})))

_LEMMATIZER = WordNetLemmatizer()


@cache
def synsets_for(word: str) -> tuple[str, ...]:
    """WordNet synset names for a word, most common sense first."""
    return tuple(synset.name() for synset in wordnet.synsets(word))


@cache
def lemmatize(word: str) -> str:
    """Reduce a word to its noun lemma, or its verb lemma if it has no noun form.

    WordNet already handles "cats" itself, but custom_synsets.json is a plain dict
    lookup, so this is what lets #cats find a custom entry for "cat".
    """
    noun = _LEMMATIZER.lemmatize(word, pos="n")
    return noun if noun != word else _LEMMATIZER.lemmatize(word, pos="v")


def is_noise(name: str) -> bool:
    """True for filler tags like #fyp, #edits or #animeedit, but not for #meditation."""
    name = name.lower()
    matches = list(NOISE_PATTERN.finditer(name))
    if not matches:
        return name in NOISE_WORDS
    # #meditation and #creditcard have "edit" in them too, so a filler word only
    # counts when it isn't part of some longer real word in the tag.
    return any(not _inside_real_word(name, m.start(), m.end()) for m in matches)


def _inside_real_word(name: str, start: int, end: int) -> bool:
    return any(
        synsets_for(name[a:b]) and lemmatize(name[a:b]) not in NOISE_WORDS
        for a in range(start + 1)
        for b in range(end, len(name) + 1)
    )


class Hashtag:
    """A hashtag, how many posts used it, and the synsets it matched."""

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
        lemma = lemmatize(word)
        for key in dict.fromkeys([word, lemma]):
            for synset_name in custom_synsets.get(key, []):
                if self._add(synset_name):
                    log.debug(f"#{self.name} gets custom synset {synset_name}")

        # Longer custom words inside this one, like "britishcolumbia" in a travel tag.
        for custom_word, names in custom_synsets.items():
            if len(custom_word) > 5 and custom_word in word:
                for synset_name in names:
                    if self._add(synset_name):
                        log.debug(f"#{self.name} gets custom synset {synset_name} ({custom_word})")

        for synset_name in synsets_for(word):
            self._add(synset_name)

    def topic(self) -> str:
        """The meaning this tag gets grouped by, which is its first synset if it has one."""
        return self.synsets[0] if self.synsets else f"#{self.name}"

    def __repr__(self) -> str:
        return f"{self.name}: {self.value}, {self.percentage:.2f}%"


def extract_largest_word(name: str, custom_synsets: dict[str, list[str]]) -> str | None:
    """Longest piece of a hashtag that WordNet or the custom list knows, or None.

    Hashtags run words together ("guitarpedals"), so this looks for the longest word
    inside. Pieces shorter than 4 letters only count when they're the whole tag, as
    "guitarpedals" is full of short junk like "tar" and "als".
    """
    for size in range(len(name), min(4, len(name)) - 1, -1):
        for start in range(len(name) - size + 1):
            piece = name[start : start + size]
            if synsets_for(piece) or piece in custom_synsets or lemmatize(piece) in custom_synsets:
                return piece
    return None


def load_custom_synsets(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        log.warning(f"There's no {path}, so slang and names won't get a meaning")
        return {}
    with path.open(encoding="utf-8") as file:
        custom: dict[str, list[str]] = json.load(file)
    return custom


def load_hashtags(path: Path) -> list[Hashtag]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    hashtags = []
    for name, value in data.items():
        if not name:
            continue
        try:
            hashtags.append(Hashtag(name, int(value)))
        except ValueError:
            log.warning(f"Skipped #{name}, as its count {value!r} isn't a number")
    return hashtags


def read_verified_count(path: Path) -> int:
    """Total posts, which is the verified and unverified counts added together."""
    with path.open(encoding="utf-8") as file:
        return sum(int(line.rsplit(": ", 1)[1]) for line in file if line.strip())


def filter_and_score(
    hashtags: list[Hashtag], total_posts: int, min_percentage: float
) -> list[Hashtag]:
    """Drop filler and rare tags, then scale what's left so the percentages add up to 100."""
    kept = [ht for ht in hashtags if not is_noise(ht.name)]
    for ht in kept:
        ht.percentage = ht.value / total_posts * 100 if total_posts else 0.0
    kept = [ht for ht in kept if ht.percentage >= min_percentage]

    total = sum(ht.percentage for ht in kept)
    if total:
        for ht in kept:
            ht.percentage = ht.percentage / total * 100
    return kept


def combine_hashtags(hashtags: list[Hashtag]) -> dict[str, Hashtag]:
    """Group hashtags by their main meaning, each group named after its biggest tag.

    Only the first synset counts. Grouping on any shared sense chains through the rare
    ones, so #dog would end up in the same topic as #running by way of #track.
    """
    groups: defaultdict[str, list[Hashtag]] = defaultdict(list)
    for ht in hashtags:
        groups[ht.topic()].append(ht)

    combined: dict[str, Hashtag] = {}
    for members in groups.values():
        biggest = max(members, key=lambda ht: ht.value)
        bucket = Hashtag(
            name=biggest.name,
            value=sum(ht.value for ht in members),
            percentage=sum(ht.percentage for ht in members),
        )
        for ht in members:
            bucket.unique_synsets.update(ht.unique_synsets)
        if len(members) > 1:
            log.debug(f"Grouped {', '.join(ht.name for ht in members)} under {biggest.topic()}")
        combined[biggest.name] = bucket
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
    # hashtags.json is the same table as filteredHashtags.json, under its old name.
    for stem in ("filteredHashtags", "hashtags"):
        _dump(json_dir / f"{stem}.json", filtered_data)
        with (txt_dir / f"{stem}.txt").open("w", encoding="utf-8") as file:
            file.writelines(f"{ht!r}\n" for ht in filtered_by_value)

    combined_by_value = sorted(combined.values(), key=lambda ht: ht.value, reverse=True)
    _dump(
        json_dir / "combinedHashtags.json",
        [
            {
                "name": ht.name,
                "value": ht.value,
                "percentage": ht.percentage,
                "synsets": list(ht.unique_synsets),
            }
            for ht in combined_by_value
        ],
    )
    with (txt_dir / "combinedHashtags.txt").open("w", encoding="utf-8") as file:
        file.writelines(f"{ht!r}\n" for ht in combined_by_value)

    synsets_data: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "hashtags": {}, "combined_value": 0}
    )
    for ht in filtered:
        for synset in ht.unique_synsets:
            entry = synsets_data[synset]
            entry["count"] += 1
            entry["hashtags"][ht.name] = ht.value
            entry["combined_value"] += ht.value
    sorted_synsets = sorted(
        synsets_data.items(), key=lambda item: item[1]["combined_value"], reverse=True
    )
    _dump(
        json_dir / "frequencies.json",
        {
            synset: {
                "frequency": data["count"],
                "hashtags": data["hashtags"],
                "total_combined_value": data["combined_value"],
            }
            for synset, data in sorted_synsets
        },
    )
    with (txt_dir / "frequencies.txt").open("w", encoding="utf-8") as file:
        for synset, data in sorted_synsets:
            hashtags_list = ", ".join(f"{n}: {v}" for n, v in data["hashtags"].items())
            file.write(
                f"{synset}: {data['count']} Total Combined Value: {data['combined_value']}\n"
            )
            file.write(f"  Hashtags: {hashtags_list}\n")

    overlapping: defaultdict[str, set[str]] = defaultdict(set)
    for ht1 in filtered:
        for ht2 in filtered:
            if ht1.name != ht2.name and ht1.unique_synsets & ht2.unique_synsets:
                overlapping[ht1.name].add(ht2.name)
    _dump(json_dir / "synsets.json", {k: sorted(v) for k, v in overlapping.items()})
    with (txt_dir / "synsets.txt").open("w", encoding="utf-8") as file:
        for name, overlaps in overlapping.items():
            file.write(f"{name} overlaps with: {', '.join(sorted(overlaps))}\n")

    log.info(
        f"Kept {len(filtered)} hashtags from {total_posts} posts and grouped them into "
        f"{len(combined)} topics in {output_dir}"
    )


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
    for ht in tqdm(filtered, desc="Matching synsets", unit="tag"):
        ht.add_synsets(custom_synsets)

    combined = combine_hashtags(filtered)
    write_outputs(filtered, combined, output_dir, total_posts)


def ensure_wordnet() -> None:
    try:
        wordnet.ensure_loaded()
    except LookupError:
        log.info("Downloading the WordNet corpus, which only happens once")
        nltk.download("wordnet", quiet=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_HASHTAGS), help="hashtagName.json")
    parser.add_argument("--verified", default=str(DEFAULT_VERIFIED), help="verified.txt")
    parser.add_argument(
        "--custom-synsets", default=str(DEFAULT_CUSTOM_SYNSETS), help="custom_synsets.json"
    )
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="where the results go"
    )
    parser.add_argument(
        "--min-percentage",
        type=float,
        default=DEFAULT_MIN_PERCENTAGE,
        help="drop hashtags on fewer than this %% of posts (default %(default)s)",
    )
    parser.add_argument("--verbose", action="store_true", help="log every synset match and group")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log.remove()
    log.add(sys.stderr, level="DEBUG" if args.verbose else "INFO")
    ensure_wordnet()
    try:
        process(
            Path(args.input),
            Path(args.verified),
            Path(args.custom_synsets),
            Path(args.output_dir),
            args.min_percentage,
        )
    except FileNotFoundError as exc:
        log.error(f"Couldn't find {exc.filename}. Run post_data_collection.py first.")
        sys.exit(1)


if __name__ == "__main__":
    main()
