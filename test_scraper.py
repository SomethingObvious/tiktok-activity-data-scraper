"""Tests for the scraper, all offline. Run with: python test_scraper.py

Nothing here talks to TikTok. To check the parser against a real page, save one and
run python tiktok_post_scraper.py --parse-html page.html.
"""

import argparse
import asyncio
import contextlib
import io
import json
import tempfile
from collections import Counter
from pathlib import Path

import httpx
from tenacity import wait_none

import tiktok_post_scraper as scraper
from tiktok_post_scraper import (
    InputError,
    build_client,
    fetch_and_parse,
    is_challenge_page,
    load_cookies,
    load_existing,
    load_export,
    parse_cookie_header,
    parse_post,
    positive_int,
    scrape_posts,
    video_id_from_url,
    write_output,
)

# The real backoff waits a second or more between tries.
scraper.RETRY_WAIT = wait_none()

REHYDRATION = """
<html><body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{data}</script>
</body></html>
"""

CHALLENGE_HTML = (
    '<html><body>Please wait... <p id="wci" class="_wafchallengeid"></p>'
    '<script src="https://x/obj/waf-aiso/dd9808.js"></script></body></html>'
)


def _page(item_struct: dict) -> str:
    detail = {"itemInfo": {"itemStruct": item_struct}}
    return REHYDRATION.format(
        data=json.dumps({"__DEFAULT_SCOPE__": {"webapp.video-detail": detail}})
    )


def _post_page(video_id: str) -> str:
    return _page({"id": video_id, "desc": f"post {video_id}", "author": {"uniqueId": "chef"}})


class _FakeClient:
    """Stands in for httpx.AsyncClient, raising one error or answering one status."""

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


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _write_json(folder: str, name: str, data) -> Path:
    path = Path(folder) / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _raises(exc_type, func, *args, **kwargs) -> str:
    try:
        func(*args, **kwargs)
    except exc_type as exc:
        return str(exc)
    raise AssertionError(f"{func.__name__} didn't raise {exc_type.__name__}")


def test_video_id_from_url() -> None:
    assert video_id_from_url("https://www.tiktok.com/@u/video/7400543367504858373") == (
        "7400543367504858373"
    )
    assert video_id_from_url("https://www.tiktokv.com/share/video/222/") == "222"
    assert video_id_from_url("https://www.tiktok.com/@u") == ""


def test_parse_post_keeps_the_queried_fields() -> None:
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
    post = parse_post(_page(item), {"7400543367504858373"})
    assert post["id"] == "7400543367504858373"
    assert post["desc"] == "Cream Cheese Bagel"
    assert post["video"] == {"duration": 50}
    assert post["contents"] == [{"textExtra": [{"hashtagName": "bagel"}]}]
    assert post["isFavorite"] is True


def test_favourite_flag_needs_the_list() -> None:
    assert parse_post(_post_page("5"), {"6"})["isFavorite"] is False
    assert "isFavorite" not in parse_post(_post_page("5"), None)


def test_parse_post_says_when_the_script_is_missing() -> None:
    message = _raises(ValueError, parse_post, "<html><body>no data here</body></html>")
    assert "__UNIVERSAL_DATA_FOR_REHYDRATION__" in message


def test_parse_post_says_when_the_post_is_gone() -> None:
    gone = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 10204, "statusMsg": ""}}}
    message = _raises(ValueError, parse_post, REHYDRATION.format(data=json.dumps(gone)))
    assert "statusCode 10204" in message


def test_parse_post_rejects_a_post_without_an_id() -> None:
    # Resume goes by ID, so a post without one would get scraped again every run.
    page = _page({"desc": "x", "author": {"uniqueId": "a"}, "contents": []})
    assert "no ID" in _raises(ValueError, parse_post, page, {"111"})


def test_parse_post_rejects_json_of_the_wrong_shape() -> None:
    assert "laid out" in _raises(ValueError, parse_post, REHYDRATION.format(data="[1, 2]"))


def test_is_challenge_page() -> None:
    assert is_challenge_page(CHALLENGE_HTML)
    assert not is_challenge_page(_post_page("1"))


def test_parse_cookie_header() -> None:
    assert parse_cookie_header("sessionid=abc; ttwid=xyz==") == {
        "sessionid": "abc",
        "ttwid": "xyz==",
    }
    assert parse_cookie_header("Cookie: sessionid=abc") == {"sessionid": "abc"}
    assert parse_cookie_header("") == {}


