"""Count how often each author, location, label, hashtag and topic shows up in the scrape.

Reads scraper_data/scraper_output/post_data.json and writes one table per field, as
text and as JSON, under scraper_data/post_processing/, where report.py reads them.
It also writes posts.csv there, with one row per post, for a spreadsheet or pandas.

Hashtags get a topic and a detail from topics.csv next to this file, so #gymtok and
#workout count toward Fitness, and #goldenretriever toward Dogs and Golden Retriever.
A tag it doesn't know stays its own topic and goes in unlabelled_tags.csv, and a row
in my_topics.csv at the top of the repo teaches it one. With --label, a language model
fills in my_topics.csv for every tag the table doesn't know.

    python post_processing/post_data_collection.py
    python post_processing/post_data_collection.py --input path/to/post_data.json
    python post_processing/post_data_collection.py --label
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeAlias

from loguru import logger as log

DEFAULT_INPUT = Path("scraper_data") / "scraper_output" / "post_data.json"
DEFAULT_OUTPUT_DIR = Path("scraper_data") / "post_processing"
TOPICS_FILE = Path(__file__).with_name("topics.csv")
# Your own labels, read after the shipped table so they win. Same columns.
MY_TOPICS_FILE = Path(__file__).parent.parent / "my_topics.csv"
FILLER = "FILLER"
# The table only knows about 50,000 of the most used tags, and these catch the endless
# spellings of #fyp and #viral past that.
FILLER_START = re.compile(r"^(fy|foryou|viral|xyz|xyb|trend|parati|4u)")
AFFIXES = re.compile(r"^tiktok|(oftiktok|tiktok|tok|s)$")
# Shorter pieces of a run-together tag are mostly accidents, like "car" in "cardio".
MIN_PIECE = 4
# Haiku labels a couple of thousand tags for a few cents, and 100 a request keeps the
# answers short enough that it rarely drops a line.
LABEL_MODEL = "claude-haiku-5-5"
LABEL_BATCH = 100
LABEL_PROMPT = """You label TikTok hashtags so a report can show what someone watches.

Each input line is `tag<TAB>seen with: other tags on the same videos`. For every line, in the
same order, write `tag<TAB>Topic<TAB>Detail` with the tag copied exactly, and nothing else.

- Topic is one of the topics listed below, copied exactly, or FILLER.
- Use the seen-with tags to tell what a short or unclear tag means. Split run-together words
  and translate tags in other languages.
- FILLER is for tags that could be on any video: fyp and viral in any spelling or language,
  moods and reactions (love, cute, omg), colours, days, years and plain numbers, engagement
  bait (follow, like, share), TikTok features (duet, stitch, capcut), and anything unreadable.
- People and Personal Accounts is for a name or handle you don't recognise. Someone well known
  goes to their field instead, with their name as the Detail.
- Detail is the specific thing the tag names, written like its English Wikipedia article title
  (goldenretriever is Dogs with Golden Retriever). Leave it empty when the tag just names the
  topic, or when you aren't sure.

Topics:
"""

Label = tuple[str, str]


def load_topics(*paths: Path) -> dict[str, Label]:
    """Read tag,topic,detail tables, with a later file's row winning over an earlier one."""
    table: dict[str, Label] = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                tag = (row.get("tag") or "").strip().lower()
                topic = (row.get("topic") or "").strip()
                if tag and topic:
                    table[tag] = (topic, (row.get("detail") or "").strip())
    return table


def label_for(tag: str, topics: Mapping[str, Label]) -> Label | None:
    """The (topic, detail) for a hashtag, FILLER for one that says nothing, or None if unknown."""
    key = re.sub(r"\W", "", tag.lower())
    for candidate in (tag, key, AFFIXES.sub("", key)):
        if candidate in topics:
            return topics[candidate]

    # Run-together tags like makeuptips or dubairealestate go by the longest known
    # tag they start or end with, as long as that one isn't filler itself.
    found = None
    for size in range(MIN_PIECE, len(key)):
        for piece in (key[:size], key[-size:]):
            if piece in topics and topics[piece][0] != FILLER:
                found = topics[piece]
    if found:
        return found
    return (FILLER, "") if FILLER_START.match(key) else None


def hashtags_of(post: dict[str, Any]) -> list[str]:
    """The post's hashtags in lower case, each once. TikTok treats #Cats and #cats as one."""
    tags = dict.fromkeys(
        (extra.get("hashtagName") or "").lower()
        for content in post.get("contents") or []
        for extra in content.get("textExtra") or []
    )
    # The empty names are @mentions.
    tags.pop("", None)
    return list(tags)


