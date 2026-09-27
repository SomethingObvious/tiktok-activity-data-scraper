"""Tests for how pipeline.py builds its steps. Run with: python test_pipeline.py

Nothing here starts a subprocess.
"""

import os
import tempfile
from pathlib import Path

from pipeline import build_steps, parse_args, shown


def test_build_steps_full_run() -> None:
    steps = build_steps(
        parse_args(["--cookies", "c.txt", "--limit", "500", "--min-percentage", "0.3", "--open"])
    )
    by_label = dict(steps)
    assert [label for label, _ in steps] == ["scrape", "tally", "process", "report"]
    assert by_label["scrape"] == ["tiktok_post_scraper.py", "--cookies", "c.txt", "--limit", "500"]
    assert by_label["process"] == ["post_processing/data_processor.py", "--min-percentage", "0.3"]
    assert by_label["report"] == ["post_processing/report.py", "--open"]


def test_build_steps_skip_scrape() -> None:
    steps = build_steps(parse_args(["--skip-scrape"]))
    assert [label for label, _ in steps] == ["tally", "process", "report"]


def test_build_steps_minimal_has_no_optional_flags() -> None:
    steps = dict(build_steps(parse_args([])))
    assert steps["scrape"] == ["tiktok_post_scraper.py"]
    assert steps["report"] == ["post_processing/report.py"]


def test_cookie_file_path_survives_the_change_of_folder() -> None:
    # The steps run from the repo root, so a path relative to where you are would break.
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "cookies.txt").write_text("a=b", encoding="utf-8")
        here = Path.cwd()
        os.chdir(tmp)
        try:
            scrape = dict(build_steps(parse_args(["--cookies", "cookies.txt"])))["scrape"]
            expected = str(Path("cookies.txt").resolve())
        finally:
            os.chdir(here)
        assert scrape == ["tiktok_post_scraper.py", "--cookies", expected]


def test_shown_hides_the_cookie_value() -> None:
    assert shown(["tiktok_post_scraper.py", "--cookies", "sessionid=secret", "--verbose"]) == (
        "tiktok_post_scraper.py --cookies <cookies> --verbose"
    )


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
