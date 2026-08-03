"""Render the processed data into a single self-contained HTML activity report.

Reads the frequency tables from ``post_data_collection.py`` and the merged topic
buckets from ``data_processor.py`` and writes ``processed_data/activity_report.html``
-- a standalone page (no external assets, no JS) summarizing who and what you
watch. This is the payoff step: the earlier stages leave raw JSON/txt tables;
this turns them into something you'd actually look at.

    python post_processing/report.py
    python post_processing/report.py --open   # ...and open it in your browser
"""

from __future__ import annotations

import argparse
import html
import json
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
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _top_items(counts: dict[str, Any] | None, limit: int = TOP_N) -> list[tuple[str, int]]:
    """Top ``limit`` (name, count) pairs from a frequency dict, highest first."""
    if not counts:
        return []
    pairs = [(str(name), int(value)) for name, value in counts.items() if name]
    pairs.sort(key=lambda pair: pair[1], reverse=True)
    return pairs[:limit]


def _bars(items: list[tuple[str, int]], total: int | None = None) -> str:
    """Render (name, count) pairs as horizontal bar rows scaled to the largest."""
    if not items:
        return '<p class="empty">No data for this section.</p>'
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
    return "\n".join(rows)


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
    """Assemble the report HTML from whatever step outputs are present.

    Returns ``None`` if nothing is available yet (the earlier steps haven't run).
    """
    creators = _load(counts_dir / "uniqueId.json")
    locations = _load(counts_dir / "locationCreated.json")
    verified = _load(counts_dir / "verified.json") or {}
    labels = _load(counts_dir / "diversificationLabels.json")
    hashtags = _load(counts_dir / "hashtagName.json")
    combined = _load(processed_dir / "json" / "combinedHashtags.json")

    if not any([creators, locations, labels, hashtags, combined]):
        return None

    verified_true = int(verified.get("true", 0))
    verified_false = int(verified.get("false", 0))
    total_posts = verified_true + verified_false or sum(int(v) for v in (creators or {}).values())
    verified_pct = verified_true / total_posts * 100 if total_posts else 0.0
    top_location = _top_items(locations, 1)

    stats = [
        _stat(f"{total_posts:,}", "posts analyzed"),
        _stat(f"{len(creators or {}):,}", "distinct creators"),
        _stat(f"{verified_pct:.0f}%", "from verified accounts"),
    ]
    if top_location:
        stats.append(_stat(top_location[0][0], "top location"))

    sections = []
    if combined:
        topic_items = [(str(bucket["name"]), int(bucket["value"])) for bucket in combined[:TOP_N]]
        sections.append(
            _section(
                "Top topics",
                "Hashtags merged by shared WordNet meaning -- the clusters of what you watch.",
                _bars(topic_items, total_posts),
            )
        )
    if creators:
        sections.append(
            _section("Top creators", "Accounts you liked most.", _bars(_top_items(creators)))
        )
    if labels:
        sections.append(
            _section(
                "Content categories",
                "TikTok's own labels for the posts you liked.",
                _bars(_top_items(labels), total_posts),
            )
        )
    if hashtags:
        sections.append(
            _section("Top hashtags", "Raw hashtags, before merging.", _bars(_top_items(hashtags)))
        )
    if locations:
        sections.append(
            _section("Locations", "Where the posts were created.", _bars(_top_items(locations)))
        )

    return _TEMPLATE.format(stats="\n".join(stats), sections="\n".join(sections))


def generate(counts_dir: Path, processed_dir: Path, output: Path, *, open_browser: bool) -> bool:
    """Write the report to ``output``. Returns False if there was nothing to render."""
    page = build_html(counts_dir, processed_dir)
    if page is None:
        log.error(
            "No processed data found. Run the scrape, post_data_collection.py, and "
            "data_processor.py steps first (see the README)."
        )
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    log.success(f"Wrote activity report to {output}")
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
  .row {{ display:grid; grid-template-columns:minmax(0,1fr) 2fr auto; align-items:center;
    gap:12px; padding:4px 0; font-size:.9rem; }}
  .label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .track {{ background:var(--track); border-radius:999px; height:9px; overflow:hidden; }}
  .fill {{ display:block; height:100%; background:var(--accent); border-radius:999px; }}
  .count {{ color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .empty {{ color:var(--muted); font-style:italic; }}
  footer {{ color:var(--muted); font-size:.8rem; text-align:center; margin-top:32px; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Your TikTok Activity</h1>
  <p>What you actually watch, from the posts you liked and favorited.</p>
</header>
<div class="stats">
{stats}
</div>
{sections}
<footer>Generated locally from your own TikTok data export. Nothing left your machine.</footer>
</div>
</body>
</html>
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--counts-dir", default=str(DEFAULT_COUNTS_DIR), help="post_data_collection JSON dir"
    )
    parser.add_argument(
        "--processed-dir", default=str(DEFAULT_PROCESSED_DIR), help="data_processor output dir"
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="where to write the report")
    parser.add_argument("--open", action="store_true", help="open the report in a browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    generate(
        Path(args.counts_dir),
        Path(args.processed_dir),
        Path(args.output),
        open_browser=args.open,
    )


if __name__ == "__main__":
    main()
