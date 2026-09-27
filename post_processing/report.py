"""Turn the count tables and topics into one HTML page you can open in a browser.

Reads the tables from post_data_collection.py and the topics from data_processor.py
and writes processed_data/activity_report.html. The page has no scripts and loads
nothing from the internet, and it shows whatever sections it has data for.

    python post_processing/report.py
    python post_processing/report.py --open
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any

from loguru import logger as log

DEFAULT_COUNTS_DIR = Path("scraper_data/post_processing/json_output_directory")
DEFAULT_PROCESSED_DIR = Path("processed_data")
DEFAULT_OUTPUT = DEFAULT_PROCESSED_DIR / "activity_report.html"
TOP_N = 15


def _load(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        log.warning(f"Left {path.name} out of the report, as it isn't valid JSON ({exc})")
        return None


def _top_items(counts: dict[str, Any] | None, limit: int = TOP_N) -> list[tuple[str, int]]:
    """The biggest (name, count) pairs, largest first."""
    if not counts:
        return []
    pairs = [(str(name), int(value)) for name, value in counts.items() if name]
    pairs.sort(key=lambda pair: pair[1], reverse=True)
    return pairs[:limit]


def _bars(items: list[tuple[str, int]], total: int | None = None) -> str:
    """Bar rows scaled to the largest count, with a share of total when it's given."""
    if not items:
        return '<p class="empty">There\'s nothing to show here yet.</p>'
    top = max(value for _, value in items) or 1
    rows = []
    for name, value in items:
        width = value / top * 100
        share = f" · {value / total * 100:.1f}%" if total else ""
        rows.append(
            '<div class="row">'
            f'<span class="label" title="{html.escape(name)}">{html.escape(name)}</span>'
            '<span class="track"><span class="fill" style="width:'
            f'{width:.1f}%"></span></span>'
            f'<span class="count">{value:,}{share}</span>'
            "</div>"
        )
    return '<div class="bars">' + "\n".join(rows) + "</div>"


def _section(title: str, subtitle: str, body: str) -> str:
    return (
        f'<section class="card"><h2>{html.escape(title)}</h2>'
        f'<p class="sub">{html.escape(subtitle)}</p>{body}</section>'
    )


def _stat(value: str, label: str) -> str:
    return (
        f'<div class="stat"><div class="num">{html.escape(value)}</div>'
        f'<div class="lbl">{html.escape(label)}</div></div>'
    )


def build_html(counts_dir: Path, processed_dir: Path) -> str | None:
    """Build the page from whatever step outputs exist, or None if there are none yet."""
    creators = _load(counts_dir / "uniqueId.json")
    locations = _load(counts_dir / "locationCreated.json")
    verified = _load(counts_dir / "verified.json") or {}
    labels = _load(counts_dir / "diversificationLabels.json")
    hashtags = _load(counts_dir / "hashtagName.json")
    combined = _load(processed_dir / "json" / "combinedHashtags.json")

    if not any([creators, locations, labels, hashtags, combined]):
        return None

    verified_true = int(verified.get("true", 0))
    total_posts = verified_true + int(verified.get("false", 0)) or sum(
        int(v) for v in (creators or {}).values()
    )
    verified_pct = verified_true / total_posts * 100 if total_posts else 0.0
    known_locations = {k: v for k, v in (locations or {}).items() if k != "Unknown"}
    top_location = _top_items(known_locations, 1)

    stats = [
        _stat(f"{total_posts:,}", "posts analyzed"),
        _stat(f"{len(creators or {}):,}", "different creators"),
        _stat(f"{verified_pct:.0f}%", "from verified accounts"),
    ]
    if top_location:
        stats.append(_stat(top_location[0][0], "top location"))

    sections = []
    if combined:
        topics = [(str(bucket["name"]), int(bucket["value"])) for bucket in combined[:TOP_N]]
        sections.append(
            _section(
                "Top Topics",
                "Hashtags grouped by what they mean, named after the most used one. A post with "
                "two tags from one topic counts twice, so these are tag uses rather than posts.",
                _bars(topics),
            )
        )
    if creators:
        sections.append(
            _section(
                "Top Creators", "The accounts you liked the most.", _bars(_top_items(creators))
            )
        )
    if labels:
        sections.append(
            _section(
                "Content Categories",
                "TikTok's own labels for the posts you liked, as a share of all of them.",
                _bars(_top_items(labels), total_posts),
            )
        )
    if hashtags:
        sections.append(
            _section("Top Hashtags", "Hashtags as they were written.", _bars(_top_items(hashtags)))
        )
    if locations:
        sections.append(
            _section("Locations", "Where the posts were made.", _bars(_top_items(locations)))
        )

    return _TEMPLATE.format(stats="\n".join(stats), sections="\n".join(sections))


