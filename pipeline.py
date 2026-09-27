"""Run every step in order, from the scrape to the HTML report.

Each step is the same script the README describes, run from the repo root, and the
run stops at the first one that fails. The steps already find each other's output
by their default paths, so this only passes along the few flags you'd change.

    python pipeline.py --cookies cookies.txt
    python pipeline.py --cookies cookies.txt --limit 500 --open
    python pipeline.py --skip-scrape
"""

from __future__ import annotations

import argparse
import os
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
    """Turn the parsed flags into (label, script and arguments) pairs, in run order."""
    steps: list[tuple[str, list[str]]] = []

    if not args.skip_scrape:
        scrape = [SCRAPER]
        if args.cookies:
            # The steps run from the repo root, so a relative path has to be pinned down first.
            is_file = os.path.isfile(args.cookies)  # noqa: PTH113, as it may be a 3 KB header
            cookies = str(Path(args.cookies).resolve()) if is_file else args.cookies
            scrape += ["--cookies", cookies]
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


def shown(script_args: list[str]) -> str:
    """The command as it's safe to print, with the cookie value blanked out."""
    args = list(script_args)
    if "--cookies" in args:
        args[args.index("--cookies") + 1] = "<cookies>"
    return " ".join(args)


def run_step(label: str, script_args: list[str]) -> None:
    log.info(f"Running {label}: python {shown(script_args)}")
    completed = subprocess.run([sys.executable, *script_args], cwd=ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        log.error(f"Stopped, since the {label} step failed (exit code {completed.returncode})")
        sys.exit(completed.returncode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cookies", help="cookies for the scrape step (see its --help)")
    parser.add_argument("--limit", type=int, help="only scrape this many of your most recent likes")
    parser.add_argument(
        "--min-percentage", type=float, help="hashtag cutoff for the process step, in %% of posts"
    )
    parser.add_argument("--open", action="store_true", help="open the report when it's done")
    parser.add_argument("--skip-scrape", action="store_true", help="reuse the last scrape")
    parser.add_argument(
        "--verbose", action="store_true", help="more logging from scrape and process"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    started = time.perf_counter()
    for label, script_args in build_steps(args):
        run_step(label, script_args)
    log.info(
        f"Finished in {time.perf_counter() - started:.0f} seconds. "
        f"The report is at {ROOT / 'processed_data' / 'activity_report.html'}"
    )


if __name__ == "__main__":
    main()
