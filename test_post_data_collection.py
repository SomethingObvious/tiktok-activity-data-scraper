"""Tests for the counting step, all offline. Run with: python test_post_data_collection.py"""

import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

from post_processing.post_data_collection import (
    FILLER,
    TOPICS_FILE,
    count_frequencies,
    label_for,
    label_unknown,
    load_topics,
    main,
)

TOPICS = {
    "dogs": ("Dogs", ""),
    "dog": ("Dogs", ""),
    "goldenretriever": ("Dogs", "Golden Retriever"),
    "realestate": ("Real Estate", ""),
    "makeup": ("Makeup", ""),
    "chicago": ("Chicago", ""),
    "hairstylist": ("Hair", ""),
    "fyp": (FILLER, ""),
    "love": (FILLER, ""),
}


def topic_for(tag: str) -> str | None:
    label = label_for(tag, TOPICS)
    return label[0] if label else None


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


def test_topic_for_knows_variants_and_run_together_tags() -> None:
    assert topic_for("dogs") == "Dogs"
    assert topic_for("Dogs\u2022") == "Dogs"
    assert topic_for("dogsoftiktok") == "Dogs"
    assert topic_for("dogtok") == "Dogs"
    assert topic_for("makeuptips") == "Makeup"
    assert topic_for("dubairealestate") == "Real Estate"
    # The longest known piece wins, and an ending counts as much as a start.
    assert topic_for("chicagohairstylist") == "Hair"
    # A longer tag keeps the detail of the one it was built on.
    assert label_for("goldenretrieverpuppy", TOPICS) == ("Dogs", "Golden Retriever")


def test_topic_for_filler_and_unknown_tags() -> None:
    assert topic_for("fyp") == FILLER
    assert topic_for("fyppppppppp") == FILLER
    assert topic_for("foryoupagee") == FILLER
    # A filler piece doesn't make the whole tag filler, and doesn't hide a real one.
    assert topic_for("homielove") is None
    assert topic_for("lovedogs") == "Dogs"
    assert topic_for("cardio") is None
    assert topic_for("") is None


def test_count_frequencies_counts_a_topic_once_per_post() -> None:
    posts = [
        {"contents": [{"textExtra": [{"hashtagName": n} for n in ("dog", "dogs", "fyp", "rizz")]}]},
        {"contents": [{"textExtra": [{"hashtagName": n} for n in ("dogtok", "goldenretriever")]}]},
    ]
    counts = count_frequencies(posts, TOPICS)
    assert counts["topic"] == {"Dogs": 2, "#rizz": 1}
    assert counts["detail"] == {"Golden Retriever": 1}
    assert counts["unlabelled"] == {"rizz": 1}
    assert counts["hashtagName"] == {
        "dog": 1,
        "dogs": 1,
        "rizz": 1,
        "dogtok": 1,
        "goldenretriever": 1,
    }


def test_shipped_topic_table_is_clean() -> None:
    topics = load_topics(TOPICS_FILE)
    assert len(topics) > 50000
    assert all(key == key.lower() and key.strip() == key and key for key in topics)
    assert topics["gymtok"][0] == "Fitness"
    assert topics["goldenretriever"] == ("Dogs", "Golden Retriever")
    assert topics["fyp"] == (FILLER, "")
    assert topics["2024"] == (FILLER, "")
    assert topics["vanderpumprules"] == ("Reality TV", "Vanderpump Rules")


def test_later_tables_win_and_blank_topics_are_skipped() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        shipped, mine = Path(tmp) / "a.csv", Path(tmp) / "b.csv"
        shipped.write_text("tag,topic,detail\ndogs,Dogs,\nrizz,Comedy,\n", encoding="utf-8")
        mine.write_text(
            "tag,topic,detail,posts\nRizz,Relationships,Rizz,4\nsza,,,9\n", encoding="utf-8-sig"
        )
        topics = load_topics(shipped, mine)
    assert topics == {"dogs": ("Dogs", ""), "rizz": ("Relationships", "Rizz")}


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


def test_main_writes_one_csv_row_per_post() -> None:
    post = {
        **POSTS[0],
        "desc": "line one\nline two café",
        "createTime": 1723073280,
        "likedAt": "2024-08-08 00:00:00",
        "stats": {"playCount": 900, "diggCount": 10},
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "post_data.json").write_text(json.dumps([post, POSTS[1]]), encoding="utf-8")
        main(["--input", str(root / "post_data.json"), "--output-dir", str(root)])
        with (root / "posts.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
    assert len(rows) == 2
    assert rows[0]["url"] == "https://www.tiktok.com/@chef/video/1"
    assert rows[0]["createTime"] == "2024-08-07 23:28:00"
    assert rows[0]["likedAt"] == "2024-08-08 00:00:00"
    assert rows[0]["desc"] == "line one\nline two café"
    assert rows[0]["hashtags"] == "bagel"
    assert rows[0]["labels"] == "Cooking|Food"
    assert (rows[0]["plays"], rows[0]["likes"], rows[0]["shares"]) == ("900", "10", "")
    assert rows[1]["url"] == "https://www.tiktok.com/@i/video/2"


def test_main_uses_my_topics_and_lists_what_is_left() -> None:
    post = {"contents": [{"textExtra": [{"hashtagName": n} for n in ("bagel", "zzqx", "fyp")]}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "post_data.json").write_text(json.dumps([post, post]), encoding="utf-8")
        (root / "mine.csv").write_text("tag,topic,detail\nbagel,Baking,Bagel\n", encoding="utf-8")
        topics = ["--topics", str(TOPICS_FILE), str(root / "mine.csv")]
        main(["--input", str(root / "post_data.json"), "--output-dir", str(root), *topics])
        with (root / "posts.csv").open(encoding="utf-8-sig", newline="") as file:
            row = next(csv.DictReader(file))
        left = (root / "unlabelled_tags.csv").read_text(encoding="utf-8-sig")
    assert (row["topics"], row["details"]) == ("Baking|#zzqx", "Bagel")
    assert left == "tag,topic,detail,posts\nzzqx,,,2\n"


def test_label_unknown_keeps_valid_answers_and_saves_them() -> None:
    posts = [{"contents": [{"textExtra": [{"hashtagName": n} for n in ("pupcup", "dogs", "fyp")]}]}]
    asked = []

    def ask(system: str, text: str) -> str:
        asked.append((system, text))
        # One good row, a FILLER with a stray detail, a made-up topic and a tag nobody asked about.
        return "pupcup\tDogs\tPuppuccino\nwhatever\tFILLER\tx\nzzqx\tNot A Topic\t\nother\tDogs\t\n"

    unknown = Counter({"pupcup": 3, "whatever": 1, "zzqx": 1})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "my_topics.csv"
        path.write_text("tag,topic,detail\nbagel,Baking,Bagel", encoding="utf-8")
        found = label_unknown(unknown, posts, TOPICS, path, ask)
        saved = load_topics(path)
    assert found == {"pupcup": ("Dogs", "Puppuccino"), "whatever": (FILLER, "")}
    assert saved == {"bagel": ("Baking", "Bagel"), **found}
    system, text = asked[0]
    assert "\nDogs\n" in system and "\nFILLER\n" not in system
    assert text.splitlines()[0] == "pupcup\tseen with: dogs"


def test_label_unknown_stops_when_the_model_does() -> None:
    unknown = Counter({f"tag{i}": 1 for i in range(250)})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "my_topics.csv"
        assert label_unknown(unknown, [], TOPICS, path, lambda _s, _t: None) == {}
        assert not path.exists() or load_topics(path) == {}


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