def labels_of(post: dict[str, Any], topics: Mapping[str, Label]) -> tuple[list[str], list[str]]:
    """The post's topics and details, each once. An unknown tag stands as its own #topic."""
    found: dict[str, None] = {}
    details: dict[str, None] = {}
    for tag in hashtags_of(post):
        topic, detail = label_for(tag, topics) or (f"#{tag}", "")
        if topic != FILLER:
            found[topic] = None
        if detail:
            details[detail] = None
    return list(found), list(details)


def count_frequencies(
    posts: list[dict[str, Any]], topics: Mapping[str, Label] | None = None
) -> dict[str, Counter]:
    """Count each field's values across posts, with each hashtag, topic and detail once per post.

    Filler hashtags are left out of the hashtag counts, and unknown ones get a table of their own.
    """
    counts: dict[str, Counter] = {
        key: Counter()
        for key in (
            "uniqueId",
            "verified",
            "locationCreated",
            "diversificationLabels",
            "suggestedWords",
            "hashtagName",
            "topic",
            "detail",
            "unlabelled",
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
        # Filler like #fyp would crowd out every real tag. posts.csv still has them all.
        for tag in hashtags_of(post):
            label = label_for(tag, topics or {})
            if label is None:
                counts["unlabelled"][tag] += 1
            if not label or label[0] != FILLER:
                counts["hashtagName"][tag] += 1
        found, details = labels_of(post, topics or {})
        counts["topic"].update(found)
        counts["detail"].update(details)
    return counts


def csv_row(post: dict[str, Any], topics: Mapping[str, Label] | None = None) -> dict[str, Any]:
    """One post flattened for posts.csv."""
    found, details = labels_of(post, topics or {})
    author = post.get("author") or {}
    stats = post.get("stats") or {}
    music = post.get("music") or {}
    created = post.get("createTime")
    return {
        "id": post.get("id"),
        "url": f"https://www.tiktok.com/@{author.get('uniqueId') or 'i'}/video/{post.get('id')}",
        "likedAt": post.get("likedAt"),
        # Same layout as likedAt, which is copied from the export.
        "createTime": datetime.fromtimestamp(int(created), UTC).strftime("%Y-%m-%d %H:%M:%S")
        if created
        else None,
        "author": author.get("uniqueId"),
        "verified": author.get("verified"),
        "followers": author.get("followerCount"),
        "desc": post.get("desc"),
        "hashtags": " ".join(hashtags_of(post)),
        "topics": "|".join(found),
        "details": "|".join(details),
        "sound": music.get("title"),
        "soundAuthor": music.get("authorName"),
        "originalSound": music.get("original"),
        "language": post.get("textLanguage"),
        "duration": (post.get("video") or {}).get("duration"),
        "plays": stats.get("playCount"),
        "likes": stats.get("diggCount"),
        "comments": stats.get("commentCount"),
        "shares": stats.get("shareCount"),
        "saves": stats.get("collectCount"),
        "reposts": stats.get("repostCount"),
        "location": post.get("locationCreated"),
        "labels": "|".join(post.get("diversificationLabels") or []),
        "isAd": post.get("isAd"),
        "isAigc": post.get("isAigc"),
        "isFavorite": post.get("isFavorite"),
    }


def write_csv(posts: list[dict[str, Any]], path: Path, topics: Mapping[str, Label]) -> None:
    rows = [csv_row(post, topics) for post in posts]
    path.parent.mkdir(parents=True, exist_ok=True)
    # The BOM is what makes Excel read it as UTF-8 instead of mangling every emoji.
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(csv_row({})))
        writer.writeheader()
        writer.writerows(rows)


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


def write_unlabelled(counter: Counter, path: Path) -> None:
    """Tags the table doesn't know, most used first, in the same columns as my_topics.csv."""
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["tag", "topic", "detail", "posts"])
        writer.writerows([tag, "", "", n] for tag, n in counter.most_common())


def neighbours(
    posts: list[dict[str, Any]], tags: set[str], topics: Mapping[str, Label]
) -> dict[str, list[str]]:
    """For each tag, the other tags most often on the same posts, leaving out filler."""
    near: dict[str, Counter] = defaultdict(Counter)
    for post in posts:
        on = hashtags_of(post)
        for tag in set(on) & tags:
            near[tag].update(t for t in on if t != tag and topics.get(t, ("",))[0] != FILLER)
    return {tag: [t for t, _ in counter.most_common(8)] for tag, counter in near.items()}


def parse_labels(text: str, batch: list[str], allowed: set[str]) -> dict[str, Label]:
    """Read tag<TAB>topic<TAB>detail lines, keeping only asked-for tags with a known topic."""
    found: dict[str, Label] = {}
    for line in text.splitlines():
        tag, _, rest = line.strip().partition("\t")
        topic, _, detail = (part.strip() for part in rest.partition("\t"))
        if tag in batch and (topic in allowed or topic == FILLER):
            found[tag] = (topic, "" if topic == FILLER else detail)
    return found


