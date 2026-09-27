"""Scrape the post data behind every video you liked on TikTok.

Your data export only lists liked videos as links, so this fetches each post page
and pulls out the JSON that TikTok embeds in it. Everything goes into
scraper_data/scraper_output/post_data.json, and a second run skips the posts that
are already saved there.

    python tiktok_post_scraper.py --cookies cookies.txt
    python tiktok_post_scraper.py --cookies cookies.txt --limit 200
    python tiktok_post_scraper.py --url "https://www.tiktok.com/@user/video/123"
    python tiktok_post_scraper.py --parse-html saved_page.html
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Container
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path

import httpx
import jmespath
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
# TikTok finds a post by its ID alone and redirects to the real @username.
POST_URL = "https://www.tiktok.com/@i/video/{video_id}"
DEFAULT_BATCH_SIZE = 5
DEFAULT_BATCH_DELAY = 0.1
DEFAULT_RETRIES = 3
# Rewriting the whole file after every batch gets slow once it holds a few thousand posts.
CHECKPOINT_EVERY = 10
RETRY_WAIT = wait_exponential_jitter(initial=1, max=30)

# A browser version from years ago is probably one more reason for the WAF to
# challenge a request, so this should stay somewhere near current Chrome.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

POST_QUERY = """{
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

# Markers from TikTok's "Please wait..." WAF page. It comes back as a 200 with no
# post in it, which would otherwise look just like a markup change.
CHALLENGE_MARKERS = ("_wafchallengeid", "SlardarWAF", "waf-aiso")


class InputError(Exception):
    """Something wrong with the export or cookies the user passed in, worded for them."""


class RateLimitedError(Exception):
    """TikTok answered 403 or 429, which is worth backing off and trying again."""


def is_challenge_page(html: str) -> bool:
    return any(marker in html for marker in CHALLENGE_MARKERS)


def video_id_from_url(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def parse_cookie_header(header: str) -> dict[str, str]:
    """Split a ``name=value; name2=value2`` Cookie header, with or without ``Cookie:`` in front."""
    header = re.sub(r"^\s*cookie:\s*", "", header, flags=re.IGNORECASE)
    cookies = {}
    for part in header.split(";"):
        name, sep, value = part.partition("=")
        if sep and name.strip():
            cookies[name.strip()] = value.strip()
    return cookies


def load_cookies(source: str | None) -> httpx.Cookies | None:
    """Load a Cookie header, a file holding one, or a Netscape cookies.txt."""
    where = "--cookies" if source else "TIKTOK_COOKIE"
    source = source or os.environ.get("TIKTOK_COOKIE")
    if not source:
        return None

    # Path.exists raises "File name too long" for a real 3 KB header on Linux with
    # Python 3.12, where os.path.isfile just says no.
    if os.path.isfile(source):  # noqa: PTH113
        text = Path(source).read_text(encoding="utf-8")
        if text.lstrip().startswith(("# Netscape", "# HTTP Cookie File")):
            jar = MozillaCookieJar(source)
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except LoadError as exc:
                raise InputError(f"Couldn't read the cookies in {source}. {exc}") from None
            log.info(f"Loaded {len(jar)} cookies from {source}")
            return httpx.Cookies(jar)
        header = text
    else:
        header = source

    cookies = httpx.Cookies()
    for name, value in parse_cookie_header(header).items():
        # Scoped to TikTok so a redirect to some other site can't take the session with it.
        cookies.set(name, value, domain=".tiktok.com")
    if not cookies:
        # Not echoed back, since it could be half a session token.
        raise InputError(
            f"What's in {where} isn't a file and doesn't look like a Cookie header either. "
            "Pass the header itself, a file with it in, or a cookies.txt."
        )
    log.info(f"Loaded {len(cookies.jar)} cookies")
    return cookies


def build_client(cookies: httpx.Cookies | None = None) -> httpx.AsyncClient:
    # httpx fills in Accept-Encoding with only what it can decode. Asking for br
    # without the brotli package gets back bytes that parse as an empty page.
    return httpx.AsyncClient(http2=True, headers=HEADERS, cookies=cookies, follow_redirects=True)


def load_export(path: Path, limit: int | None = None) -> tuple[list[str], set[str] | None]:
    """Return the liked post URLs, newest first, and the IDs of favourited videos.

    Favourites come back as None when the export has no Favorite Videos list at all.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError(
            f"Couldn't find {path}. Put your TikTok data export there or pass --input."
        ) from None
    except json.JSONDecodeError as exc:
        raise InputError(f"Couldn't read {path}. It isn't valid JSON ({exc}).") from None

    # The export has kept these lists under three different top-level names so far,
    # and the newer ones spell the keys in lower case.
    activity: dict = {}
    if isinstance(data, dict):
        activity = (
            data.get("Likes and Favorites")
            or data.get("Your Activity")
            or data.get("Activity")
            or {}
        )
    if "Like List" not in activity:
        raise InputError(
            f"Couldn't find a Like List in {path}. Make sure it's the JSON export, not the TXT one."
        )

    likes = (activity["Like List"] or {}).get("ItemFavoriteList") or []
    ids = [video_id_from_url(item.get("Link") or item.get("link") or "") for item in likes]
    if missing := ids.count(""):
        log.warning(f"Skipped {missing} liked entries that have no video ID in the link")
    # Liking, unliking and liking again leaves the same video in the list twice.
    unique = [video_id for video_id in dict.fromkeys(ids) if video_id][:limit]
    urls = [POST_URL.format(video_id=video_id) for video_id in unique]

    favorites = None
    if "Favorite Videos" in activity:
        saved = (activity["Favorite Videos"] or {}).get("FavoriteVideoList") or []
        favorites = {
            video_id_from_url(item.get("Link") or item.get("link") or "") for item in saved
        }
        favorites.discard("")
    return urls, favorites


def parse_post(html: str, favorites: Container[str] | None = None) -> dict:
    """Pull the post JSON out of a post page. Raises ValueError saying why when it can't."""
    data = Selector(html).xpath("//script[@id='__UNIVERSAL_DATA_FOR_REHYDRATION__']/text()").get()
    if data is None:
        raise ValueError("The page has no __UNIVERSAL_DATA_FOR_REHYDRATION__ script")

    try:
        detail = json.loads(data)["__DEFAULT_SCOPE__"]["webapp.video-detail"]
        item = (detail.get("itemInfo") or {}).get("itemStruct")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"The page's JSON isn't laid out the way it used to be ({exc!r})"
        ) from None
    if not isinstance(item, dict):
        # Deleted and private posts still load, just with a status where the post would be.
        raise ValueError(f"The page has no post in it (statusCode {detail.get('statusCode')})")

    post: dict = jmespath.search(POST_QUERY, item)
    if not post.get("id"):
        raise ValueError("The post has no ID, so it can't be saved or skipped next time")
    if favorites is not None:
        post["isFavorite"] = post["id"] in favorites
    return post


async def fetch_and_parse(
    client: httpx.AsyncClient,
    url: str,
    favorites: Container[str] | None,
    retries: int,
    stats: Counter[str] | None = None,
) -> dict:
    """Fetch and parse one post, or log why not and return {}. It never raises."""
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(retries),
            wait=RETRY_WAIT,
            retry=retry_if_exception_type((httpx.TransportError, RateLimitedError)),
            reraise=True,
        ):
            with attempt:
                response = await client.get(url)
                if response.status_code in (403, 429):
                    raise RateLimitedError(f"HTTP {response.status_code}")
    except (httpx.TransportError, RateLimitedError) as exc:
        log.warning(f"Gave up on {url} after {retries} tries ({exc})")
        return {}
    except Exception as exc:
        # One odd post shouldn't end a run that's thousands of posts long.
        log.error(f"Couldn't fetch {url} ({exc!r})")
        return {}

    if response.status_code != 200:
        log.warning(f"TikTok answered {response.status_code} for {url}")
        return {}
    if is_challenge_page(response.text):
        # Retrying won't help, as the challenge wants a browser to run its JavaScript.
        if stats is not None:
            stats["blocked"] += 1
        log.debug(f"Bot challenge for {url}")
        return {}
    try:
        return parse_post(response.text, favorites)
    except ValueError as exc:
        log.warning(f"{exc}: {url}")
        return {}


