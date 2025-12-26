"""Google Ads / Keyword Planner helper (best-effort).

This file provides a guarded wrapper around the Google Ads Keyword Planner API.
It will only run when the `google-ads` Python library is installed and a
Google Ads configuration (yaml) is available. For many reviewers the easiest
path is to use the `pytrends` collector; this module is provided for completeness
and will return an empty list when credentials are not available.

Environment hints:
- Set `GOOGLE_ADS_CONFIG_PATH` to a google-ads.yaml configuration file path
  (containing developer_token, client_id/secret, refresh_token, login_customer_id).
- Set `GOOGLE_ADS_CUSTOMER_ID` to the target customer ID (string of digits).

If you want monthly search volumes for a keyword without Ads API access,
use `pytrends` anchor-based estimate in `trends_collector.py`.
"""
from typing import List, Dict, Any
import os
import json


def collect_keyword_volumes(keywords: List[str], geo: str = "US") -> List[Dict[str, Any]]:
    """Attempt to fetch Keyword Planner monthly search volumes.

    Returns list of dicts like:
    {
      "platform": "GoogleAds",
      "keyword": "n8n Slack integration",
      "country": "US",
      "metrics": { "monthly_searches": 3600, "competition": 0.4 }
    }

    If the google-ads client or credentials are missing this returns [].
    """
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
    except Exception:
        print("google-ads library not installed; skipping Google Ads Keyword Planner")
        return []

    config_path = os.getenv("GOOGLE_ADS_CONFIG_PATH")
    customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID")
    if not config_path or not customer_id:
        print("GOOGLE_ADS_CONFIG_PATH or GOOGLE_ADS_CUSTOMER_ID not set; skipping Google Ads calls")
        return []

    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as e:
        print(f"Failed to load Google Ads config: {e}")
        return []

    service = client.get_service("KeywordPlanIdeaService")
    # The Ads API expects location and language constants; for simplicity this
    # implementation uses minimal required fields and may need to be adapted.
    results = []
    try:
        for kw in keywords:
            try:
                # Build request payload according to google-ads docs
                request = {
                    "customer_id": customer_id,
                    "language": "1000",  # English
                    "geo_target_constants": [],
                    "keyword_plan_network": "GOOGLE_SEARCH",
                    "keyword_seed": {"keywords": [kw]},
                }
                resp = service.generate_keyword_ideas(request=request)
                # Parse response — each idea contains average_monthly_searches
                monthly = None
                comp = None
                for idea in resp:
                    metrics = idea.keyword_idea_metrics
                    if metrics and metrics.avg_monthly_searches:
                        monthly = int(metrics.avg_monthly_searches)
                        comp = float(metrics.competition) if metrics.competition is not None else None
                        break

                results.append({
                    "platform": "GoogleAds",
                    "keyword": kw,
                    "country": geo,
                    "metrics": {"monthly_searches": monthly, "competition": comp},
                })
            except GoogleAdsException as ge:
                print(f"GoogleAds API error for {kw}: {ge}")
                continue
            except Exception as e:
                print(f"GoogleAds unexpected error for {kw}: {e}")
                continue
    except Exception as e:
        print(f"GoogleAds request failed: {e}")
        return []

    return results
