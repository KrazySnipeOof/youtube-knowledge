#!/usr/bin/env python3
"""
YouTube Knowledge - description link scraper.

Pipeline:
  1. FETCH   - use the yt-dlp CLI to pull full video metadata (incl. the
               description) for topic search queries and configured channels.
  2. EXTRACT - pull every URL out of each description (decoding YouTube
               redirect links along the way).
  3. FILTER  - smart-filter out social / sponsor / affiliate / self junk.
  4. RANK    - dedupe links and rank them by how many distinct videos and
               channels cite them (cross-referenced links are more useful).
  5. TAG     - categorize each link into your topics (AI / ML / Quant /
               Learning / Crypto).
  6. WRITE   - emit web/data.json for the frontend, plus a raw cache.

Usage:
  python scraper/scrape.py                 # full run (network)
  python scraper/scrape.py --topics ai ml  # only these topics
  python scraper/scrape.py --no-fetch      # rebuild from cache, no network
  python scraper/scrape.py --limit 5       # override per-source video count
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pyyaml.  Install with:  pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
CACHE_PATH = ROOT / "data" / "raw_videos.jsonl"
OUTPUT_PATH = ROOT / "web" / "data.json"

# --------------------------------------------------------------------------- #
# URL handling
# --------------------------------------------------------------------------- #
URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)
# Trailing characters that are usually punctuation, not part of the URL.
TRAILING = ".,;:!?'\"”’)>]}"
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "feature", "si", "ab_channel", "app", "fbclid", "gclid", "igshid",
}


def decode_youtube_redirect(url: str) -> str:
    """YouTube wraps description links as youtube.com/redirect?...&q=<real>."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("youtube.com") and parsed.path == "/redirect":
        q = urllib.parse.parse_qs(parsed.query).get("q")
        if q:
            return urllib.parse.unquote(q[0])
    return url


