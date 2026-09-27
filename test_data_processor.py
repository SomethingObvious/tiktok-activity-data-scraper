"""Tests for the hashtag tagging and grouping. Run with: python test_data_processor.py

These need the WordNet corpus, which python -m nltk.downloader wordnet fetches.
"""

import json
import tempfile
from pathlib import Path

from post_processing.data_processor import (
    Hashtag,
    combine_hashtags,
    extract_largest_word,
    filter_and_score,
    is_noise,
    lemmatize,
    process,
    read_verified_count,
    synsets_for,
)
from post_processing.synset_updater import add_words, tidy


def _tagged(name: str, value: int, custom=None) -> Hashtag:
    ht = Hashtag(name, value)
    ht.add_synsets(custom or {})
    return ht


def test_lemmatize() -> None:
    assert lemmatize("cats") == "cat"
    assert lemmatize("running") == "run"


def test_synsets_for() -> None:
    assert synsets_for("cat")[0] == "cat.n.01"
    assert synsets_for("zzzznotaword") == ()


def test_extract_largest_word() -> None:
    assert extract_largest_word("guitarpedals", {}) == "guitar"
    assert extract_largest_word("zzq", {}) is None


def test_extract_largest_word_takes_short_tags_whole() -> None:
    assert extract_largest_word("cat", {}) == "cat"
    assert extract_largest_word("gym", {}) == "gym"
    # A short word inside a longer tag is too likely to be a coincidence.
    assert extract_largest_word("zzcatzz", {}) is None


def test_custom_synset_via_lemma() -> None:
    # The custom key is "cat" and a dict lookup won't match "cats" without the lemmatizer.
    ht = _tagged("cats", 10, {"cat": ["mypet.n.01"]})
    assert ht.synsets[0] == "mypet.n.01"
    assert "cat.n.01" in ht.unique_synsets


def test_is_noise_catches_filler_tags() -> None:
    for name in ("fyp", "fy", "foryoupage", "Funny", "funnycats", "edits", "animeedit", "trending"):
        assert is_noise(name), name


def test_is_noise_keeps_real_words_with_filler_inside() -> None:
    for name in ("meditation", "meditationmusic", "credit", "creditcard", "skittles", "memento"):
        assert not is_noise(name), name


def test_filter_and_score() -> None:
    tags = [Hashtag("cats", 50), Hashtag("fyp", 40), Hashtag("dogs", 50), Hashtag("rare", 1)]
    kept = filter_and_score(tags, total_posts=1000, min_percentage=0.15)
    assert [ht.name for ht in kept] == ["cats", "dogs"]
    assert [ht.percentage for ht in kept] == [50.0, 50.0]


def test_filter_and_score_handles_zero_posts() -> None:
    assert filter_and_score([Hashtag("cat", 5)], total_posts=0, min_percentage=0.15) == []
    assert [ht.percentage for ht in filter_and_score([Hashtag("cat", 5)], 0, 0)] == [0.0]


def test_combine_hashtags_groups_by_main_meaning() -> None:
    combined = combine_hashtags([_tagged("cats", 10), _tagged("cat", 5), _tagged("kitten", 3)])
    assert sorted(combined) == ["cats", "kitten"]
    assert combined["cats"].value == 15
    assert "cat.n.01" in combined["cats"].unique_synsets


def test_combine_hashtags_keeps_side_meanings_apart() -> None:
    # #dog shares a rare sense with #track and so does #running, so grouping on any
    # shared sense would chain all three into one topic.
    tags = [_tagged(name, 10) for name in ("dog", "dogs", "track", "running", "chase")]
    combined = combine_hashtags(tags)
    assert sorted(combined) == ["chase", "dog", "running", "track"]
    assert combined["dog"].value == 20
    assert sum(ht.value for ht in combined.values()) == 50


def test_combine_hashtags_leaves_unknown_tags_alone() -> None:
    combined = combine_hashtags([Hashtag("zzq", 4), Hashtag("qqz", 2)])
    assert {name: ht.value for name, ht in combined.items()} == {"zzq": 4, "qqz": 2}


def test_tidy_cleans_keys_before_checking_wordnet() -> None:
    custom = {
        "Bagel!": ["bagel!.s.1"],
        "Rizz": ["Rizz.s.1"],
        "rizz.": ["rizz..s.1"],
        "abc": ["abc.s.1"],
    }
    add_words(custom, ["Situationship", "they"])
    assert tidy(custom) == {
        "rizz": ["rizz.s.1", "rizz..s.1"],
        "situationship": ["situationship.s.1"],
    }


def test_read_verified_count_skips_blank_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "verified.txt"
        path.write_text("False: 6\nTrue: 9\n\n", encoding="utf-8")
        assert read_verified_count(path) == 15


def test_process_writes_topics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "hashtagName.json").write_text(
            json.dumps({"cats": 6, "cat": 3, "fyp": 9, "guitarpedals": 2, "guitar": 2}),
            encoding="utf-8",
        )
        (root / "verified.txt").write_text("False: 8\nTrue: 2\n", encoding="utf-8")
        (root / "custom.json").write_text("{}", encoding="utf-8")
        process(
            root / "hashtagName.json",
            root / "verified.txt",
            root / "custom.json",
            root / "out",
            0.15,
        )
        topics = json.loads(
            (root / "out" / "json" / "combinedHashtags.json").read_text(encoding="utf-8")
        )
        text = (root / "out" / "txt" / "combinedHashtags.txt").read_text(encoding="utf-8")
    assert [(t["name"], t["value"]) for t in topics] == [("cats", 9), ("guitarpedals", 4)]
    assert text.splitlines() == ["cats: 9, 69.23%", "guitarpedals: 4, 30.77%"]


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
