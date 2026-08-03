"""Run the whole pipeline end to end: scrape -> tally -> process -> report.

Each step is the same command documented in the README, run in order from the
repo root; the run stops at the first step that fails. The steps already chain by
their default input/output paths, so the only flags here are the few you actually
vary per run.

    python pipeline.py --cookies cookies.txt              # full run
    python pipeline.py --cookies cookies.txt --limit 500 --open
    python pipeline.py --skip-scrape                      # reprocess an existing scrape
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger as log

ROOT = Path(__file__).resolve().parent
SCRAPER = "tiktok_post_scraper.py"
COLLECT = "post_processing/post_data_collection.py"
PROCESS = "post_processing/data_processor.py"
REPORT = "post_processing/report.py"


def build_steps(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    """Turn parsed args into an ordered list of (label, script-args) to run."""
    steps: list[tuple[str, list[str]]] = []

    if not args.skip_scrape:
        scrape = [SCRAPER]
        if args.cookies:
            scrape += ["--cookies", args.cookies]
        if args.limit is not None:
            scrape += ["--limit", str(args.limit)]
        if args.verbose:
            scrape.append("--verbose")
        steps.append(("scrape", scrape))

    steps.append(("tally", [COLLECT]))

    process = [PROCESS]
    if args.min_percentage is not None:
        process += ["--min-percentage", str(args.min_percentage)]
    if args.verbose:
        process.append("--verbose")
    steps.append(("process", process))

    report = [REPORT]
    if args.open:
        report.append("--open")
    steps.append(("report", report))

    return steps


def _run(label: str, script_args: list[str]) -> None:
    log.info(f"-> {label}: python {' '.join(script_args)}")
    completed = subprocess.run([sys.executable, *script_args], cwd=ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise SystemExit(f"pipeline stopped: '{label}' failed (exit {completed.returncode})")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cookies", help="cookies passed to the scrape step (see its --help)")
    parser.add_argument("--limit", type=int, help="max liked posts to scrape")
    parser.add_argument("--min-percentage", type=float, help="hashtag frequency cutoff for process")
    parser.add_argument("--open", action="store_true", help="open the HTML report when done")
    parser.add_argument("--skip-scrape", action="store_true", help="reuse an existing scrape")
    parser.add_argument("--verbose", action="store_true", help="debug logging for scrape/process")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    steps = build_steps(args)
    start = time.time()
    for label, script_args in steps:
        _run(label, script_args)
    log.success(f"Pipeline finished in {time.time() - start:.1f}s. Report at processed_data/")


if __name__ == "__main__":
    main()
