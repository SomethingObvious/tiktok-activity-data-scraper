"""Scrape the post data behind every video you liked on TikTok.

Your data export only lists liked videos as links, so this fetches each post page
and pulls out the JSON that TikTok embeds in it. Everything goes into
scraper_data/scraper_output/post_data.json, with the deleted and private posts in
unavailable.json next to it, and a second run skips the posts in either.

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
from collections import Counter, deque
from collections.abc import Container, Mapping
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
UNAVAILABLE_NAME = "unavailable.json"
# TikTok finds a post by its ID alone and redirects to the real @username.
POST_URL = "https://www.tiktok.com/@i/video/{video_id}"
# Measured in November 2026 with cookies: one post a second in a row went through
# 100 times without a challenge, two at once got about 130 posts in before a block,
# and 5 at once got blocked after about 20.
DEFAULT_BATCH_SIZE = 1
DEFAULT_BATCH_DELAY = 1.0
# The blocks lifted by themselves after 35 to 100 seconds, and got longer each time.
COOLDOWN = 60
MAX_COOLDOWN = 480
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

# TikTok sends some counts as strings, so every number goes through to_number.
# statsV2 has the repost count, and older pages only have stats.
POST_QUERY = """{
    id: id,
    desc: desc,
    createTime: to_number(createTime),
    video: video.{duration: duration},
    author: {
        id: author.id, uniqueId: author.uniqueId, nickname: author.nickname,
        verified: author.verified,
        followerCount: to_number((authorStatsV2 || authorStats).followerCount)
    },
    music: music.{id: id, title: title, authorName: authorName, original: original},
    stats: (statsV2 || stats).{
        diggCount: to_number(diggCount), shareCount: to_number(shareCount),
        commentCount: to_number(commentCount), playCount: to_number(playCount),
        collectCount: to_number(collectCount), repostCount: to_number(repostCount)
    },
    textLanguage: textLanguage,
    isAd: isAd,
    isAigc: IsAigc,
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


class UnavailableError(ValueError):
    """The page loaded but has a status code where the post would be, as when it's deleted."""

    def __init__(self, status: object) -> None:
        super().__init__(f"The page has no post in it (statusCode {status})")
        self.status = status


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


def load_export(path: Path, limit: int | None = None) -> tuple[dict[str, str], set[str] | None]:
    """Return when each video was liked, keyed by video ID and newest first, and the
    IDs of favourited videos.

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

    items = (activity["Like List"] or {}).get("ItemFavoriteList") or []
    likes: dict[str, str] = {}
    missing = 0
    for item in items:
        video_id = video_id_from_url(item.get("Link") or item.get("link") or "")
        if not video_id:
            missing += 1
        # Liking, unliking and liking again leaves the same video in the list twice,
        # and the first one is the newest.
        elif video_id not in likes and len(likes) != limit:
            likes[video_id] = item.get("Date") or item.get("date") or ""
    if missing:
        log.warning(f"Skipped {missing} liked entries that have no video ID in the link")

    favorites = None
    if "Favorite Videos" in activity:
        saved = (activity["Favorite Videos"] or {}).get("FavoriteVideoList") or []
        favorites = {
            video_id_from_url(item.get("Link") or item.get("link") or "") for item in saved
        }
        favorites.discard("")
    return likes, favorites


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
        raise UnavailableError(detail.get("statusCode"))

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
) -> dict | None:
    """Fetch and parse one post, or log why not and return {}. It never raises.

    Returns None for the bot challenge, which is worth trying again after a break.
    """
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
        log.debug(f"Bot challenge for {url}")
        return None
    try:
        return parse_post(response.text, favorites)
    except UnavailableError as exc:
        log.debug(f"{exc}: {url}")
        return {"id": video_id_from_url(url), "statusCode": exc.status}
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
    unavailable: list[dict] | None = None,
    liked_at: Mapping[str, str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_delay: float = DEFAULT_BATCH_DELAY,
    retries: int = DEFAULT_RETRIES,
) -> bool:
    """Scrape urls in batches and save them after base_data in output_file.

    Deleted and private posts go after unavailable in unavailable.json next to it.
    Returns False if it stopped early because TikTok kept challenging every request
    through the longest cooldown.
    """
    posts = list(base_data or [])
    gone = list(unavailable or [])
    gone_file = output_file.with_name(UNAVAILABLE_NAME)
    queue = deque(urls)
    stats: Counter[str] = Counter()
    cooldown = COOLDOWN
    finished = False

    def save() -> None:
        write_output(output_file, posts)
        write_output(gone_file, gone)

    try:
        with tqdm(total=len(urls), desc="Scraping", unit="post") as bar:
            while queue:
                batch = [queue.popleft() for _ in range(min(batch_size, len(queue)))]
                results = await asyncio.gather(
                    *(fetch_and_parse(client, url, favorites, retries) for url in batch)
                )
                challenged = [
                    url for url, result in zip(batch, results, strict=True) if result is None
                ]
                for result in results:
                    if result is None:
                        continue
                    if result and liked_at is not None:
                        result["likedAt"] = liked_at.get(result["id"])
                    if "statusCode" in result:
                        gone.append(result)
                        stats["unavailable"] += 1
                    elif result:
                        posts.append(result)
                        stats["scraped"] += 1
                    else:
                        stats["failed"] += 1
                bar.update(len(batch) - len(challenged))
                # Challenged posts go back to the front, to try again after the break.
                queue.extendleft(reversed(challenged))
                stats["challenged"] += len(challenged)

                if len(challenged) == len(batch):
                    if cooldown > MAX_COOLDOWN:
                        break
                    save()
                    log.warning(f"TikTok wants a break, so this waits {cooldown} seconds")
                    await asyncio.sleep(cooldown)
                    cooldown *= 2
                    continue
                cooldown = COOLDOWN
                stats["batches"] += 1
                if stats["batches"] % CHECKPOINT_EVERY == 0:
                    save()
                if queue:
                    await asyncio.sleep(batch_delay)
            else:
                finished = True
    finally:
        # This runs on Ctrl+C as well, so an interrupted run keeps what it got.
        save()

    log.info(
        f"Scraped {stats['scraped']} posts into {output_file}. {stats['unavailable']} were "
        f"deleted or private, {stats['failed']} failed, and TikTok challenged "
        f"{stats['challenged']} requests along the way"
    )
    if not finished:
        log.error(
            f"TikTok kept answering with its bot challenge for {MAX_COOLDOWN * 2 - COOLDOWN} "
            "seconds, so the run stopped. Your cookies are probably missing or expired. Grab "
            "fresh ones (see the README) and run it again, and it'll pick up where it left off."
        )
    return finished


async def run(args: argparse.Namespace) -> bool:
    """Scrape every liked post that isn't saved yet. Returns False if TikTok blocked the run."""
    output_file = Path(args.output_dir) / "post_data.json"
    likes, favorites = load_export(Path(args.input), args.limit)
    log.info(f"Found {len(likes)} liked posts in {args.input}")

    base_data: list[dict] = []
    unavailable: list[dict] = []
    if args.resume:
        base_data = load_existing(output_file)
        unavailable = load_existing(output_file.with_name(UNAVAILABLE_NAME))
        for post in base_data:
            # Posts saved by versions that didn't keep the date get it here.
            if not post.get("likedAt") and post.get("id") in likes:
                post["likedAt"] = likes[post["id"]]
        done = {post.get("id") for post in base_data + unavailable}
        likes = {video_id: date for video_id, date in likes.items() if video_id not in done}
        log.info(
            f"{len(base_data)} posts are already saved and {len(unavailable)} are deleted or "
            f"private, so {len(likes)} are left to scrape"
        )

    if not likes:
        if base_data:
            write_output(output_file, base_data)
        log.info("Nothing new to scrape")
        return True

    started = time.perf_counter()
    async with build_client(load_cookies(args.cookies)) as client:
        finished = await scrape_posts(
            client,
            [POST_URL.format(video_id=video_id) for video_id in likes],
            favorites,
            output_file,
            base_data=base_data,
            unavailable=unavailable,
            liked_at=likes,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            retries=args.retries,
        )
    log.info(f"Took {time.perf_counter() - started:.0f} seconds")
    return finished


async def scrape_single(url: str, cookies: str | None, retries: int) -> dict | None:
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
            post: dict | None = parse_post(Path(args.parse_html).read_text(encoding="utf-8"))
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
    # Windows pipes default to cp1252, which can't print the emoji most captions have.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    main()
