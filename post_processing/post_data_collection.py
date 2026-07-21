"""Tally scraped post data into frequency counts.

Reads the raw scrape (``scraper_data/scraper_output/post_data.json`` by default)
and writes per-field frequency tables -- authors, verified flag, location,
diversification labels, suggested words, and hashtags -- as both ``.txt`` and
``.json`` under ``scraper_data/post_processing/``. ``data_processor.py`` reads
the hashtag and verified tables from here.

    python post_processing/post_data_collection.py
    python post_processing/post_data_collection.py --input path/to/post_data.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from loguru import logger as log

DEFAULT_INPUT = Path("scraper_data") / "scraper_output" / "post_data.json"
DEFAULT_OUTPUT_DIR = Path("scraper_data") / "post_processing"


def load_json(file_path: str) -> list[dict[str, Any]]:
    with Path(file_path).open(encoding="utf-8") as file:
        return json.load(file)


def count_frequencies(data: list[dict[str, Any]]) -> dict[str, Counter]:
    """Count occurrences of each field value across all posts."""
    unique_id_counter: Counter[str] = Counter()
    verified_counter: Counter[bool] = Counter()
    location_created_counter: Counter[str] = Counter()
    diversification_labels_counter: Counter[str] = Counter()
    suggested_words_counter: Counter[str] = Counter()
    hashtag_name_counter: Counter[str] = Counter()

    for item in data:
        author = item.get("author")
        if author:
            unique_id_counter[author.get("uniqueId", "Unknown")] += 1
            verified_counter[author.get("verified", False)] += 1
        else:
            unique_id_counter["Unknown"] += 1
            verified_counter[False] += 1

        location_created_counter[item.get("locationCreated", "Unknown")] += 1

        for label in item.get("diversificationLabels") or []:
            diversification_labels_counter[label] += 1

        for word in item.get("suggestedWords") or []:
            suggested_words_counter[word] += 1

        for content in item.get("contents") or []:
            for text_extra in content.get("textExtra") or []:
                hashtag_name_counter[text_extra.get("hashtagName", "Unknown")] += 1

    return {
        "uniqueId": unique_id_counter,
        "verified": verified_counter,
        "locationCreated": location_created_counter,
        "diversificationLabels": diversification_labels_counter,
        "suggestedWords": suggested_words_counter,
        "hashtagName": hashtag_name_counter,
    }


def write_frequencies_to_text_files(frequencies: dict[str, Counter], output_dir: str) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for key, counter in frequencies.items():
        with (output_path / f"{key}.txt").open("w", encoding="utf-8") as file:
            for item, count in counter.most_common():
                file.write(f"{item}: {count}\n")


def write_frequencies_to_json_files(frequencies: dict[str, Counter], json_output_dir: str) -> None:
    json_output_path = Path(json_output_dir)
    json_output_path.mkdir(parents=True, exist_ok=True)
    for key, counter in frequencies.items():
        with (json_output_path / f"{key}.json").open("w", encoding="utf-8") as file:
            json.dump(dict(counter.most_common()), file, ensure_ascii=False, indent=4)


def main(json_file_path: str, output_dir: str) -> None:
    parent_dir = Path(output_dir)
    text_output_dir = parent_dir / "output_directory"
    json_output_dir = parent_dir / "json_output_directory"

    data = load_json(json_file_path)
    frequencies = count_frequencies(data)
    write_frequencies_to_text_files(frequencies, str(text_output_dir))
    write_frequencies_to_json_files(frequencies, str(json_output_dir))
    log.success(f"Counted {len(data)} posts into {parent_dir}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="scraped post_data.json")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="where to write the frequency tables"
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    _args = parse_args()
    main(_args.input, _args.output_dir)
