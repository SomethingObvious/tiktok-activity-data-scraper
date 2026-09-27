"""Count how often each author, location, label and hashtag shows up in the scrape.

Reads scraper_data/scraper_output/post_data.json and writes one table per field, as
text and as JSON, under scraper_data/post_processing/. data_processor.py and
report.py read them from there.

    python post_processing/post_data_collection.py
    python post_processing/post_data_collection.py --input path/to/post_data.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from loguru import logger as log

DEFAULT_INPUT = Path("scraper_data") / "scraper_output" / "post_data.json"
DEFAULT_OUTPUT_DIR = Path("scraper_data") / "post_processing"


def count_frequencies(posts: list[dict[str, Any]]) -> dict[str, Counter]:
    """Count each field's values across posts, with each hashtag counted once per post."""
    counts: dict[str, Counter] = {
        key: Counter()
        for key in (
            "uniqueId",
            "verified",
            "locationCreated",
            "diversificationLabels",
            "suggestedWords",
            "hashtagName",
        )
    }
    for post in posts:
        # The scraper writes every key and leaves a missing value as null, so a
        # .get default never kicks in here.
        author = post.get("author") or {}
        counts["uniqueId"][author.get("uniqueId") or "Unknown"] += 1
        counts["verified"][bool(author.get("verified"))] += 1
        counts["locationCreated"][post.get("locationCreated") or "Unknown"] += 1
        counts["diversificationLabels"].update(post.get("diversificationLabels") or [])
        counts["suggestedWords"].update(post.get("suggestedWords") or [])

        # TikTok treats #Cats and #cats as one tag. The empty names are @mentions.
        hashtags = {
            (extra.get("hashtagName") or "").lower()
            for content in post.get("contents") or []
            for extra in content.get("textExtra") or []
        }
        hashtags.discard("")
        counts["hashtagName"].update(hashtags)
    return counts


def write_tables(counts: dict[str, Counter], output_dir: Path) -> None:
    text_dir = output_dir / "output_directory"
    json_dir = output_dir / "json_output_directory"
    text_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    for key, counter in counts.items():
        ranked = counter.most_common()
        with (text_dir / f"{key}.txt").open("w", encoding="utf-8") as file:
            file.writelines(f"{item}: {count}\n" for item, count in ranked)
        with (json_dir / f"{key}.json").open("w", encoding="utf-8") as file:
            json.dump(dict(ranked), file, ensure_ascii=False, indent=4)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="the scraped post_data.json")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="where the count tables go"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        posts = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error(f"Couldn't find {args.input}. Run tiktok_post_scraper.py first.")
        sys.exit(1)
    counts = count_frequencies(posts)
    write_tables(counts, Path(args.output_dir))
    log.info(f"Counted {len(posts)} posts into {args.output_dir}")


if __name__ == "__main__":
    main()
