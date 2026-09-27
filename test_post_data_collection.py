"""Tests for the counting step, all offline. Run with: python test_post_data_collection.py"""

import json
import tempfile
from pathlib import Path

from post_processing.post_data_collection import count_frequencies, main

POSTS = [
    {
        "id": "1",
        "author": {"uniqueId": "chef", "verified": True},
        "locationCreated": "CA",
        "diversificationLabels": ["Cooking", "Food"],
        "suggestedWords": ["bagel"],
        "contents": [
            {"textExtra": [{"hashtagName": "Bagel"}, {"hashtagName": "bagel"}, {"hashtagName": ""}]}
        ],
    },
    # The scraper writes null for anything the post didn't have.
    {
        "id": "2",
        "author": {"uniqueId": None, "verified": None},
        "locationCreated": None,
        "diversificationLabels": None,
        "suggestedWords": None,
        "contents": None,
    },
    {"id": "3", "author": None, "contents": [{"textExtra": [{"hashtagName": "bagel"}]}]},
]


def test_count_frequencies_turns_nulls_into_unknown() -> None:
    counts = count_frequencies(POSTS)
    assert counts["uniqueId"] == {"chef": 1, "Unknown": 2}
    assert counts["verified"] == {True: 1, False: 2}
    assert counts["locationCreated"] == {"CA": 1, "Unknown": 2}
    assert counts["diversificationLabels"] == {"Cooking": 1, "Food": 1}


def test_count_frequencies_counts_a_hashtag_once_per_post() -> None:
    # #Bagel and #bagel are one tag on TikTok, and the empty name is an @mention.
    assert count_frequencies(POSTS)["hashtagName"] == {"bagel": 2}


def test_main_writes_both_kinds_of_table() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "post_data.json").write_text(json.dumps(POSTS), encoding="utf-8")
        main(["--input", str(root / "post_data.json"), "--output-dir", str(root / "out")])
        verified_json = json.loads(
            (root / "out" / "json_output_directory" / "verified.json").read_text(encoding="utf-8")
        )
        verified_txt = (root / "out" / "output_directory" / "verified.txt").read_text(
            encoding="utf-8"
        )
    assert verified_json == {"false": 2, "true": 1}
    assert verified_txt == "False: 2\nTrue: 1\n"


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
