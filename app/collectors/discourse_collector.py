import os
import asyncio
import httpx
from typing import List, Dict, Any
from datetime import datetime
import time
import math

BASE = os.getenv("DISCOURSE_BASE_URL", "https://community.n8n.io")
# Optional API credentials to increase rate-limits or access private endpoints
DISCOURSE_API_KEY = os.getenv("DISCOURSE_API_KEY")
DISCOURSE_API_USER = os.getenv("DISCOURSE_API_USER")
# Optional proxy (e.g. http://user:pass@host:port) - falls back to common env vars
PROXY = os.getenv("COLLECTOR_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")


async def _get(client: httpx.AsyncClient, url: str, params: dict = None, retries: int = 3) -> dict:
    backoff = 0.5
    headers = {}
    if DISCOURSE_API_KEY:
        headers["Api-Key"] = DISCOURSE_API_KEY
    if DISCOURSE_API_USER:
        headers["Api-Username"] = DISCOURSE_API_USER
    # add a sensible User-Agent to avoid being blocked by some forums
    headers.setdefault("User-Agent", "n8n-popularity-collector/1.0 (+https://github.com)")
    headers.setdefault("Accept", "application/json")

    # sensible timeout for individual requests
    timeout = httpx.Timeout(10.0)

    for attempt in range(retries):
        try:
            # support optional proxy for environments behind restricted networks
            if PROXY:
                async with httpx.AsyncClient(proxies=PROXY, timeout=timeout) as pclient:
                    resp = await pclient.get(url, params=params, headers=headers or None)
            else:
                resp = await client.get(url, params=params, headers=headers or None, timeout=timeout)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return {}
            if resp.status_code in (429, 503):
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            # log non-retryable status for diagnostics
            try:
                text = resp.text[:400]
            except Exception:
                text = "<no-body>"
            print(f"Discourse _get non-200 status={resp.status_code} url={url} params={params} body={text}")
            resp.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            # transient network error, backoff and retry
            print(f"Discourse _get error: {e} url={url} params={params} (attempt {attempt+1}/{retries})")
            await asyncio.sleep(backoff)
            # exponential backoff with jitter
            backoff = min(10, backoff * 2 + (math.sin(time.time()) % 1))
            continue
    return {}


# Simple in-memory cache for username -> country mapping
_user_country_cache = {}


async def infer_user_country(client: httpx.AsyncClient, username: str) -> str:
    """Try to infer country for a Discourse username via /u/{username}.json.

    Returns country code like 'US' or 'IN' or None.
    Caches results in-memory to avoid repeated lookups.
    """
    if not username:
        return None
    if username in _user_country_cache:
        return _user_country_cache[username]

    url = f"{BASE}/u/{username}.json"
    try:
        # lightweight per-user fetch
        ud = await _get(client, url, params=None, retries=2)
        user = ud.get("user") or ud
        # common fields that may hold location info
        cand = None
        if isinstance(user, dict):
            cand = user.get("location") or user.get("bio_raw") or None
            # some Discourse instances store custom fields under user_fields
            uf = user.get("user_fields") or user.get("user_fields_values") or None
            if not cand and isinstance(uf, dict):
                # join field values
                try:
                    cand = " ".join(str(v) for v in uf.values() if v)
                except Exception:
                    cand = None

        if cand:
            s = str(cand).lower()
            # simple heuristics
            if "india" in s or "in" in s and ("india" in s or "delhi" in s or "mumbai" in s or "bangalore" in s or "bengal" in s):
                _user_country_cache[username] = "IN"
                return "IN"
            if "india" in s or "bharat" in s or "mumbai" in s or "delhi" in s:
                _user_country_cache[username] = "IN"
                return "IN"
            if "united states" in s or "usa" in s or "us" in s or "america" in s or "new york" in s or "san francisco" in s or "california" in s:
                _user_country_cache[username] = "US"
                return "US"
            # detect country codes like IN or US standalone
            if "in" == s.strip() or s.strip().upper() == "IN":
                _user_country_cache[username] = "IN"
                return "IN"
            if "us" == s.strip() or s.strip().upper() == "US":
                _user_country_cache[username] = "US"
                return "US"

    except Exception:
        pass
    _user_country_cache[username] = None
    return None