def write_output(output_file: Path, posts: list[dict]) -> None:
    # A crash halfway through json.dump would otherwise wipe out every saved post.
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_file.with_suffix(output_file.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(posts, file, indent=2, ensure_ascii=False)
    tmp.replace(output_file)


def load_existing(output_file: Path) -> list[dict]:
    """Return the posts saved by an earlier run, or [] if there aren't any."""
    try:
        existing = json.loads(output_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise InputError(
            f"Couldn't read the saved posts in {output_file} ({exc}). "
            "Move it somewhere else, or pass --no-resume to start over."
        ) from None
    return existing if isinstance(existing, list) else []


async def scrape_posts(
    client: httpx.AsyncClient,
    urls: list[str],
    favorites: Container[str] | None,
    output_file: Path,
    *,
    base_data: list[dict] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_delay: float = DEFAULT_BATCH_DELAY,
    retries: int = DEFAULT_RETRIES,
) -> bool:
    """Scrape urls in batches and save them after base_data in output_file.

    Returns False if it stopped early because TikTok challenged a whole batch.
    """
    posts = list(base_data or [])
    stats: Counter[str] = Counter()
    scraped = failed = 0
    finished = False

    try:
        with tqdm(total=len(urls), desc="Scraping", unit="post") as bar:
            for batch_index, start in enumerate(range(0, len(urls), batch_size)):
                batch = urls[start : start + batch_size]
                blocked_before = stats["blocked"]
                results = await asyncio.gather(
                    *(fetch_and_parse(client, url, favorites, retries, stats) for url in batch)
                )
                got = [post for post in results if post]
                posts.extend(got)
                scraped += len(got)
                failed += len(batch) - len(got)
                bar.update(len(batch))

                # A whole batch of challenges means the session is dead or TikTok
                # wants a break, and the rest of the list would go the same way.
                if stats["blocked"] - blocked_before == len(batch):
                    break
                if batch_index % CHECKPOINT_EVERY == 0:
                    write_output(output_file, posts)
                if start + batch_size < len(urls):
                    await asyncio.sleep(batch_delay)
            else:
                finished = True
    finally:
        # This runs on Ctrl+C as well, so an interrupted run keeps what it got.
        write_output(output_file, posts)

    log.info(
        f"Scraped {scraped} posts into {output_file} "
        f"({failed} failed, and {stats['blocked']} of those hit the bot challenge)"
    )
    if not finished:
        log.error(
            "TikTok answered a whole batch with its bot challenge, so the run stopped there. "
            "Your cookies are probably missing or expired. Grab fresh ones (see the README) "
            "and run it again, and it'll pick up where it left off."
        )
    elif stats["blocked"]:
        log.warning(
            f"{stats['blocked']} posts hit the bot challenge. Running it again later picks them "
            "up, and a lower --batch-size or higher --batch-delay might help."
        )
    return finished


async def run(args: argparse.Namespace) -> bool:
    """Scrape every liked post that isn't saved yet. Returns False if TikTok blocked the run."""
    output_file = Path(args.output_dir) / "post_data.json"
    urls, favorites = load_export(Path(args.input), args.limit)
    log.info(f"Found {len(urls)} liked posts in {args.input}")

    base_data: list[dict] = []
    if args.resume:
        base_data = load_existing(output_file)
        saved = {post.get("id") for post in base_data}
        urls = [url for url in urls if video_id_from_url(url) not in saved]
        log.info(f"{len(base_data)} posts are already saved, so {len(urls)} are left to scrape")

    if not urls:
        log.info("Nothing new to scrape")
        return True

    started = time.perf_counter()
    async with build_client(load_cookies(args.cookies)) as client:
        finished = await scrape_posts(
            client,
            urls,
            favorites,
            output_file,
            base_data=base_data,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            retries=args.retries,
        )
    log.info(f"Took {time.perf_counter() - started:.0f} seconds")
    return finished


async def scrape_single(url: str, cookies: str | None, retries: int) -> dict:
    async with build_client(load_cookies(cookies)) as client:
        return await fetch_and_parse(client, url, None, retries)


def configure_logging(verbose: bool) -> None:
    log.remove()
    # Going through tqdm.write keeps log lines from tearing up the progress bar.
    log.add(
        lambda message: tqdm.write(message, file=sys.stderr, end=""),
        level="DEBUG" if verbose else "INFO",
    )


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"needs to be 1 or more, got {value!r}")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=DEFAULT_INPUT, help="your TikTok data export (JSON)")
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="where post_data.json goes"
    )
    parser.add_argument(
        "--limit", type=positive_int, help="only scrape this many of your most recent likes"
    )
    parser.add_argument(
        "--batch-size",
        type=positive_int,
        default=DEFAULT_BATCH_SIZE,
        help="how many posts to fetch at once (default %(default)s)",
    )
    parser.add_argument(
        "--batch-delay",
        type=float,
        default=DEFAULT_BATCH_DELAY,
        help="seconds to wait between batches (default %(default)s)",
    )
    parser.add_argument(
        "--retries",
        type=positive_int,
        default=DEFAULT_RETRIES,
        help="tries per post when TikTok throttles or the network drops (default %(default)s)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="scrape everything again instead of skipping saved posts",
    )
    parser.add_argument(
        "--cookies",
        help="a Cookie header, a file with one in it, or a Netscape cookies.txt. "
        "TikTok serves a bot challenge without it. TIKTOK_COOKIE works too",
    )
    one = parser.add_mutually_exclusive_group()
    one.add_argument("--url", help="scrape one post and print it, without saving anything")
    one.add_argument("--parse-html", metavar="FILE", help="parse a saved post page and print it")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        if args.parse_html:
            post = parse_post(Path(args.parse_html).read_text(encoding="utf-8"))
        elif args.url:
            post = asyncio.run(scrape_single(args.url, args.cookies, args.retries))
        else:
            sys.exit(0 if asyncio.run(run(args)) else 1)
    except (InputError, ValueError, OSError) as exc:
        log.error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        # scrape_posts has already saved what it got by the time this lands here.
        sys.exit(130)

    if not post:
        sys.exit(1)
    print(json.dumps(post, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
