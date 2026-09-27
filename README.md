# TikTok Activity Data Scraper

This takes the data export you can request from TikTok, looks up every video you liked, and turns what it finds into one HTML page of the creators, hashtags and topics you watch the most. Hashtags get matched to WordNet meanings, so #cat, #cats and #catsoftiktok all count toward the same topic.

## Setup

It needs Python 3.11 or newer.

```bash
git clone https://github.com/SomethingObvious/tiktok-activity-data-scraper.git
cd tiktok-activity-data-scraper
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Request your data in the app under Settings and privacy, Account, Download your data, and pick JSON (the TXT export won't work). Once it arrives, put user_data_tiktok.json in the repo root.

TikTok puts a bot challenge in front of every post page, so you'll also need cookies from a browser where you're logged in. In the developer tools' Network tab, click any TikTok request and copy its Cookie header into a file called cookies.txt, which git already ignores. A file from a "Get cookies.txt" extension works too, and so does the TIKTOK_COOKIE environment variable.

## Running It

```bash
python pipeline.py --cookies cookies.txt       # scrape, count, group and report
python pipeline.py --cookies cookies.txt --limit 500 --open
python pipeline.py --skip-scrape               # redo everything after the scrape
```

The report ends up at processed_data/activity_report.html, and each step is its own script with a --help if you only want to run one again.

The scrape fetches 5 posts at a time and saves as it goes, so if it stops partway (or you press Ctrl+C) the next run picks up where it left off. It also stops by itself once TikTok answers a whole batch with the bot challenge, which usually means the cookies have expired.

Slang and names that WordNet doesn't know go in post_processing/custom_synsets.json, and `python post_processing/synset_updater.py rizz` adds one.

## What It Won't Do

It won't log in for you, get past the bot challenge without your cookies, or download any videos. TikTok changes its page markup now and then, and the posts come back empty with a warning when it does. Running `python tiktok_post_scraper.py --parse-html page.html` on a saved post page is the quickest way to see what broke. Topics go by one word per hashtag and its most common WordNet sense, so misspellings and other languages mostly stay ungrouped.

## Tests

None of the tests touch the network.

```bash
python -m nltk.downloader wordnet
for test in test_*.py; do python "$test"; done
```
