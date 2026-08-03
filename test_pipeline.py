"""Offline checks for the pipeline orchestrator. Run: python test_pipeline.py

Only the step-building logic is exercised (pure, no subprocesses spawned).
"""

from pipeline import build_steps, parse_args


def test_build_steps_full_run() -> None:
    steps = build_steps(
        parse_args(["--cookies", "c.txt", "--limit", "500", "--min-percentage", "0.3", "--open"])
    )
    by_label = dict(steps)
    assert [label for label, _ in steps] == ["scrape", "tally", "process", "report"]
    assert by_label["scrape"] == [
        "tiktok_post_scraper.py",
        "--cookies",
        "c.txt",
        "--limit",
        "500",
    ]
    assert "--min-percentage" in by_label["process"] and "0.3" in by_label["process"]
    assert "--open" in by_label["report"]


def test_build_steps_skip_scrape() -> None:
    steps = build_steps(parse_args(["--skip-scrape"]))
    assert [label for label, _ in steps] == ["tally", "process", "report"]


def test_build_steps_minimal_has_no_optional_flags() -> None:
    steps = dict(build_steps(parse_args([])))
    assert steps["scrape"] == ["tiktok_post_scraper.py"]  # no cookies/limit/verbose
    assert steps["report"] == ["post_processing/report.py"]  # no --open


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
