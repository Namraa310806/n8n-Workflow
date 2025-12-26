import json
from datetime import datetime
from pathlib import Path

DATA = Path("data")
TS_FILE = DATA / "trends_synth.json"
RESP_FILE = DATA / "response.json"

def load_json(p):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json(p, obj):
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def main():
    if not TS_FILE.exists():
        print("trends_synth.json not found")
        return
    ts = load_json(TS_FILE)
    rows = ts.get("rows") or []
    # build per-region entries (US and IN) by duplicating global synthesized values
    out = []
    now = datetime.utcnow().isoformat() + "Z"
    for r in rows:
        kw = r.get("keyword")
        if not kw:
            continue
        score = r.get("score")
        mentions = r.get("mentions")
        growth = r.get("growth_pct_60d")
        monthly = r.get("monthly_search_estimate")
        platforms = r.get("platforms")
        for country in ("US", "IN"):
            item = {
                "platform": "GoogleTrendsSynth",
                "source_id": f"trends_synth:{kw}:{country}",
                "keyword": kw,
                "country": country,
                "metrics": {
                    "score": score,
                    "count_mentions": mentions,
                    "monthly_search_estimate": monthly,
                    "growth_pct_60d": growth,
                    "platforms": platforms,
                },
                "scrape_ts": now,
            }
            out.append(item)

    # load existing response.json (or create skeleton)
    resp = {}
    if RESP_FILE.exists():
        try:
            resp = load_json(RESP_FILE)
        except Exception:
            resp = {}

    # replace/insert google_trends key
    resp["google_trends"] = out
    write_json(RESP_FILE, resp)
    print(f"Wrote {len(out)} per-region trend entries to {RESP_FILE}")

if __name__ == '__main__':
    main()
