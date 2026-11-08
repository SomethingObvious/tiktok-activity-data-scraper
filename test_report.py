"""Tests for the HTML report, all offline. Run with: python test_report.py"""

import json
import tempfile
from pathlib import Path

from post_processing.report import _top_items, build_html, generate, main


def _fixture(root: Path) -> Path:
    counts = root / "counts"
    counts.mkdir(parents=True)
    tables = {
        "uniqueId.json": {"chef": 12, "<script>": 3},
        "verified.json": {"true": 9, "false": 6},
        "locationCreated.json": {"Unknown": 11, "US": 3, "CA": 1},
        "diversificationLabels.json": {"Cooking": 12, "Music": 3},
        "topic.json": {"Cooking": 6, "#bagel": 3, "People and Personal Accounts": 9},
        "detail.json": {"Sourdough": 2},
    }
    for name, table in tables.items():
        (counts / name).write_text(json.dumps(table), encoding="utf-8")
    return counts


def test_top_items_sorts_and_limits() -> None:
    assert _top_items({"a": 1, "b": 5, "c": 3, "": 9}, limit=2) == [("b", 5), ("c", 3)]
    assert _top_items(None) == []


def test_build_html_none_when_no_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assert build_html(root / "counts") is None


def test_build_html_has_sections_and_escapes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = build_html(_fixture(Path(tmp)))
    assert page is not None
    for heading in (
        "Top Topics",
        "Specific Interests",
        "Top Creators",
        "Content Categories",
        "Locations",
    ):
        assert f"<h2>{heading}</h2>" in page
    assert '<div class="num">15</div>' in page  # 9 verified and 6 not
    assert '<div class="num">60%</div>' in page
    assert "People and Personal Accounts" not in page
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_top_location_skips_unknown() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = build_html(_fixture(Path(tmp)))
    assert page is not None
    assert '<div class="num">US</div><div class="lbl">top location</div>' in page


def test_topics_and_categories_show_a_share_of_posts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = build_html(_fixture(Path(tmp)))
    assert page is not None
    assert '<span class="count">6 · 40.0%</span>' in page
    assert '<span class="count">12 · 80.0%</span>' in page


def test_generate_writes_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out" / "activity_report.html"
        assert generate(_fixture(Path(tmp)), out, open_browser=False) is True
        assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_empty_report_exits_with_1() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            main(["--counts-dir", str(root / "c"), "--output", str(root / "report.html")])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("an empty report should exit with 1")
        assert not (root / "report.html").exists()


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