async def search_topics(query: str, page: int = 0) -> List[Dict[str, Any]]:
    """Search Discourse for topics matching the query. Returns a list of topic evidence dicts."""
    url = f"{BASE}/search.json"
    params = {"q": query, "page": page}
    data = {}
    async with httpx.AsyncClient() as client:
        data = await _get(client, url, params=params)

    # fallback: if API search returns empty or access denied, try HTML search scraping
    if not data or data.get("errors"):
        try:
            # fetch search HTML and extract topic ids (HTML fallback when API is blocked)
            import re as _re
            search_html_url = f"{BASE}/search"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as html_client:
                # retry small number of times for flaky HTML endpoints
                retries = 3
                backoff = 0.5
                html = None
                for _ in range(retries):
                    try:
                        r = await html_client.get(search_html_url, params={"q": query})
                        if r.status_code == 200:
                            html = r.text or ""
                            break
                    except Exception as _e:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                if html is None:
                    html = ""
            ids = set()
            for m in _re.findall(r"/t/[\w-]+/(\d+)", html):
                ids.add(m)
            for m in _re.findall(r"/t/(\d+)", html):
                ids.add(m)
            if ids:
                topics = [{"topic_id": int(i), "title": None} for i in ids]
                data = {"topics": topics}
        except Exception:
            pass

    topics = []
    # Some Discourse endpoints return topic lists under different keys
    rows = data.get("topics") or data.get("rows") or data.get("topic_list", {}).get("topics") or []
    for r in rows:
        topic_id = r.get("id") or r.get("topic_id")
        title = r.get("title") or r.get("topic_title")
        if topic_id:
            topics.append({"topic_id": topic_id, "title": title})

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for t in topics:
            tid = t["topic_id"]
            turl = f"{BASE}/t/{tid}.json"
            td = await _get(client, turl, retries=3)
            if not td:
                continue
            topic = td.get("topic") or td
            posts_count = topic.get("posts_count") or 0
            views = topic.get("views") or 0
            like_count = 0
            posters = topic.get("posters") or []
            unique_contributors = len({p.get("user_id") for p in posters if p.get("user_id")})
            posts = td.get("post_stream", {}).get("posts", [])
            for p in posts:
                like_count += p.get("like_count", 0)

            # attempt to infer country from first poster username or posters list (best-effort)
            country = None
            try:
                # try first post username
                if posts and isinstance(posts, list):
                    first_username = posts[0].get("username") or posts[0].get("name")
                    if first_username:
                        country = await infer_user_country(client, first_username)
                # fallback to posters entries
                if not country and posters:
                    for pp in posters:
                        uname = pp.get("username") or (pp.get("extras") or {}).get("username")
                        if uname:
                            country = await infer_user_country(client, uname)
                            if country:
                                break
                # final fallback: scan all post usernames
                if not country:
                    for p in posts:
                        uname = p.get("username")
                        if uname:
                            country = await infer_user_country(client, uname)
                            if country:
                                break
            except Exception:
                country = None

            evidence = {
                "platform": "Discourse",
                "source_id": f"discourse:{tid}",
                "source_url": f"{BASE}/t/{tid}",
                "title": t.get("title") or topic.get("title"),
                "metrics": {
                    "replies": max(0, (posts_count or 0) - 1),
                    "likes": like_count,
                    "views": views or 0,
                    "unique_contributors": unique_contributors,
                    "first_post_ts": topic.get("created_at"),
                    "last_post_ts": topic.get("bumped_at") or topic.get("last_posted_at"),
                    "country": country,
                },
                "scrape_ts": datetime.utcnow().isoformat() + "Z",
            }
            results.append(evidence)

    return results


async def collect_seed_queries(seed_queries: List[str], max_pages: int = 2) -> List[Dict[str, Any]]:
    items = []
    for q in seed_queries:
        for p in range(max_pages):
            try:
                res = await search_topics(q, page=p)
                items.extend(res)
            except Exception:
                continue
    # if nothing found via search, fallback to scraping recent topics and filtering by query
    if not items:
        try:
            recent = await collect_recent_topics(max_pages * 2)
            for q in seed_queries:
                ql = q.lower()
                for t in recent:
                    if ql in (t.get("title") or "").lower():
                        items.append(t)
        except Exception:
            pass

    # de-duplicate by topic id
    seen = set()
    uniq = []
    for i in items:
        sid = i.get("source_id")
        if sid in seen:
            continue
        seen.add(sid)
        uniq.append(i)
    return uniq


