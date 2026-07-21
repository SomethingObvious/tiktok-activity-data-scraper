"""Offline checks for the scraper's pure helpers. Run: python test_scraper.py

Live scraping needs the network and isn't covered here; sanity-check the parser
against a saved page with `python tiktok_post_scraper.py --parse-html page.html`.
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from tiktok_post_scraper import (
    _positive_int,
    _write_output,
    binary_search,
    fetch_and_parse,
    load_urls_and_favorites_from_json,
    parse_post,
    video_id_from_url,
)


class _FakeClient:
    """Stand-in httpx client that raises a fixed error or returns a fixed status."""

    def __init__(self, exc=None, status=None, text=""):
        self.exc = exc
        self.status = status
        self.text = text
        self.calls = 0

    async def get(self, url):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return httpx.Response(self.status, text=self.text, request=httpx.Request("GET", url))


REHYDRATION = """
<html><body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{data}</script>
</body></html>
"""


def _page(item_struct: dict) -> str:
    payload = {
        "__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item_struct}}}
    }
    return REHYDRATION.format(data=json.dumps(payload))


def test_binary_search() -> None:
    ids = ["100", "200", "300"]
    assert binary_search(ids, "200")
    assert not binary_search(ids, "250")


def test_video_id_from_url() -> None:
    assert video_id_from_url("https://www.tiktok.com/@u/video/7400543367504858373") == (
        "7400543367504858373"
    )
    assert video_id_from_url("https://www.tiktok.com/@u") == ""


def test_parse_post_extracts_fields() -> None:
    item = {
        "id": "7400543367504858373",
        "desc": "Cream Cheese Bagel",
        "createTime": "1723073280",
        "video": {"duration": 50, "ratio": "540p"},
        "author": {"id": "1", "uniqueId": "chef", "nickname": "Chef", "verified": True},
        "stats": {"diggCount": 10},
        "locationCreated": "US",
        "diversificationLabels": ["Cooking"],
        "suggestedWords": ["bagel"],
        "contents": [{"textExtra": [{"hashtagName": "bagel"}]}],
    }
    post = parse_post(_page(item), ["7400543367504858373"])
    assert post["id"] == "7400543367504858373"
    assert post["desc"] == "Cream Cheese Bagel"
    assert post["video"] == {"duration": 50}  # jmespath trims to duration only
    assert post["contents"][0]["textExtra"][0]["hashtagName"] == "bagel"
    assert post["isFavorite"] is True


def test_parse_post_missing_script() -> None:
    assert parse_post("<html><body>no data here</body></html>", None) == {}


def test_load_urls_and_favorites() -> None:
    export = {
        "Activity": {
            "Like List": {
                "ItemFavoriteList": [
                    {"Date": "2024-05-02 10:00:00", "Link": "https://x/share/video/222/"},
                    {"Date": "2024-05-01 10:00:00", "Link": "https://x/share/video/111/"},
                ]
            },
            "Favorite Videos": {
                "FavoriteVideoList": [
                    {"Date": "2024-05-01 09:00:00", "Link": "https://x/video/111/"},
                    {"Date": "2024-06-01 09:00:00", "Link": "https://x/video/999/"},
                ]
            },
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.json"
        path.write_text(json.dumps(export), encoding="utf-8")
        urls, favorites = load_urls_and_favorites_from_json(str(path), limit=10)

    assert len(urls) == 2
    assert all("/video/" in url for url in urls)
    # 999 was favorited after the most recent like, so it's filtered out; 111 stays.
    assert favorites == ["111"]


def test_parse_post_missing_id_does_not_crash() -> None:
    # A post with no "id" but a favorites list must not blow up binary_search.
    item = {"desc": "x", "author": {"uniqueId": "a"}, "contents": []}
    post = parse_post(_page(item), ["111", "222"])
    assert "isFavorite" not in post  # can't flag a favorite without an id


def test_fetch_and_parse_retries_transient_then_gives_up() -> None:
    # A connect error is transient: retry up to `retries` times, then return {}
    # instead of propagating and aborting the whole batch.
    client = _FakeClient(exc=httpx.ConnectError("down"))
    result = asyncio.run(fetch_and_parse(client, "http://x/video/1", None, retries=2))
    assert result == {}
    assert client.calls == 2


def test_fetch_and_parse_backs_off_on_429() -> None:
    # 429 (Too Many Requests) must be treated as throttling and retried, not
    # dropped after a single attempt.
    client = _FakeClient(status=429)
    result = asyncio.run(fetch_and_parse(client, "http://x/video/1", None, retries=2))
    assert result == {}
    assert client.calls == 2


def test_fetch_and_parse_never_raises() -> None:
    # One bad URL raising something unexpected must not abort a gathered batch.
    bad = _FakeClient(exc=ValueError("boom"))
    ok = _FakeClient(status=404)

    async def run_batch():
        return await asyncio.gather(
            fetch_and_parse(bad, "http://x/video/1", None, retries=1),
            fetch_and_parse(ok, "http://x/video/2", None, retries=1),
        )

    results = asyncio.run(run_batch())
    assert results == [{}, {}]


def test_positive_int_rejects_non_positive() -> None:
    assert _positive_int("5") == 5
    for bad in ("0", "-3"):
        try:
            _positive_int(bad)
        except argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError(f"{bad} should be rejected")


def test_write_output_is_atomic_and_leaves_no_tmp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sub" / "post_data.json"
        _write_output(out, [{"id": "1"}])
        assert json.loads(out.read_text(encoding="utf-8")) == [{"id": "1"}]
        assert not list(out.parent.glob("*.tmp"))  # temp file was replaced, not left behind


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
