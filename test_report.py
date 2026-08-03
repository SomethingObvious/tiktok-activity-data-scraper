"""Offline checks for the HTML report builder. Run: python test_report.py

Pure string transformation of the processed JSON -- no network, no live TikTok.
"""

import json
import tempfile
from pathlib import Path

from post_processing.report import _top_items, build_html, generate


def _fixture(root: Path) -> tuple[Path, Path]:
    counts = root / "counts"
    processed = root / "processed"
    (counts).mkdir(parents=True)
    (processed / "json").mkdir(parents=True)
    (counts / "uniqueId.json").write_text(json.dumps({"chef": 12, "<script>": 3}), encoding="utf-8")
    (counts / "verified.json").write_text(json.dumps({"true": 9, "false": 6}), encoding="utf-8")
    (counts / "locationCreated.json").write_text(json.dumps({"US": 10, "CA": 5}), encoding="utf-8")
    (processed / "json" / "combinedHashtags.json").write_text(
        json.dumps([{"name": "bagel", "value": 20}, {"name": "guitar", "value": 8}]),
        encoding="utf-8",
    )
    return counts, processed


def test_top_items_sorts_and_limits() -> None:
    items = _top_items({"a": 1, "b": 5, "c": 3}, limit=2)
    assert items == [("b", 5), ("c", 3)]
    assert _top_items(None) == []


def test_build_html_none_when_no_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assert build_html(root / "counts", root / "processed") is None


def test_build_html_has_sections_and_escapes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        counts, processed = _fixture(Path(tmp))
        page = build_html(counts, processed)
    assert page is not None
    assert "Top topics" in page and "Top creators" in page
    assert "bagel" in page
    assert "15" in page  # total posts = 9 verified + 6 unverified
    assert "60%" in page  # verified share = 9/15
    assert "<script>" not in page  # the malicious creator name is HTML-escaped
    assert "&lt;script&gt;" in page


def test_generate_writes_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        counts, processed = _fixture(Path(tmp))
        out = Path(tmp) / "out" / "activity_report.html"
        assert generate(counts, processed, out, open_browser=False) is True
        assert out.exists() and out.read_text(encoding="utf-8").startswith("<!doctype html>")


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
