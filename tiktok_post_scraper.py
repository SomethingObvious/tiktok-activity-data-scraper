"""Scrape post data for the videos in a TikTok data export.

The export lists the videos you liked and favorited, but only as URLs. This
fetches each post page, pulls the embedded post JSON (author, stats, hashtags,
location, ...), and writes it to ``scraper_data/scraper_output/post_data.json``.

Runs are resumable: on a second run it reads what's already saved and skips any
video ID it already has, so a crash or a rate-limit stop only costs the posts
still outstanding. Requests that come back 403/429 (TikTok throttling) or hit a
transient network error are retried with exponential backoff.

TikTok fronts these pages with a WAF bot challenge; an anonymous request gets a
"Please wait..." page with no post data. Pass a logged-in browser session with
``--cookies`` (or the ``TIKTOK_COOKIE`` env var) to get through it.

Examples::

    python tiktok_post_scraper.py --cookies cookies.txt  # scrape the whole Like List
    python tiktok_post_scraper.py --limit 200            # just the 200 most recent
    python tiktok_post_scraper.py --url "https://..."    # one live URL, print result
    python tiktok_post_scraper.py --parse-html page.html # parse a saved page offline
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import datetime
import json
import os
import re
import sys
import time
from collections import Counter
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import jmespath
from httpx import AsyncClient, Response, TransportError
from loguru import logger as log
from parsel import Selector
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tqdm import tqdm

DEFAULT_INPUT = "user_data_tiktok.json"
DEFAULT_OUTPUT_DIR = Path("scraper_data/scraper_output")
# TikTok resolves a post by its numeric ID; the @username segment is cosmetic and
# redirects to the real one, so a placeholder is fine (we build from the ID, not
# the raw export link, which has no username).
POST_URL = "https://www.tiktok.com/@i/video/{video_id}"
DEFAULT_LIMIT = 7999
DEFAULT_BATCH_SIZE = 5
DEFAULT_BATCH_DELAY = 0.1
DEFAULT_RETRIES = 3
# Checkpoint the growing output every N batches so a crash costs at most this
# many batches, without rewriting the whole file on every single batch.
CHECKPOINT_EVERY = 10

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
)
_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": _USER_AGENT,
    "Accept": _ACCEPT,
    "Accept-Encoding": "gzip, deflate, br",
}

_POST_QUERY = """{
    id: id,
    desc: desc,
    createTime: createTime,
    video: video.{duration: duration},
    author: author.{id: id, uniqueId: uniqueId, nickname: nickname, verified: verified},
    stats: stats,
    locationCreated: locationCreated,
    diversificationLabels: diversificationLabels,
    suggestedWords: suggestedWords,
    contents: contents[].{textExtra: textExtra[].{hashtagName: hashtagName}}
    }"""


class RateLimitedError(Exception):
    """Raised on a 403/429 so the retry layer backs off and tries again."""


# Markers unique to TikTok's WAF ("SlardarWAF") bot-challenge page, which comes
# back with HTTP 200 and no post JSON. Without these, a challenge is
# indistinguishable from a markup change and gets misreported as such.
_CHALLENGE_MARKERS = ("_wafchallengeid", "SlardarWAF", "waf-aiso")


def is_challenge_page(html: str) -> bool:
    """True if TikTok served its "Please wait..." bot challenge instead of a post."""
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def _parse_cookie_header(header: str) -> dict[str, str]:
    """Parse a ``k=v; k2=v2`` Cookie header into a dict (values kept verbatim)."""
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        name, sep, value = part.partition("=")
        if sep:
            cookies[name.strip()] = value.strip()
    return cookies


def load_cookies(source: str | None) -> dict[str, str] | MozillaCookieJar | None:
    """Load cookies from ``--cookies``/``TIKTOK_COOKIE`` for an authenticated session.

    ``source`` may be a raw ``Cookie:`` header string, or a path to a file holding
    one, or a path to a Netscape ``cookies.txt`` (what browser extensions export).
    Returns ``None`` when nothing is supplied, so the client runs cookieless.
    """
    source = source or os.environ.get("TIKTOK_COOKIE")
    if not source:
        return None

    path = Path(source)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if text.lstrip().startswith(("# Netscape", "# HTTP Cookie File")):
            jar = MozillaCookieJar(str(path))
            jar.load(ignore_discard=True, ignore_expires=True)
            log.info(f"Loaded {len(jar)} cookies from {path}")
            return jar
        source = text.strip()

    cookies = _parse_cookie_header(source)
    log.info(f"Loaded {len(cookies)} cookies")
    return cookies or None


def build_client(cookies: dict[str, str] | MozillaCookieJar | None = None) -> AsyncClient:
    """Create the shared HTTP/2 client with browser-like headers.

    Follows redirects because TikTok bounces the export's ``share`` links to their
    canonical ``@user/video`` form; without it those posts come back 3xx and fail.
    """
    return AsyncClient(http2=True, headers=_HEADERS, cookies=cookies, follow_redirects=True)


def binary_search(sorted_list: list[str], item: str) -> bool:
    """True if ``item`` is in the pre-sorted list (used to flag favorites)."""
    index = bisect.bisect_left(sorted_list, item)
    return index != len(sorted_list) and sorted_list[index] == item


def video_id_from_url(url: str) -> str:
    """Pull the numeric video ID out of a post URL, or "" if there isn't one."""
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def parse_post(html: str, favorite_video_ids: list[str] | None) -> dict:
    """Extract the post JSON from a post page's HTML.

    Returns an empty dict if the rehydration script or the expected keys are
    missing, which happens when TikTok changes its markup.
    """
    data = Selector(html).xpath("//script[@id='__UNIVERSAL_DATA_FOR_REHYDRATION__']/text()").get()
    if data is None:
        log.error("Failed to find the required script tag in the HTML.")
        return {}

    try:
        video_detail = json.loads(data)["__DEFAULT_SCOPE__"]["webapp.video-detail"]
        post_data = video_detail["itemInfo"]["itemStruct"]
    except (KeyError, json.JSONDecodeError) as exc:
        log.error(f"Failed to parse JSON data: {exc}")
        return {}

    parsed: dict = jmespath.search(_POST_QUERY, post_data)
    if parsed and favorite_video_ids is not None and parsed.get("id"):
        parsed["isFavorite"] = binary_search(favorite_video_ids, parsed["id"])
    return parsed