def clean_url(url: str) -> str | None:
    """Normalize a raw URL: decode redirects, strip tracking, tidy trailing."""
    url = url.strip().rstrip(TRAILING)
    if not url:
        return None
    url = decode_youtube_redirect(url)
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    # Drop tracking query params, keep the rest.
    query_pairs = [
        (k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
        if k.lower() not in TRACKING_PARAMS
    ]
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = urllib.parse.urlencode(query_pairs)
    cleaned = urllib.parse.urlunparse(
        (parsed.scheme, netloc, path, "", query, "")
    )
    return cleaned


def registrable_domain(url: str) -> str:
    """A rough registrable domain: strip www and collapse to the last labels."""
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Handle a few common two-part TLDs (co.uk, com.au, ...).
    two_part_tlds = {"co", "com", "org", "net", "gov", "edu", "ac"}
    if parts[-2] in two_part_tlds and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# --------------------------------------------------------------------------- #
# Fetching via yt-dlp
# --------------------------------------------------------------------------- #
def run_ytdlp(target: str, count: int) -> list[dict]:
    """Run yt-dlp for one target, returning a list of full video-info dicts."""
    cmd = [
        "yt-dlp",
        "--ignore-errors",
        "--no-warnings",
        "--skip-download",
        "--dump-json",
        "--playlist-end", str(count),
        target,
    ]
    print(f"    $ yt-dlp ... {target!r}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except FileNotFoundError:
        sys.exit("yt-dlp not found on PATH. Install it: https://github.com/yt-dlp/yt-dlp")
    except subprocess.TimeoutExpired:
        print("      ! timed out, skipping")
        return []

    videos = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not videos and proc.stderr:
        first_err = proc.stderr.strip().splitlines()[:1]
        if first_err:
            print(f"      ! {first_err[0]}")
    return videos


def slim_video(info: dict, source: str, topic: str) -> dict:
    """Keep only the fields we need from a heavy yt-dlp info dict."""
    return {
        "id": info.get("id"),
        "title": info.get("title") or "(untitled)",
        "url": info.get("webpage_url") or info.get("original_url") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
        "description": info.get("description") or "",
        "source": source,   # "search" or "channel"
        "topic": topic,      # topic hint from the query/channel it came from
    }


def fetch(config: dict, only_topics: list[str] | None, limit_override: int | None) -> list[dict]:
    per_query = limit_override or config["limits"]["per_query"]
    per_channel = limit_override or config["limits"]["per_channel"]

    videos: list[dict] = []
    seen_ids: set[str] = set()

    def add(info: dict, source: str, topic: str):
        vid = info.get("id")
        if not vid or vid in seen_ids:
            return
        seen_ids.add(vid)
        videos.append(slim_video(info, source, topic))

    # --- searches ---
    for topic_key, topic_cfg in config["topics"].items():
        if only_topics and topic_key not in only_topics:
            continue
        for query in topic_cfg.get("queries", []):
            print(f"  [search:{topic_key}] {query}")
            target = f"ytsearch{per_query}:{query}"
            for info in run_ytdlp(target, per_query):
                add(info, "search", topic_key)

    # --- channels / playlists ---
    for entry in config.get("channels") or []:
        topic_key = entry.get("topic", "")
        if only_topics and topic_key and topic_key not in only_topics:
            continue
        url = entry.get("url")
        if not url:
            continue
        print(f"  [channel:{topic_key or '?'}] {url}")
        for info in run_ytdlp(url, per_channel):
            add(info, "channel", topic_key)

    return videos


# --------------------------------------------------------------------------- #
# Filter + categorize + rank
# --------------------------------------------------------------------------- #
def build_topic_matchers(config: dict) -> dict[str, list[str]]:
    return {
        key: [k.lower() for k in cfg.get("keywords", [])]
        for key, cfg in config["topics"].items()
    }


def keyword_topics(text: str, matchers: dict[str, list[str]]) -> set[str]:
    """Topics implied by keywords in a link's own URL + description label."""
    haystack = text.lower()
    return {
        topic_key for topic_key, keywords in matchers.items()
        if any(kw in haystack for kw in keywords)
    }


def resolve_source_topics(source_topics: list[str]) -> set[str]:
    """Discovery buckets that genuinely apply to a link.

    Keep a topic if the link recurs (>=2 videos) in that search bucket;
    otherwise fall back to the single most common bucket. This stops a
    generic resource cited once in every topic from being tagged as all five.
    """
    counts = Counter(t for t in source_topics if t)
    if not counts:
        return set()
    strong = {t for t, c in counts.items() if c >= 2}
    return strong or {counts.most_common(1)[0][0]}


def is_junk(url: str, domain: str, flt: dict) -> bool:
    if domain in set(flt.get("keep_domains") or []):
        return False
    if domain in set(flt.get("drop_domains") or []):
        return True
    low = url.lower()
    for sub in flt.get("drop_url_substrings") or []:
        if sub.lower() in low:
            return True
    return False


def context_line(description: str, url_raw: str) -> str:
    """The text on the same line as the URL - often a human label for it."""
    for line in description.splitlines():
        if url_raw in line:
            cleaned = line.replace(url_raw, " ").strip(" -–—•:|>")
            return cleaned[:160]
    return ""


def process(videos: list[dict], config: dict) -> dict:
    flt = config.get("filter", {})
    matchers = build_topic_matchers(config)

    # url -> aggregate record
    links: dict[str, dict] = {}

    for v in videos:
        desc = v.get("description", "")
        if not desc:
            continue
        # Preserve first-seen order, dedupe within a single description.
        seen_here: set[str] = set()
        for raw in URL_RE.findall(desc):
            cleaned = clean_url(raw)
            if not cleaned:
                continue
            domain = registrable_domain(cleaned)
            if is_junk(cleaned, domain, flt):
                continue
            if cleaned in seen_here:
                continue
            seen_here.add(cleaned)

            ctx = context_line(desc, raw)
            rec = links.get(cleaned)
            if rec is None:
                rec = {
                    "url": cleaned,
                    "domain": domain,
                    "label": ctx or domain,
                    "kw_topics": set(),     # from the link's own url + label
                    "source_topics": [],    # discovery bucket per citing video
                    "videos": {},           # video_id -> source info
                    "channels": set(),
                }
                links[cleaned] = rec

            rec["kw_topics"].update(keyword_topics(f"{cleaned} {ctx}", matchers))
            if v.get("topic"):
                rec["source_topics"].append(v["topic"])
            if not rec["label"] or rec["label"] == domain:
                if ctx:
                    rec["label"] = ctx
            rec["videos"][v["id"]] = {
                "video_title": v["title"],
                "video_url": v["url"],
                "channel": v["channel"],
                "channel_url": v["channel_url"],
                "source": v["source"],
                "topic": v.get("topic", ""),
            }
            if v["channel"]:
                rec["channels"].add(v["channel"])

    # Finalize + score.
    out_links = []
    for rec in links.values():
        video_count = len(rec["videos"])
        channel_count = len(rec["channels"])
        # Cross-channel citations weigh more than repeats from one channel.
        score = channel_count * 3 + video_count
        topics = rec["kw_topics"] | resolve_source_topics(rec["source_topics"])
        out_links.append({
            "url": rec["url"],
            "domain": rec["domain"],
            "label": rec["label"],
            "topics": sorted(topics) or ["uncategorized"],
            "video_count": video_count,
            "channel_count": channel_count,
            "score": score,
            "sources": list(rec["videos"].values()),
        })

    out_links.sort(key=lambda l: (l["score"], l["video_count"], l["domain"]), reverse=True)

    topic_labels = {k: cfg.get("label", k.title()) for k, cfg in config["topics"].items()}
    topic_labels["uncategorized"] = "Uncategorized"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "topic_labels": topic_labels,
        "stats": {
            "videos_scanned": len(videos),
            "unique_links": len(out_links),
        },
        "links": out_links,
    }


# --------------------------------------------------------------------------- #
# Cache I/O
# --------------------------------------------------------------------------- #
def write_cache(videos: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        for v in videos:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")


def read_cache() -> list[dict]:
    if not CACHE_PATH.exists():
        sys.exit(f"No cache at {CACHE_PATH}. Run once without --no-fetch first.")
    videos = []
    with CACHE_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                videos.append(json.loads(line))
    return videos


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape YouTube descriptions for useful links.")
    ap.add_argument("--topics", nargs="*", help="only these topic keys (e.g. ai ml crypto)")
    ap.add_argument("--limit", type=int, help="override videos fetched per source")
    ap.add_argument("--no-fetch", action="store_true", help="rebuild from cache, no network")
    args = ap.parse_args()

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    if args.no_fetch:
        print("Loading videos from cache ...")
        videos = read_cache()
    else:
        print("Fetching videos via yt-dlp ...")
        videos = fetch(config, args.topics, args.limit)
        write_cache(videos)
        print(f"Cached {len(videos)} videos -> {CACHE_PATH}")

    print(f"Processing {len(videos)} videos ...")
    result = process(videos, config)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Done. {result['stats']['unique_links']} unique links from "
        f"{result['stats']['videos_scanned']} videos -> {OUTPUT_PATH}"
    )
    print("View them:  python serve.py   (then open http://localhost:8000)")


if __name__ == "__main__":
    main()
