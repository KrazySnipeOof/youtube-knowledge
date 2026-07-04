# YouTube Knowledge

Scrapes **YouTube video descriptions** for useful links — the kind you'd only
find by opening a video and expanding its description — then filters, dedupes,
ranks, and categorizes them into a browsable web page.

Topics out of the box: **AI · Machine Learning · Quant Finance · Learning · Crypto**.

Links are discovered from **both** keyword searches *and* any channels/playlists
you list. A **smart filter** drops social, sponsor, and affiliate junk, and
links are **ranked** by how many distinct videos and channels cite them —
so links referenced across many independent creators float to the top.

## How it works

```
 yt-dlp (search + channels)  →  descriptions  →  extract URLs
        →  smart filter  →  dedupe + rank  →  categorize  →  web/data.json  →  frontend
```

No YouTube API key required — it drives the `yt-dlp` CLI.

## Requirements

- **Python 3.9+**
- **yt-dlp** on your PATH — `pip install -U yt-dlp` (check with `yt-dlp --version`)
- `pip install -r requirements.txt` (just PyYAML)

## Usage

```bash
# 1. Scrape (hits the network via yt-dlp; takes a few minutes)
python scraper/scrape.py

# 2. Browse the results
python serve.py            # opens http://localhost:8000
```

### Handy flags

```bash
python scraper/scrape.py --topics ai crypto   # only some topics
python scraper/scrape.py --limit 5            # fewer videos per source (fast test)
python scraper/scrape.py --no-fetch           # re-run filtering on the cache, no network
```

`--no-fetch` is great for tuning `config.yaml` filters — it reuses the raw
videos cached in `data/raw_videos.jsonl` instead of re-downloading.

## Configuring

Everything lives in [`config.yaml`](config.yaml):

- **`topics`** — search `queries` (what to look for) and `keywords` (what tags a
  link with that topic).
- **`channels`** — trusted channels/playlists to always harvest, e.g.
  ```yaml
  channels:
    - url: "https://www.youtube.com/@TwoMinutePapers/videos"
      topic: ml
    - url: "https://www.youtube.com/playlist?list=PLxxxx"
      topic: quant
  ```
- **`filter`** — `drop_domains` (social/sponsors), `drop_url_substrings`
  (affiliate patterns), and `keep_domains` (allowlist override).
- **`limits`** — `per_query` / `per_channel` video counts (raise for coverage,
  lower for speed).

## The frontend

`web/` is a dependency-free static page. It reads `web/data.json` and lets you:

- filter by topic (multi-select chips),
- full-text search across links, domains, and source video/channel names,
- sort by rank, most videos, most channels, or domain,
- expand each link to see exactly which videos cited it.

## Layout

```
config.yaml            # what to scrape + how to filter
scraper/scrape.py      # the scraper/ranker
serve.py               # tiny static server for the frontend
web/                   # frontend (index.html, style.css, app.js) + data.json
data/raw_videos.jsonl  # cache of fetched video metadata
```
