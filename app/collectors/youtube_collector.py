import os
import asyncio
import time
import logging
from typing import List, Dict, Any
import httpx
from datetime import datetime
import re
import json

logger = logging.getLogger("youtube_collector")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_API_KEYS = [k.strip() for k in os.getenv("YOUTUBE_API_KEYS", "").split(",") if k.strip()]
# If a single key is provided via YOUTUBE_API_KEY, include it in the keys list
if YOUTUBE_API_KEY and YOUTUBE_API_KEY not in YOUTUBE_API_KEYS:
    YOUTUBE_API_KEYS.insert(0, YOUTUBE_API_KEY)

# rotation state
_yt_key_index = 0
_yt_key_lock = asyncio.Lock()
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


async def _get(client: httpx.AsyncClient, url: str, params: dict, retries: int = 3) -> dict:
    global _yt_key_index
    backoff = 1
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, timeout=30.0)
            if resp.status_code == 200:
                return resp.json()
            # Log rate limit or other non-200 responses to aid debugging
            logger.warning("GET %s returned status %s: %s", url, resp.status_code, resp.text[:200])
            if resp.status_code in (429, 403):
                # rate limit / quota — try rotating keys (if available) then backoff
                if YOUTUBE_API_KEYS:
                    # attempt to rotate to the next key (async-safe)
                    async with _yt_key_lock:
                        global _yt_key_index
                        old_index = _yt_key_index
                        _yt_key_index = (_yt_key_index + 1) % len(YOUTUBE_API_KEYS)
                        new_key = YOUTUBE_API_KEYS[_yt_key_index]
                        params["key"] = new_key
                        logger.info("Rotated YouTube API key index %s -> %s", old_index, _yt_key_index)
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("HTTP error on GET %s: %s", url, e)
            await asyncio.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"Failed to GET {url} after {retries} retries")


async def search_videos(query: str, region: str = "US", max_pages: int = 2) -> List[Dict[str, Any]]:
    """Search YouTube for videos matching `query`. Returns list of video metadata dicts.

    This function performs a paginated `search.list` and then batches `videos.list` calls to retrieve statistics.
    """
    # If no API keys available, fall back to HTML scraping of YouTube search results
    if not (YOUTUBE_API_KEY or YOUTUBE_API_KEYS):
        return await search_videos_via_html(query, region=region, max_pages=max_pages)

    # choose an initial key (do not rebind global variables)
    if YOUTUBE_API_KEYS:
        key = YOUTUBE_API_KEYS[_yt_key_index]
    else:
        key = YOUTUBE_API_KEY

    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        page_token = None
        pages = 0
        while pages < max_pages:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 50,
                "key": key,
                "regionCode": region,
            }
            if page_token:
                params["pageToken"] = page_token

            data = await _get(client, YOUTUBE_SEARCH_URL, params)
            page_items = data.get("items", [])
            video_ids = [it["id"]["videoId"] for it in page_items if it.get("id", {}).get("videoId")]
            if not video_ids:
                break

            # fetch video details in a batch
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i : i + 50]
                vparams = {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "key": key,
                }
                vdata = await _get(client, YOUTUBE_VIDEOS_URL, vparams)
                for v in vdata.get("items", []):
                    stats = v.get("statistics", {})
                    snippet = v.get("snippet", {})
                    vid = v.get("id")
                    # safe conversions
                    def _int(x):
                        try:
                            return int(x)
                        except Exception:
                            return None

                    evidence = {
                        "platform": "YouTube",
                        "source_id": f"youtube:{vid}",
                        "source_url": f"https://www.youtube.com/watch?v={vid}",
                        "title": snippet.get("title"),
                        "metrics": {
                            "views": _int(stats.get("viewCount")),
                            "likes": _int(stats.get("likeCount")),
                            "comments": _int(stats.get("commentCount")),
                            "published_at": snippet.get("publishedAt"),
                            "country": region,
                        },
                        "scrape_ts": datetime.utcnow().isoformat() + "Z",
                    }
                    items.append(evidence)

            page_token = data.get("nextPageToken")
            pages += 1
            if not page_token:
                break
            # small delay to avoid quota bursts
            await asyncio.sleep(0.5)

    return items