def generate(counts_dir: Path, processed_dir: Path, output: Path, *, open_browser: bool) -> bool:
    """Write the report to output. Returns False if there was nothing to put in it."""
    page = build_html(counts_dir, processed_dir)
    if page is None:
        log.error(
            f"There's nothing in {counts_dir} or {processed_dir} to report on yet. "
            "Run the scrape, post_data_collection.py and data_processor.py first."
        )
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    log.info(f"Wrote the report to {output}")
    if open_browser:
        webbrowser.open(output.resolve().as_uri())
    return True


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TikTok Activity Report</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --ink:#1a1d21; --muted:#6b7280;
           --track:#eceef1; --accent:#fe2c55; --border:#e6e8eb; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0e0f11; --card:#17191c; --ink:#f2f3f5; --muted:#9aa1a9;
             --track:#25282c; --accent:#fe2c55; --border:#25282c; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.5; }}
  .wrap {{ max-width:820px; margin:0 auto; padding:40px 20px 64px; }}
  header h1 {{ font-size:1.7rem; margin:0 0 4px; }}
  header p {{ color:var(--muted); margin:0 0 28px; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:12px; margin-bottom:28px; }}
  .stat {{ flex:1 1 140px; background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:16px; }}
  .stat .num {{ font-size:1.6rem; font-weight:700; }}
  .stat .lbl {{ color:var(--muted); font-size:.85rem; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px;
    padding:20px 22px; margin-bottom:18px; }}
  .card h2 {{ font-size:1.1rem; margin:0 0 2px; }}
  .card .sub {{ color:var(--muted); font-size:.85rem; margin:0 0 16px; }}
  /* One grid for the whole card, so the bars line up however wide the counts get. */
  .bars {{ display:grid; grid-template-columns:minmax(0,1fr) 2fr auto; align-items:center;
    gap:8px 12px; font-size:.9rem; }}
  .row {{ display:contents; }}
  .label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .track {{ background:var(--track); border-radius:999px; height:9px; overflow:hidden; }}
  .fill {{ display:block; height:100%; background:var(--accent); border-radius:999px; }}
  .count {{ color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap;
    text-align:right; }}
  .empty {{ color:var(--muted); font-style:italic; }}
  footer {{ color:var(--muted); font-size:.8rem; text-align:center; margin-top:32px; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Your TikTok Activity</h1>
  <p>What you watch, going by the posts you liked.</p>
</header>
<div class="stats">
{stats}
</div>
{sections}
<footer>Built on your own computer from your TikTok data export.</footer>
</div>
</body>
</html>
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--counts-dir", default=str(DEFAULT_COUNTS_DIR), help="the JSON tables from the count step"
    )
    parser.add_argument(
        "--processed-dir", default=str(DEFAULT_PROCESSED_DIR), help="data_processor.py's output"
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="where the page goes")
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    written = generate(
        Path(args.counts_dir),
        Path(args.processed_dir),
        Path(args.output),
        open_browser=args.open,
    )
    if not written:
        sys.exit(1)


if __name__ == "__main__":
    main()