def load_urls_and_favorites_from_json(
    file_path: str, limit: int
) -> tuple[list[str], list[str] | None]:
    """Read the export and return (liked post URLs, sorted favorite video IDs).

    Favorites are limited to those saved on or before the most recent like, so
    the two lists line up in time. Favorite IDs come back sorted for
    ``binary_search``. Returns ``None`` for favorites when the export has none.
    """
    with Path(file_path).open(encoding="utf-8") as file:
        data = json.load(file)

    liked_posts = data.get("Activity", {}).get("Like List", {}).get("ItemFavoriteList", [])[:limit]

    date_format = "%Y-%m-%d %H:%M:%S"
    last_liked_date = (
        datetime.datetime.strptime(liked_posts[0]["Date"], date_format) if liked_posts else None
    )

    # Build canonical post URLs from the extracted video ID instead of rewriting
    # the export link in place -- the old string surgery broke on any link that
    # wasn't exactly a tiktokv.com/share/... URL.
    urls = []
    skipped = 0
    for item in liked_posts:
        video_id = video_id_from_url(item.get("Link", ""))
        if video_id:
            urls.append(POST_URL.format(video_id=video_id))
        else:
            skipped += 1
    if skipped:
        log.warning(f"{skipped} liked entries had no resolvable /video/<id> link; skipped")

    favorite_video_data = (
        data.get("Activity", {}).get("Favorite Videos", {}).get("FavoriteVideoList")
    )
    if favorite_video_data is None:
        favorite_video_ids = None
    else:
        favorite_video_ids = [
            re.sub(r"\D", "", item["Link"])
            for item in favorite_video_data
            if last_liked_date
            and datetime.datetime.strptime(item["Date"], date_format) <= last_liked_date
        ]
        favorite_video_ids.sort()

    return urls, favorite_video_ids


async def fetch_and_parse(
    client: AsyncClient,
    url: str,
    favorite_video_ids: list[str] | None,
    retries: int,
    stats: Counter[str] | None = None,
) -> dict:
    """Fetch one post URL and parse it, retrying throttling (403/429) and transient
    network errors with backoff.

    Always returns a dict: a URL that keeps failing -- or raises anything
    unexpected -- is logged and skipped so it can't abort the surrounding batch.
    A WAF bot-challenge (HTTP 200, no post JSON) is counted in ``stats`` and given
    up on immediately, since a cookieless retry can't solve a JS challenge.
    """
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(retries),
            wait=wait_exponential_jitter(initial=1, max=30),
            retry=retry_if_exception_type((TransportError, RateLimitedError)),
            reraise=True,
        ):
            with attempt:
                response: Response = await client.get(url)
                if response.status_code == 200:
                    if is_challenge_page(response.text):
                        if stats is not None:
                            stats["blocked"] += 1
                        log.warning(f"Bot-challenge (WAF) for {url}; needs a --cookies session")
                        return {}
                    return parse_post(response.text, favorite_video_ids)
                if response.status_code in (403, 429):
                    log.warning(f"{response.status_code} (throttled) for {url}; backing off")
                    raise RateLimitedError(url)
                log.warning(f"Received status code {response.status_code} for URL: {url}")
                return {}
    except (TransportError, RateLimitedError):
        log.error(f"Failed to scrape URL after {retries} attempts: {url}")
    except Exception as exc:
        # One malformed post must never abort a whole scrape run.
        log.error(f"Unexpected error scraping {url}: {exc}")
    return {}