async def search_videos_via_html(query: str, region: str = "US", max_pages: int = 1) -> List[Dict[str, Any]]:
    """Lightweight HTML fallback that fetches YouTube search page and extracts video ids and basic metrics.

    This is intentionally simple (parses the `ytInitialData` JSON blob) and not a full-featured parser.
    """
    items: List[Dict[str, Any]] = []
    params = {"search_query": query}
    headers = {"User-Agent": "n8n-popularity-collector/1.0 (+https://github.com)"}
    search_url = f"https://www.youtube.com/results"
    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        try:
            r = await client.get(search_url, params={"search_query": query})
            html = r.text or ""
        except Exception:
            return items

    # Extract the ytInitialData JSON blob
    m = re.search(r"var ytInitialData = (\{.*?\});", html, re.DOTALL)
    if not m:
        # alternative pattern
        m = re.search(r"window\[\"ytInitialData\"\] = (\{.*?\});", html, re.DOTALL)
    if not m:
        # try to find JSON embedded without var assignment
        m = re.search(r"(\{\"contents\".*\})", html, re.DOTALL)
    if not m:
        return items

    try:
        jd = json.loads(m.group(1))
    except Exception:
        return items

    # walk the JSON to find videoRenderer entries
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "videoRenderer" or (k == "videoRenderer" and isinstance(v, dict)):
                    yield v
                else:
                    for sub in walk(v):
                        yield sub
        elif isinstance(obj, list):
            for i in obj:
                for sub in walk(i):
                    yield sub

    found = []
    for vr in walk(jd):
        if not isinstance(vr, dict):
            continue
        vid = vr.get("videoId")
        snippet = vr.get("title", {}).get("runs", [])
        title = None
        if snippet and isinstance(snippet, list):
            title = "".join([r.get("text", "") for r in snippet])
        # view count text
        views_text = None
        vc = vr.get("viewCountText") or {}
        if isinstance(vc, dict):
            views_text = vc.get("simpleText") or vc.get("runs", [{}])[0].get("text")
        # try to parse integer from views_text
        def parse_int(s):
            try:
                if not s:
                    return None
                s = s.replace("views", "").replace("view", "").strip()
                s = s.replace(",", "")
                # handle suffixes like 1.2K
                if s.endswith("K") or s.endswith("M") or s.endswith("B"):
                    mult = 1
                    if s.endswith("K"):
                        mult = 1_000
                        s = s[:-1]
                    elif s.endswith("M"):
                        mult = 1_000_000
                        s = s[:-1]
                    elif s.endswith("B"):
                        mult = 1_000_000_000
                        s = s[:-1]
                    return int(float(s) * mult)
                return int(re.sub(r"[^0-9]", "", s))
            except Exception:
                return None

        views = parse_int(views_text)
        if vid:
            evidence = {
                "platform": "YouTube",
                "source_id": f"youtube:{vid}",
                "source_url": f"https://www.youtube.com/watch?v={vid}",
                "title": title,
                "metrics": {"views": views, "likes": None, "comments": None, "country": region},
                "scrape_ts": datetime.utcnow().isoformat() + "Z",
            }
            items.append(evidence)
            found.append(vid)
        if len(items) >= 50 * max_pages:
            break

    return items


async def collect_seed_queries(seed_queries: List[str], region: str = "US", max_pages_per_query: int = 2) -> List[Dict[str, Any]]:
    """Collect evidence items for multiple seed queries concurrently."""
    tasks = []
    for q in seed_queries:
        tasks.append(search_videos(q, region=region, max_pages=max_pages_per_query))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_items: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception):
            # log or handle
            continue
        all_items.extend(r)
    return all_items