def test_load_cookies_reads_a_netscape_file() -> None:
    netscape = (
        "# Netscape HTTP Cookie File\n"
        ".tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tsecret\n"
        "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t0\tsid_tt\talso-secret\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.txt"
        path.write_text(netscape, encoding="utf-8")
        cookies = load_cookies(str(path))
    assert cookies is not None
    assert {(c.name, c.value, c.domain) for c in cookies.jar} == {
        ("sessionid", "secret", ".tiktok.com"),
        ("sid_tt", "also-secret", ".tiktok.com"),
    }


def test_load_cookies_reads_a_file_holding_a_header() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "header.txt"
        path.write_text("sessionid=abc; ttwid=xyz\n", encoding="utf-8")
        cookies = load_cookies(str(path))
    assert cookies is not None
    assert dict(cookies) == {"sessionid": "abc", "ttwid": "xyz"}


def test_load_cookies_takes_a_3kb_header() -> None:
    header = "sessionid=" + "a" * 3000 + "; ttwid=b"
    cookies = load_cookies(header)
    assert cookies is not None
    assert cookies["sessionid"] == "a" * 3000


def test_load_cookies_rejects_a_path_that_isnt_there() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        message = _raises(InputError, load_cookies, str(Path(tmp) / "cookies.txt"))
    assert "doesn't look like a Cookie header" in message


def test_cookies_only_go_to_tiktok() -> None:
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent[request.url.host] = request.headers.get("cookie")
        return httpx.Response(200)

    async def visit() -> None:
        async with httpx.AsyncClient(
            cookies=load_cookies("sessionid=abc"), transport=httpx.MockTransport(handler)
        ) as client:
            await client.get("https://www.tiktok.com/@i/video/1")
            await client.get("https://example.com/")

    asyncio.run(visit())
    assert sent == {"www.tiktok.com": "sessionid=abc", "example.com": None}


def test_client_only_asks_for_encodings_httpx_can_decode() -> None:
    async def headers() -> tuple[str, str]:
        async with build_client() as ours, httpx.AsyncClient() as plain:
            return ours.headers["accept-encoding"], plain.headers["accept-encoding"]

    ours, plain = asyncio.run(headers())
    assert ours == plain


def test_load_export_reads_the_older_layout() -> None:
    export = {
        "Activity": {
            "Like List": {
                "ItemFavoriteList": [
                    {
                        "Date": "2024-05-02 10:00:00",
                        "Link": "https://www.tiktokv.com/share/video/222/",
                    },
                    {
                        "Date": "2024-05-01 10:00:00",
                        "Link": "https://www.tiktokv.com/share/video/111/",
                    },
                ]
            },
            "Favorite Videos": {
                "FavoriteVideoList": [
                    {
                        "Date": "2024-05-01 09:00:00",
                        "Link": "https://www.tiktokv.com/share/video/111/",
                    },
                    # Favourited after the newest like, which still counts.
                    {
                        "Date": "2024-06-01 09:00:00",
                        "Link": "https://www.tiktokv.com/share/video/222/",
                    },
                ]
            },
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        urls, favorites = load_export(_write_json(tmp, "export.json", export))
    assert urls == ["https://www.tiktok.com/@i/video/222", "https://www.tiktok.com/@i/video/111"]
    assert favorites == {"111", "222"}


def test_load_export_reads_the_newer_layouts() -> None:
    likes = {"ItemFavoriteList": [{"date": "2025-01-02 10:00:00", "link": "https://x/video/333/"}]}
    for section in ("Your Activity", "Likes and Favorites"):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, "export.json", {section: {"Like List": likes}})
            urls, favorites = load_export(path)
        assert urls == ["https://www.tiktok.com/@i/video/333"]
        assert favorites is None


def test_load_export_dedupes_before_the_limit() -> None:
    links = ["https://x/video/3/", "https://x/video/3/", "https://x/@user", "https://x/video/2/"]
    export = {"Activity": {"Like List": {"ItemFavoriteList": [{"Link": link} for link in links]}}}
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_json(tmp, "export.json", export)
        assert load_export(path)[0] == [
            "https://www.tiktok.com/@i/video/3",
            "https://www.tiktok.com/@i/video/2",
        ]
        assert load_export(path, limit=1)[0] == ["https://www.tiktok.com/@i/video/3"]


def test_load_export_explains_what_is_wrong() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "user_data_tiktok.json"
        assert "Couldn't find" in _raises(InputError, load_export, missing)
        not_json = Path(tmp) / "export.txt"
        not_json.write_text("Like List:\n", encoding="utf-8")
        assert "isn't valid JSON" in _raises(InputError, load_export, not_json)
        no_likes = _write_json(tmp, "export.json", {"Profile": {}})
        assert "Like List" in _raises(InputError, load_export, no_likes)


def test_challenge_is_not_retried() -> None:
    client = _FakeClient(status=200, text=CHALLENGE_HTML)
    stats: Counter[str] = Counter()
    result = asyncio.run(fetch_and_parse(client, "http://x/video/1", None, retries=3, stats=stats))
    assert result == {}
    assert client.calls == 1
    assert stats["blocked"] == 1


def test_fetch_and_parse_retries_a_dropped_connection() -> None:
    client = _FakeClient(exc=httpx.ConnectError("down"))
    assert asyncio.run(fetch_and_parse(client, "http://x/video/1", None, retries=2)) == {}
    assert client.calls == 2


def test_fetch_and_parse_retries_a_429() -> None:
    client = _FakeClient(status=429)
    assert asyncio.run(fetch_and_parse(client, "http://x/video/1", None, retries=2)) == {}
    assert client.calls == 2


def test_fetch_and_parse_never_raises() -> None:
    bad = _FakeClient(exc=ValueError("boom"))
    missing = _FakeClient(status=404)
    broken = _FakeClient(status=200, text="<html>no post</html>")

    async def run_batch():
        return await asyncio.gather(
            fetch_and_parse(bad, "http://x/video/1", None, retries=1),
            fetch_and_parse(missing, "http://x/video/2", None, retries=1),
            fetch_and_parse(broken, "http://x/video/3", None, retries=1),
        )

    assert asyncio.run(run_batch()) == [{}, {}, {}]


def test_scrape_appends_to_saved_posts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_post_page(video_id_from_url(str(request.url))))

    async def scrape(out: Path) -> bool:
        async with _mock_client(handler) as client:
            urls = [scraper.POST_URL.format(video_id=n) for n in ("1", "2", "3")]
            return await scrape_posts(
                client, urls, {"2"}, out, base_data=[{"id": "0"}], batch_size=2, batch_delay=0
            )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "post_data.json"
        assert asyncio.run(scrape(out)) is True
        saved = json.loads(out.read_text(encoding="utf-8"))
    assert [post["id"] for post in saved] == ["0", "1", "2", "3"]
    assert [post.get("isFavorite") for post in saved] == [None, False, True, False]


def test_scrape_stops_on_a_challenged_batch() -> None:
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text=CHALLENGE_HTML)

    async def scrape(out: Path) -> bool:
        async with _mock_client(handler) as client:
            urls = [scraper.POST_URL.format(video_id=n) for n in range(1, 11)]
            return await scrape_posts(
                client, urls, None, out, base_data=[{"id": "0"}], batch_size=3, batch_delay=0
            )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "post_data.json"
        assert asyncio.run(scrape(out)) is False
        assert json.loads(out.read_text(encoding="utf-8")) == [{"id": "0"}]
    assert len(requested) == 3