def append_topics(path: Path, labels: Mapping[str, Label]) -> None:
    """Add rows to a tag,topic,detail file, starting it with a header if it's new."""
    new = not path.exists() or path.stat().st_size == 0
    # A file saved by hand often has no newline at the end, which would glue two rows together.
    unfinished = not new and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as file:
        if unfinished:
            file.write("\n")
        writer = csv.writer(file)
        if new:
            writer.writerow(["tag", "topic", "detail"])
        writer.writerows([tag, *label] for tag, label in labels.items())


Ask: TypeAlias = Callable[[str, str], str | None]


def ask_model() -> Ask:
    """A function that sends one batch to the model and returns its text, or None to stop."""
    try:
        import anthropic  # only --label needs it, so it stays an optional install
    except ImportError:
        log.error("Labelling needs the anthropic package. Install it with pip install anthropic.")
        sys.exit(1)
    client = anthropic.Anthropic()

    def ask(system: str, text: str) -> str | None:
        try:
            response = client.messages.create(
                model=LABEL_MODEL,
                max_tokens=16000,
                # The topic list is the same every batch, so it's only paid for in full once.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": text}],
            )
        except TypeError:
            log.error("Couldn't find an API key. Set ANTHROPIC_API_KEY and run it again.")
            return None
        except anthropic.APIError as error:
            log.error(f"The model couldn't label this batch ({error}), so labelling stopped here")
            return None
        if response.stop_reason == "refusal":
            log.warning("The model declined one batch of tags, so those stay unlabelled")
            return ""
        return "".join(block.text for block in response.content if block.type == "text")

    return ask


def label_unknown(
    unknown: Counter,
    posts: list[dict[str, Any]],
    topics: Mapping[str, Label],
    path: Path,
    ask: Ask,
) -> dict[str, Label]:
    """Have the model label the unknown tags, most used first, saving each batch to path."""
    allowed = {topic for topic, _ in topics.values()} - {FILLER}
    system = LABEL_PROMPT + "\n".join(sorted(allowed))
    tags = [tag for tag, _ in unknown.most_common()]
    near = neighbours(posts, set(tags), topics)
    log.info(f"Asking {LABEL_MODEL} about {len(tags)} tags the topic table doesn't know")
    found: dict[str, Label] = {}
    for start in range(0, len(tags), LABEL_BATCH):
        batch = tags[start : start + LABEL_BATCH]
        lines = [f"{tag}\tseen with: {' '.join(near.get(tag, [])) or 'nothing'}" for tag in batch]
        text = ask(system, "\n".join(lines))
        if text is None:
            break
        labels = parse_labels(text, batch, allowed)
        append_topics(path, labels)
        found.update(labels)
    if found:
        log.info(f"Labelled {len(found)} of them and saved the labels to {path}")
    return found


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="the scraped post_data.json")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="where the count tables go"
    )
    parser.add_argument(
        "--topics",
        nargs="+",
        help="tag,topic,detail tables, later ones winning "
        f"(default: {TOPICS_FILE.name}, then {MY_TOPICS_FILE.name} if it exists)",
    )
    parser.add_argument(
        "--label",
        action="store_true",
        help=f"have {LABEL_MODEL} label the tags the table doesn't know, saving them to "
        f"{MY_TOPICS_FILE.name}"
        " (needs pip install anthropic and ANTHROPIC_API_KEY)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        posts = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error(f"Couldn't find {args.input}. Run tiktok_post_scraper.py first.")
        sys.exit(1)
    if args.topics:
        paths = [Path(p) for p in args.topics]
    else:
        paths = [TOPICS_FILE] + ([MY_TOPICS_FILE] if MY_TOPICS_FILE.exists() else [])
    try:
        topics = load_topics(*paths)
    except FileNotFoundError as error:
        log.error(f"Couldn't find the topic table at {error.filename}.")
        sys.exit(1)
    counts = count_frequencies(posts, topics)
    if args.label and counts["unlabelled"]:
        found = label_unknown(counts["unlabelled"], posts, topics, MY_TOPICS_FILE, ask_model())
        if found:
            topics.update(found)
            counts = count_frequencies(posts, topics)
    output_dir = Path(args.output_dir)
    write_tables(counts, output_dir)
    write_csv(posts, output_dir / "posts.csv", topics)
    write_unlabelled(counts["unlabelled"], output_dir / "unlabelled_tags.csv")
    log.info(f"Counted {len(posts)} posts into {output_dir}, with one row each in posts.csv")


if __name__ == "__main__":
    main()
