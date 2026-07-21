"""Offline checks for the hashtag processing logic. Run: python test_data_processor.py

Needs the WordNet corpus: python -c "import nltk; nltk.download('wordnet')"
"""

from post_processing.data_processor import (
    Hashtag,
    combine_hashtags,
    extract_largest_word,
    filter_and_score,
    lemmatize,
    synsets_for,
)


def test_lemmatize() -> None:
    assert lemmatize("cats") == "cat"
    assert lemmatize("running") == "run"


def test_synsets_for() -> None:
    assert any(name.startswith("cat.n") for name in synsets_for("cat"))
    assert synsets_for("zzzznotaword") == ()


def test_extract_largest_word() -> None:
    # Finds the longest real word embedded in a run-together hashtag.
    assert extract_largest_word("guitarpedals", {}) == "guitar"
    # Too short to hold a 4-letter word.
    assert extract_largest_word("abc", {}) is None


def test_custom_synset_via_lemma() -> None:
    # "cats" is inflected; the custom key is the singular "cat". The lemmatizer
    # bridges them, which a plain dict lookup (or WordNet Morphy) would not.
    ht = Hashtag("cats", 10)
    ht.add_synsets({"cat": ["mypet.n.01"]})
    assert "mypet.n.01" in ht.unique_synsets
    assert any(name.startswith("cat.n") for name in ht.unique_synsets)


def test_filter_and_score() -> None:
    tags = [Hashtag("cats", 50), Hashtag("fyp", 40), Hashtag("dogs", 50)]
    kept = filter_and_score(tags, total_posts=1000, min_percentage=0.15)
    assert {ht.name for ht in kept} == {"cats", "dogs"}  # "fyp" is noise
    assert abs(sum(ht.percentage for ht in kept) - 100) < 1e-9  # renormalized


def test_combine_hashtags_merges_shared_synset() -> None:
    cat = Hashtag("cat", 10)
    cat.unique_synsets = {"cat.n.01"}
    kitten = Hashtag("kitten", 5)
    kitten.unique_synsets = {"cat.n.01"}
    combined = combine_hashtags([cat, kitten])
    assert set(combined) == {"cat"}  # merged into the higher-count name
    assert combined["cat"].value == 15


def test_combine_hashtags_transitive_conserves_value() -> None:
    # Transitive chain: A shares s1 with B, B shares s2 with C. All three belong
    # in one bucket, and no value may be dropped or double-counted (regression:
    # the old pairwise merge produced 31 for these inputs instead of 23).
    a = Hashtag("A", 10)
    a.unique_synsets = {"s1"}
    b = Hashtag("B", 8)
    b.unique_synsets = {"s1", "s2"}
    c = Hashtag("C", 5)
    c.unique_synsets = {"s2"}
    combined = combine_hashtags([a, b, c])
    assert set(combined) == {"A"}  # highest-count member names the bucket
    assert combined["A"].value == 23
    assert combined["A"].unique_synsets == {"s1", "s2"}  # union, not just the overlap


def test_filter_and_score_handles_zero_posts() -> None:
    # A mismatched/empty verified count must not raise ZeroDivisionError.
    kept = filter_and_score([Hashtag("cat", 5)], total_posts=0, min_percentage=0.15)
    assert kept == []


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
