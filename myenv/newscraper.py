import jmespath
import asyncio
import json
import gzip
import zlib
from typing import List, Dict
from httpx import AsyncClient, Response, ReadTimeout
from parsel import Selector
from loguru import logger as log
import re
import time
import bisect
import datetime

failed_post = 0
max_retries = 3  # Maximum number of retries for each URL

# Initialize an async httpx client
client = AsyncClient(
    http2=True,
    headers={
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    },
)

def parse_post(response: Response, favorite_video_ids: List[str]) -> Dict:
    global failed_post

    response_text = response.text

    selector = Selector(response_text)
    data = selector.xpath("//script[@id='__UNIVERSAL_DATA_FOR_REHYDRATION__']/text()").get()

    if data is None:
        log.error("Failed to find the required script tag in the HTML.")
        return {}

    try:
        post_data = json.loads(data)["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
    except KeyError as e:
        log.error(f"Failed to parse JSON data: {e}")
        failed_post += 1
        log.error(f"Failed post count = " + str(failed_post))
        return {}

    parsed_post_data = jmespath.search(
        """{
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
        }""",
        post_data
    )
    
    if parsed_post_data:
        parsed_post_data['isFavorite'] = binary_search(favorite_video_ids, parsed_post_data['id'])
    
    return parsed_post_data

def binary_search(sorted_list: List[str], item: str) -> bool:
    index = bisect.bisect_left(sorted_list, item)
    if index != len(sorted_list) and sorted_list[index] == item:
        return True
    return False

def load_urls_and_favorites_from_json(file_path: str, limit: int) -> (List[str], List[str]): # type: ignore
    with open(file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)

    # Extract liked posts up to the specified limit
    liked_posts = data['Activity']['Like List']['ItemFavoriteList'][:limit]
    
    # Get the date of the most recent liked post (assuming it's already sorted)
    last_liked_date = datetime.datetime.strptime(liked_posts[0]['Date'], "%Y-%m-%d %H:%M:%S")

    # Extract URLs from liked posts
    urls = [item['Link'] for item in liked_posts]
    urls = [re.sub(r'v(?!i)', '', url).replace('share', '@') for url in urls]
    
    # Extract and filter favorite video IDs by date
    favorite_video_ids = [
        re.sub(r'\D', '', item['Link'])
        for item in data['Activity']['Favorite Videos']['FavoriteVideoList']
        if datetime.datetime.strptime(item['Date'], "%Y-%m-%d %H:%M:%S") <= last_liked_date
    ]
    
    favorite_video_ids.sort()
    return urls, favorite_video_ids

async def fetch_and_parse(url: str, favorite_video_ids: List[str]) -> Dict:
    retries = 0
    while retries < max_retries:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                post_data = parse_post(response, favorite_video_ids)
                if post_data:
                    return post_data
                else:
                    log.error(f"Failed to parse JSON data for URL: {url}")
                    return {}
            elif response.status_code == 403:
                log.warning(f"Received status code 403 for URL: {url}. Waiting for 2 seconds before retrying.")
                await asyncio.sleep(5)  # Wait for 2 seconds before retrying
                retries += 1
            else:
                log.warning(f"Received status code {response.status_code} for URL: {url}")
                return {}
        except ReadTimeout:
            log.warning(f"ReadTimeout for URL: {url}")
            retries += 1
            await asyncio.sleep(1)  # Wait for 1 second before retrying
    log.error(f"Failed to scrape URL after {max_retries} attempts: {url}")
    return {}

async def scrape_posts(urls: List[str], favorite_video_ids: List[str], batch_size: int = 5, batch_delay: float = 0.1) -> List[Dict]:
    start_time = time.time()
    data = []

    async def process_url(url: str):
        post_data = await fetch_and_parse(url, favorite_video_ids)
        if post_data:
            return post_data
        return None

    # Process URLs in batches
    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i:i + batch_size]
        
        # Process each batch concurrently
        results = await asyncio.gather(*[process_url(url) for url in batch_urls])
        
        # Filter out None results and append to data
        data.extend(result for result in results if result)

        # Add a delay between batches
        if i + batch_size < len(urls):
            await asyncio.sleep(batch_delay)

        try:
            with open("post_data.json", "r", encoding="utf-8") as file:
                existing_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            existing_data = []

        log.success(f"Scraped {len(data)} posts from post pages")
    
    existing_data.extend(data)
    with open("post_data.json", "w", encoding="utf-8") as file:
        json.dump(existing_data, file, indent=2, ensure_ascii=False)

    end_time = time.time()
    log.success(f"Scraped {len(data)} posts from post pages")
    log.info(f"scrape_posts took {end_time - start_time:.2f} seconds")
    log.info(f"Total Failed Scrapes : {failed_post}")
    return data



async def run():
    start_time = time.time()

    urls, favorite_video_ids = load_urls_and_favorites_from_json("user_data_tiktok.json", 7999)

    post_data = await scrape_posts(urls, favorite_video_ids)
    
    with open("post_data.json", "w", encoding="utf-8") as file:
        json.dump(post_data, file, indent=2, ensure_ascii=False)

    end_time = time.time()
    log.info(f"The entire program took {end_time - start_time:.2f} seconds")

async def test_single_url(url: str):
    favorite_video_ids = ['7302518024957955334']
    post_data = await scrape_posts([url], favorite_video_ids)
    print(json.dumps(post_data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        asyncio.run(test_single_url(url))
    else:
        asyncio.run(run())