def test_scrape_saves_progress_when_cancelled() -> None:
    # Post 2 lands between checkpoints, so only the save on the way out can keep it.
    async def handler(request: httpx.Request) -> httpx.Response:
        video_id = video_id_from_url(str(request.url))
        if video_id == "3":
            await asyncio.sleep(30)
        return httpx.Response(200, text=_post_page(video_id))

    async def scrape(out: Path) -> None:
        async with _mock_client(handler) as client:
            urls = [scraper.POST_URL.format(video_id=n) for n in ("1", "2", "3")]
            await asyncio.wait_for(
                scrape_posts(client, urls, None, out, batch_size=1, batch_delay=0), timeout=1
            )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "post_data.json"
        _raises(TimeoutError, asyncio.run, scrape(out))
        assert [post["id"] for post in json.loads(out.read_text(encoding="utf-8"))] == ["1", "2"]


def test_run_skips_posts_that_are_already_saved() -> None:
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(video_id_from_url(str(request.url)))
        return httpx.Response(200, text=_post_page(requested[-1]))

    links = [{"Link": f"https://x/video/{n}/"} for n in ("3", "2", "1")]
    real_build_client = scraper.build_client
    scraper.build_client = lambda cookies=None: _mock_client(handler)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            export = _write_json(
                tmp, "export.json", {"Activity": {"Like List": {"ItemFavoriteList": links}}}
            )
            write_output(Path(tmp) / "post_data.json", [{"id": "2"}])
            args = argparse.Namespace(
                input=str(export), output_dir=tmp, limit=None, resume=True, cookies="a=b",
                batch_size=5, batch_delay=0, retries=1,
            )  # fmt: skip
            assert asyncio.run(scraper.run(args)) is True
            saved = json.loads((Path(tmp) / "post_data.json").read_text(encoding="utf-8"))
    finally:
        scraper.build_client = real_build_client
    assert requested == ["3", "1"]
    assert [post["id"] for post in saved] == ["2", "3", "1"]


def test_load_existing_refuses_a_corrupt_file() -> None:
    # Treating it as empty would let the first checkpoint overwrite every saved post.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "post_data.json"
        assert load_existing(out) == []
        out.write_text('[{"id": "1"}, {"id"', encoding="utf-8")
        assert "--no-resume" in _raises(InputError, load_existing, out)


def test_write_output_leaves_no_temp_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sub" / "post_data.json"
        write_output(out, [{"id": "1"}])
        assert json.loads(out.read_text(encoding="utf-8")) == [{"id": "1"}]
        assert not list(out.parent.glob("*.tmp"))


def test_positive_int_rejects_zero_and_below() -> None:
    assert positive_int("5") == 5
    for bad in ("0", "-3"):
        _raises(argparse.ArgumentTypeError, positive_int, bad)


def test_parse_html_cli_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.html"
        good.write_text(_post_page("42"), encoding="utf-8")
        bad = Path(tmp) / "bad.html"
        bad.write_text("<html></html>", encoding="utf-8")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scraper.main(["--parse-html", str(good)])
        assert json.loads(out.getvalue())["id"] == "42"

        try:
            scraper.main(["--parse-html", str(bad)])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("a page with no post in it should exit with 1")


if __name__ == "__main__":
    for _name, _case in sorted(globals().items()):
        if _name.startswith("test_"):
            _case()
            print(f"ok  {_name}")
    print("all passed")
