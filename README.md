# TikTok Activity Data Scraper

This takes the data export you can request from TikTok, looks up every video you liked, and turns what it finds into one HTML page of the creators, hashtags and topics you watch the most. Hashtags get grouped into about 600 topics, so #gymtok, #workout and #fitness all count toward Fitness, and many also get a specific detail, like Golden Retriever under Dogs.

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
python pipeline.py --cookies cookies.txt       # scrape, count and report
python pipeline.py --cookies cookies.txt --limit 500 --open
python pipeline.py --skip-scrape               # redo everything after the scrape
```

The report ends up at processed_data/activity_report.html, and each step is its own script with a --help if you only want to run one again.

For your own analysis, scraper_data/scraper_output/post_data.json has every liked post with the date you liked it, and unavailable.json next to it lists the deleted and private ones, which reruns skip. The count step also writes scraper_data/post_processing/posts.csv with one row per post and its topics and details, for Excel or pandas (createTime there is UTC).

The scrape goes about one post every 2 seconds, which is as fast as TikTok lets it go for long without the bot challenge, so 5,000 likes take around three hours. It saves as it goes, and if it stops partway (or you press Ctrl+C) the next run picks up where it left off. When the challenge does show up, it waits a minute and carries on, waiting longer each time it comes back, and it only gives up after about 15 minutes of it, which usually means the cookies have expired.

## Your Own Topics

The labels come from post_processing/topics.csv, which gives about 50,000 of the most used hashtags a topic and, where there is one, a detail. Tags like #fyp that say nothing about the video are marked FILLER. A tag that isn't in it shows up in the report as itself, and every run lists those in scraper_data/post_processing/unlabelled_tags.csv, most used first.

To label them yourself, fill in the topic (and the detail if you want one) on the rows you care about, save the file as my_topics.csv in the repo root, and run `python pipeline.py --skip-scrape` again. Your rows win over the shipped ones, so the same file is also how you change a label you disagree with. Rows with no topic are skipped, and a topic can be any name you like, not just one already in the table.

```csv
tag,topic,detail
rizz,Relationships,
sza,R&B,SZA
fyp,FILLER,
```

To have a model do it instead, add `--label`. Nothing else in the repo uses one, and this works with any server that speaks the chat completions API, whether that's a hosted one or a local one like Ollama, LM Studio or llama.cpp. It sends each unknown tag and the tags it was posted with, 100 at a time, and adds the answers to my_topics.csv after each batch, where you can check and change them. A later run only asks about new tags.

LABEL_BASE_URL, LABEL_MODEL and LABEL_API_KEY pick the server, the model and its key (set them with `$env:NAME = "..."` in PowerShell). The defaults use claude-haiku-5-5, which labels about 2,500 tags for a few cents, and a local model costs nothing and needs no key.

```bash
export LABEL_API_KEY=...     # a key for the default
python pipeline.py --skip-scrape --label

export LABEL_BASE_URL=http://localhost:11434/v1   # or any other server, like Ollama here
export LABEL_MODEL=llama3.2
python pipeline.py --skip-scrape --label
```

## What It Won't Do

It won't log in for you, get past the bot challenge without your cookies, or download any videos. TikTok changes its page markup now and then, and the posts come back empty with a warning when it does. Running `python tiktok_post_scraper.py --parse-html page.html` on a saved post page is the quickest way to see what broke. A hashtag outside the topic table only gets a topic when it starts or ends with one the table knows (#makeuptips counts as Makeup), so a niche tag mostly stays as itself unless you run `--label`.

## Tests

None of the tests touch the network.

```bash
for test in test_*.py; do python "$test"; done
```