async def collect_recent_topics(pages: int = 1) -> List[Dict[str, Any]]:
    """Scrape the community `/latest` pages to gather recent topic IDs, then fetch topic JSONs."""
    results: List[Dict[str, Any]] = []
    import re as _re
    # Try JSON endpoints first: /latest.json and /top.json (some Discourse installs expose these publicly)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        json_topics = []
        try:
            latest = await _get(client, f"{BASE}/latest.json")
            # latest.json often contains topic_list->topics
            json_topics = latest.get("topic_list", {}).get("topics") or latest.get("topics") or []
        except Exception:
            json_topics = []

        if not json_topics:
            try:
                top = await _get(client, f"{BASE}/top.json")
                json_topics = top.get("topic_list", {}).get("topics") or top.get("topics") or []
            except Exception:
                json_topics = []

        # If JSON topic lists available, consume them first
        seen_ids = set()
        for t in (json_topics or []):
            tid = t.get("id") or t.get("topic_id")
            if not tid:
                continue
            seen_ids.add(str(tid))
            try:
                # Some topic entries already carry metrics
                title = t.get("fancy_title") or t.get("title") or None
                posts_count = t.get("posts_count") or t.get("posts") or None
                views = t.get("views") or None
                like_count = t.get("like_count") or t.get("like_counts") or 0
                evidence = {
                    "platform": "Discourse",
                    "source_id": f"discourse:{tid}",
                    "source_url": f"{BASE}/t/{tid}",
                    "title": title,
                    "metrics": {
                        "replies": max(0, (posts_count or 0) - 1) if posts_count is not None else None,
                        "likes": like_count or 0,
                        "views": views or 0,
                        "unique_contributors": None,
                        "first_post_ts": None,
                        "last_post_ts": None,
                    },
                    "scrape_ts": datetime.utcnow().isoformat() + "Z",
                }
                results.append(evidence)
            except Exception:
                continue

        # Next, scrape /latest HTML to capture additional recent topics not present in JSON
        for p in range(pages):
            url = f"{BASE}/latest"
            params = {"page": p} if p > 0 else None
            try:
                # retry HTML fetches a few times to avoid transient network hangs
                page_retries = 3
                page_backoff = 0.5
                html = None
                for _ in range(page_retries):
                    try:
                        r = await client.get(url, params=params)
                        if r.status_code == 200:
                            html = r.text or ""
                            break
                    except Exception:
                        await asyncio.sleep(page_backoff)
                        page_backoff *= 2
                if not html:
                    continue
                ids = list(dict.fromkeys(_re.findall(r"/t/[\w-]+/(\d+)", html)))
                for tid in ids:
                    if str(tid) in seen_ids:
                        continue
                    try:
                        td = await _get(client, f"{BASE}/t/{tid}.json")
                        title = None
                        posts_count = None
                        views = None
                        like_count = 0
                        unique_contributors = None

                        if td:
                            topic = td.get("topic") or td
                            posts_count = topic.get("posts_count") or 0
                            views = topic.get("views") or 0
                            posters = topic.get("posters") or []
                            unique_contributors = len({pp.get("user_id") for pp in posters if pp.get("user_id")})
                            posts = td.get("post_stream", {}).get("posts", [])
                            for pp in posts:
                                like_count += pp.get("like_count", 0)
                            title = topic.get("title") or topic.get("fancy_title") or None
                        else:
                            # JSON blocked — fallback to HTML topic page and extract metrics heuristically
                            try:
                                h = await client.get(f"{BASE}/t/{tid}", timeout=20.0)
                                htext = h.text or ""
                                m = _re.search(r"<meta property=\"og:title\" content=\"([^\"]+)\"", htext)
                                if not m:
                                    m = _re.search(r"<title>([^<]+)</title>", htext)
                                if m:
                                    title = m.group(1).strip()
                                # replies/posts: count post markers
                                posts_found = len(_re.findall(r"data-post-id=\"\d+\"", htext))
                                if posts_found == 0:
                                    posts_found = len(_re.findall(r"<article", htext))
                                posts_count = posts_found
                                # Try to extract views: look for patterns like "123 views" or "Views" labels
                                v = _re.search(r"([0-9,]+)\s+views", htext, _re.IGNORECASE)
                                if v:
                                    views = int(v.group(1).replace(",", ""))
                                else:
                                    # alternative: look for data attribute
                                    v2 = _re.search(r"\"views\":\s*(\d+)", htext)
                                    if v2:
                                        views = int(v2.group(1))
                                # likes: sum visible like counts in the HTML
                                likes = 0
                                for lm in _re.findall(r"like-count\">?\s*([0-9,]+)", htext):
                                    try:
                                        likes += int(lm.replace(",", ""))
                                    except Exception:
                                        continue
                                if likes == 0:
                                    # try aria-label patterns
                                    for lm in _re.findall(r"aria-label=\"([0-9,]+) likes?\"", htext, _re.IGNORECASE):
                                        try:
                                            likes += int(lm.replace(",", ""))
                                        except Exception:
                                            continue
                                like_count = likes
                                unique_contributors = None
                            except Exception:
                                continue

                        evidence = {
                            "platform": "Discourse",
                            "source_id": f"discourse:{tid}",
                            "source_url": f"{BASE}/t/{tid}",
                            "title": title,
                            "metrics": {
                                "replies": max(0, (posts_count or 0) - 1) if posts_count is not None else None,
                                "likes": like_count,
                                "views": views if views is not None else 0,
                                "unique_contributors": unique_contributors,
                                "first_post_ts": None,
                                "last_post_ts": None,
                            },
                            "scrape_ts": datetime.utcnow().isoformat() + "Z",
                        }
                        results.append(evidence)
                    except Exception:
                        continue
            except Exception:
                continue
    return results
