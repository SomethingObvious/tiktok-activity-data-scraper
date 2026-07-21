# TikTok Activity Data Scraper

Pull the posts you've liked/favorited on TikTok (from your own data export), scrape
the current post data for each one, and cluster the hashtags by WordNet meaning so
you can see what you actually watch.

## How it fits together

1. `tiktok_post_scraper.py` reads your TikTok data export, hits each liked/favorited
   post's page, and pulls out the post JSON (author, stats, hashtags, etc.).
2. `post_processing/post_data_collection.py` tallies that raw data into frequency
   counts (hashtags, authors, locations, ...).
3. `post_processing/data_processor.py` takes the hashtag counts, filters out noise
   ("fyp", "viral", ...), looks up a WordNet synset for each hashtag, and merges
   hashtags that share a synset so `#cats` and `#kitten` end up in the same bucket.
4. `post_processing/synset_updater.py` and `post_processing/wordnet_search.py` are
   small helper scripts for maintaining `post_processing/custom_synsets.json`, which
   covers slang and names WordNet doesn't know about.

All four steps run in that order and each one reads the previous step's output, so
run them in sequence from the repo root (paths below assume that).

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/SomethingObvious/tiktok-activity-data-scraper.git
cd tiktok-activity-data-scraper
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r requirements.txt
python -c "import nltk; nltk.download('wordnet')"
```

The last line only needs to run once — it downloads the WordNet corpus into your
NLTK data directory. `synset_updater.py` and `wordnet_search.py` also call
`nltk.download('wordnet')` on import, so it's safe to skip and let them handle it,
but doing it up front avoids a surprise download mid-run.

You'll also need your own TikTok data export as `user_data_tiktok.json` in the
repo root. Request it from TikTok's account settings (Privacy > Download your
data, JSON format) — it can take a day or two to arrive.

## Usage

Run the steps in order from the repo root. Every script takes `--help`.

### 1. Scrape

```bash
python tiktok_post_scraper.py               # scrape the whole Like List, resuming if interrupted
python tiktok_post_scraper.py --limit 200   # only the 200 most recent likes
python tiktok_post_scraper.py --no-resume   # ignore what's saved and re-scrape everything
```

Other flags: `--input` (export path), `--output-dir`, `--batch-size` and
`--batch-delay` (throttling), `--retries`, `--verbose`. A progress bar shows how
far along the run is.

Runs are resumable. The output file is checkpointed every few batches, and on the
next run the scraper skips any video ID it already saved, so a crash or a
rate-limit stop only costs the posts still outstanding. Pass `--no-resume` to
start clean.

Two ways to check the parser without scraping the whole list:

```bash
python tiktok_post_scraper.py --url "https://www.tiktok.com/@user/video/123"  # one live URL
python tiktok_post_scraper.py --parse-html saved_page.html                    # no network at all
```

`--parse-html` reads a post page you've already saved to disk and prints the
parsed JSON — handy for debugging after TikTok changes its markup.

### 2. Tally the raw scrape into frequency counts

```bash
python post_processing/post_data_collection.py
python post_processing/post_data_collection.py --input path/to/post_data.json
```

### 3. Filter, WordNet-tag, and merge the hashtags

```bash
python post_processing/data_processor.py
python post_processing/data_processor.py --min-percentage 0.25 --verbose
```

`--min-percentage` is the frequency cutoff (default 0.15% of posts). `--verbose`
logs every synset match and merge.

### 4. (optional) Maintain the custom synset list

```bash
python post_processing/synset_updater.py situationship rizz  # add words, then tidy the file
python post_processing/synset_updater.py                     # just run the tidy passes
python post_processing/wordnet_search.py bagel               # does WordNet already know a word?
```

Output lands in `scraper_data/` (raw scrape + frequency counts) and
`processed_data/` (filtered/merged hashtags, JSON and plain text). Both are
gitignored since they're your personal data, not source.

### Post data shape

Each scraped post looks like this:

```json
{
  "id": "7400543367504858373",
  "desc": "Cream Cheese Stuffed Everything Bagel",
  "createTime": "1723073280",
  "video": { "duration": 50 },
  "author": {
    "id": "106392206474711040",
    "uniqueId": "genericauthor",
    "nickname": "Alice Bob",
    "verified": true
  },
  "stats": {
    "diggCount": 6917,
    "shareCount": 1127,
    "commentCount": 72,
    "playCount": 87200,
    "collectCount": "700"
  },
  "locationCreated": "US",
  "diversificationLabels": ["Cooking", "Food & Drink", "Lifestyle"],
  "suggestedWords": ["cream cheese", "Cream Cheese Bagel", "bagel"],
  "contents": [
    { "textExtra": [{ "hashtagName": "pedalboards" }, { "hashtagName": "guitarpedals" }] }
  ],
  "isFavorite": false
}
```

## Rate limits

The scraper fetches posts in batches of 5 with a short delay between batches.
TikTok returns 403/429s if you push much harder than that. A throttling response
or a transient network error is retried with exponential backoff (`--retries`,
default 3 attempts) before the post is given up on; a post that keeps failing is
logged and skipped rather than aborting the run. If a large Like List throws a
lot of 403s, lower `--batch-size` or raise `--batch-delay` — there's no way
around TikTok's own throttling, only ways to stay under it.

## Limitations

- TikTok's page markup and internal JSON change without notice. When they do,
  `parse_post()` returns empty and logs an error; use `--parse-html` on a saved
  page to see what broke.
- Synset matching finds the longest real word inside each hashtag and looks it up
  in WordNet (cached, and a lemmatizer bridges inflected forms to the custom
  list). It beats nothing for run-together hashtags, but it won't handle
  misspellings or multi-word phrases, and it tags on one word per hashtag.
- `custom_synsets.json` is hand-curated. Slang, names, and non-English hashtags
  won't get a synset unless someone's added them (see step 4).

## Tests

The pure logic has offline self-tests — no network, no live TikTok:

```bash
python -c "import nltk; nltk.download('wordnet')"   # once, for the processor tests
python test_scraper.py
python test_data_processor.py
```

They cover URL/ID parsing, the post parser, hashtag filtering, WordNet matching,
and the merge step. Live scraping isn't covered; exercise the parser with
`--parse-html` instead.

## Contributing

Issues and pull requests are welcome. Fork, branch, commit, push, open a PR —
the usual.

## Contact

Questions or feedback: open an issue on this repo.