def _write_output(output_file: Path, data: list[dict]) -> None:
    # Write to a sibling temp file and atomically replace, so a crash mid-write
    # can't corrupt the checkpoint and lose everything scraped so far.
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_file.with_suffix(output_file.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    tmp.replace(output_file)


def load_existing(output_file: Path) -> list[dict]:
    """Return posts already saved from an earlier run (empty list if none)."""
    try:
        with output_file.open(encoding="utf-8") as file:
            existing = json.load(file)
        return existing if isinstance(existing, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


async def scrape_posts(
    client: AsyncClient,
    urls: list[str],
    favorite_video_ids: list[str] | None,
    output_file: Path,
    *,
    base_data: list[dict] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_delay: float = DEFAULT_BATCH_DELAY,
    retries: int = DEFAULT_RETRIES,
) -> list[dict]:
    """Scrape ``urls`` in concurrent batches, checkpointing to ``output_file``.

    Newly scraped posts are appended to ``base_data`` (posts already on disk) so
    the output file always holds the full, resumable set. Returns just the posts
    scraped this run.
    """
    start_time = time.time()
    combined = list(base_data or [])
    new_data: list[dict] = []
    stats: Counter[str] = Counter()
    failed = 0

    with tqdm(total=len(urls), desc="scraping", unit="post") as bar:
        for batch_index, i in enumerate(range(0, len(urls), batch_size)):
            batch = urls[i : i + batch_size]
            results = await asyncio.gather(
                *[fetch_and_parse(client, url, favorite_video_ids, retries, stats) for url in batch]
            )
            got = [post for post in results if post]
            failed += len(batch) - len(got)
            new_data.extend(got)
            combined.extend(got)
            bar.update(len(batch))

            if batch_index % CHECKPOINT_EVERY == 0:
                _write_output(output_file, combined)
            if i + batch_size < len(urls):
                await asyncio.sleep(batch_delay)

    _write_output(output_file, combined)
    blocked = stats["blocked"]
    log.success(
        f"Scraped {len(new_data)} posts ({failed} failed, {blocked} bot-challenged) "
        f"into {output_file}"
    )
    if blocked:
        log.warning(
            f"TikTok served its bot challenge for {blocked} posts. Supply a logged-in "
            "session with --cookies (see the README), and/or lower --batch-size or raise "
            "--batch-delay."
        )
    log.info(f"scrape_posts took {time.time() - start_time:.2f} seconds")
    return new_data


async def run(args: argparse.Namespace) -> None:
    """Load the export, skip already-scraped posts, and scrape the rest."""
    start_time = time.time()
    output_file = Path(args.output_dir) / "post_data.json"

    urls, favorite_video_ids = load_urls_and_favorites_from_json(args.input, args.limit)
    log.info(f"{len(urls)} liked posts in export (limit {args.limit})")

    base_data: list[dict] = []
    if args.resume:
        base_data = load_existing(output_file)
        done = {post.get("id") for post in base_data}
        before = len(urls)
        urls = [url for url in urls if video_id_from_url(url) not in done]
        log.info(f"Resuming: {len(base_data)} already saved, {before - len(urls)} skipped")

    if not urls:
        log.success("Nothing new to scrape.")
        return

    client = build_client(load_cookies(args.cookies))
    try:
        await scrape_posts(
            client,
            urls,
            favorite_video_ids,
            output_file,
            base_data=base_data,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            retries=args.retries,
        )
    finally:
        await client.aclose()

    log.info(f"The entire program took {time.time() - start_time:.2f} seconds")


async def scrape_single(args: argparse.Namespace, url: str) -> None:
    """Scrape one live URL and print the parsed post (no file writes)."""
    client = build_client(load_cookies(args.cookies))
    try:
        post = await fetch_and_parse(client, url, None, args.retries)
    finally:
        await client.aclose()
    print(json.dumps(post, indent=2, ensure_ascii=False))


def parse_local_html(path: str) -> None:
    """Parse a saved post page from disk and print the result. No network."""
    html = Path(path).read_text(encoding="utf-8")
    post = parse_post(html, None)
    print(json.dumps(post, indent=2, ensure_ascii=False))


def _configure_logging(verbose: bool) -> None:
    log.remove()
    log.add(sys.stderr, level="DEBUG" if verbose else "INFO")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=DEFAULT_INPUT, help="TikTok data export JSON")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="where to write post_data.json"
    )
    parser.add_argument(
        "--limit", type=_positive_int, default=DEFAULT_LIMIT, help="max liked posts to scrape"
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_BATCH_SIZE,
        help="posts fetched concurrently",
    )
    parser.add_argument(
        "--batch-delay", type=float, default=DEFAULT_BATCH_DELAY, help="seconds between batches"
    )
    parser.add_argument(
        "--retries",
        type=_positive_int,
        default=DEFAULT_RETRIES,
        help="attempts per URL on 403/timeout",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="re-scrape everything instead of skipping saved posts",
    )
    parser.add_argument(
        "--cookies",
        help="Cookie header string, or a path to a file with one, or a Netscape "
        "cookies.txt; needed to get past TikTok's bot challenge (or set TIKTOK_COOKIE)",
    )
    parser.add_argument("--url", help="scrape a single live URL and print it")
    parser.add_argument(
        "--parse-html", metavar="FILE", help="parse a saved post page offline and print it"
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.verbose)

    if args.parse_html:
        parse_local_html(args.parse_html)
    elif args.url:
        asyncio.run(scrape_single(args, args.url))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
