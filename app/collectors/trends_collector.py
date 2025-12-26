from pytrends.request import TrendReq
from typing import List, Dict, Any
from datetime import datetime
import time
import random
import os


def collect_keyword_trends(keywords: List[str], geos: List[str] = None) -> List[Dict[str, Any]]:
    """Collect interest_over_time and interest_by_region for each keyword across one or more geos.

    This is synchronous; callers should run in a thread or executor when used from async code.
    Added retries, small random delays, and explicit request headers to reduce blocking.
    """
    if geos is None:
        geos = ["US"]
    # support passing a single geo as a string
    if isinstance(geos, str):
        geos = [geos]

    results = []
    # try a realistic browser User-Agent first (some Google endpoints reject unknown UAs)
    ua = os.getenv("PYTRENDS_USER_AGENT") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    # optional proxy support
    proxy = os.getenv('COLLECTOR_PROXY') or os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    req_args = {"headers": {"User-Agent": ua}}
    if proxy:
        # requests expects a dict of proxies
        req_args["proxies"] = {"http": proxy, "https": proxy}
    # primary pytrends client using a custom User-Agent; some networks
    # / Google responses may reject custom headers — we'll fallback below
    try:
        pytrend = TrendReq(hl="en-US", tz=360, requests_args=req_args)
    except Exception:
        # fallback to default client if custom requests_args cause issues
        try:
            pytrend = TrendReq(hl="en-US", tz=360)
        except Exception:
            pytrend = None

    # optional anchor to convert relative interest to absolute monthly searches
    # set PYTRENDS_ANCHOR_KEYWORD and PYTRENDS_ANCHOR_VOLUME in env to enable
    anchor_kw = os.getenv("PYTRENDS_ANCHOR_KEYWORD")
    anchor_vol = os.getenv("PYTRENDS_ANCHOR_VOLUME")
    anchor_val = None
    if anchor_kw and anchor_vol:
        try:
            pytrend.build_payload([anchor_kw], timeframe="today 90-d", geo=geos[0] if geos else "US")
            a_iot = pytrend.interest_over_time()
            if a_iot is not None and not a_iot.empty:
                try:
                    acol = a_iot[anchor_kw].tolist()
                    if acol:
                        # use recent 30-day average for anchor
                        if len(acol) >= 30:
                            anchor_val = sum(acol[-30:]) / 30
                        else:
                            anchor_val = sum(acol) / len(acol)
                except Exception:
                    anchor_val = None
        except Exception:
            anchor_val = None

    for geo in geos:
        for kw in keywords:
            # per-keyword retry with exponential backoff on 429 errors
            backoff = 5
            attempts = 4
            for attempt in range(attempts):
                try:
                    # small randomized delay to avoid triggering rate limits
                    time.sleep(random.uniform(0.5, 2.0))
                    try:
                        pytrend.build_payload([kw], timeframe="today 90-d", geo=geo)
                    except Exception as e_build:
                        # If Google returns 400 or similar, retry with conservative
                        # pytrends settings (no custom headers, explicit timeouts/retries)
                        se = str(e_build)
                        print(f"pytrends build_payload error, retrying with fallback client: {se}")
                        try:
                            pytrend = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
                            pytrend.build_payload([kw], timeframe="today 90-d", geo=geo)
                        except Exception as e2:
                            # surface the error and abort this keyword
                            print(f"pytrends fallback failed for {kw} {geo}: {e2}")
                            raise
                    iot_df = pytrend.interest_over_time()
                    if iot_df is None or iot_df.empty:
                        print(f"pytrends: no interest_over_time for {kw} {geo}")
                        break
                    ibr_df = pytrend.interest_by_region(resolution="COUNTRY", inc_low_vol=True)
                    related = {}
                    try:
                        related = pytrend.related_queries().get(kw, {})
                    except Exception as e:
                        print(f"pytrends related_queries error for {kw}:{geo}: {e}")

                    # convert iot_df to list of values for the kw column
                    vals = []
                    try:
                        col = iot_df[kw].tolist()
                        vals = [float(v) for v in col]
                    except Exception:
                        vals = []

                    if len(vals) >= 60:
                        last30 = sum(vals[-30:]) / 30
                        prev30 = sum(vals[-60:-30]) / 30
                        # 60-day windows
                        last60 = sum(vals[-60:]) / 60
                        prev60 = sum(vals[:-60]) / max(1, len(vals[:-60])) if len(vals) > 60 else last60
                    elif len(vals) >= 30:
                        last30 = sum(vals[-30:]) / 30
                        prev30 = sum(vals[:-30]) / max(1, len(vals[:-30]))
                        last60 = last30
                        prev60 = prev30
                    elif len(vals) >= 30:
                        last30 = sum(vals[-30:]) / 30
                        prev30 = sum(vals[:-30]) / max(1, len(vals[:-30]))
                        last60 = last30
                        prev60 = prev30
                    elif vals:
                        last30 = sum(vals) / len(vals)
                        prev30 = last30
                        last60 = last30
                        prev60 = prev30
                    else:
                        last30 = 0.0
                        prev30 = 0.0
                        last60 = 0.0
                        prev60 = 0.0

                    growth = (last30 - prev30) / max(1, prev30) if prev30 != 0 else 0.0
                    # 60-day growth (if available)
                    growth60 = (last60 - prev60) / max(1, prev60) if prev60 != 0 else 0.0

                    # estimate monthly searches if an anchor keyword+volume is provided
                    monthly_est = None
                    try:
                        if anchor_val and anchor_vol and anchor_val > 0:
                            multiplier = float(anchor_vol) / float(anchor_val)
                            # use 30-day average (last30) as representative interest
                            monthly_est = max(0, int(last30 * multiplier))
                    except Exception:
                        monthly_est = None

                    res = {
                        "platform": "GoogleTrends",
                        "source_id": f"trends:{kw}:{geo}",
                        "keyword": kw,
                        "country": geo,
                        "metrics": {
                            "interest_over_time": iot_df.to_dict() if hasattr(iot_df, "to_dict") else {},
                            "interest_by_region": ibr_df.to_dict() if hasattr(ibr_df, "to_dict") else {},
                            "related_queries": related,
                            "growth_pct_30d": growth,
                            "growth_pct_60d": growth60,
                            "monthly_search_estimate": monthly_est,
                        },
                        "scrape_ts": datetime.utcnow().isoformat() + "Z",
                    }
                    results.append(res)
                    break
                except Exception as e:
                    se = str(e)
                    # detect rate-limit and backoff
                    if "429" in se or "rate limit" in se.lower():
                        print(f"pytrends rate-limited for {kw} {geo}, attempt {attempt+1}/{attempts}, sleeping {backoff}s")
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    print(f"pytrends error for {kw} {geo}: {e}")
                    break
    return results
