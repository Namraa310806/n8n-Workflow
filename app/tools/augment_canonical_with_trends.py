import json
from pathlib import Path

DATA = Path("data")
CANON = DATA / "canonical_workflows.json"
TRENDS = DATA / "trends_synth.json"

def load(p):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def write(p, obj):
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def build_trend_map():
    if not TRENDS.exists():
        return {}
    t = load(TRENDS)
    rows = t.get("rows") or []
    m = {}
    for r in rows:
        kw = (r.get("keyword") or "").lower()
        m[kw] = r
    return m

def match_trend_for_title(title, trend_map):
    if not title:
        return None
    tl = title.lower()
    # exact match first
    if tl in trend_map:
        return trend_map[tl]
    # token match
    for kw, v in trend_map.items():
        if kw and kw in tl:
            return v
    return None

def main():
    if not CANON.exists():
        print("canonical_workflows.json not found")
        return
    trend_map = build_trend_map()
    if not trend_map:
        print("no trends_synth.json rows found; skipping augmentation")
        return
    canon = load(CANON)
    updated = 0
    for item in canon:
        title = item.get("workflow") or ""
        match = match_trend_for_title(title, trend_map)
        if match:
            # attach per-country estimates if present in trends_synth rows
            item.setdefault("trend_metrics", {})
            item["trend_metrics"]["monthly_search_estimate"] = match.get("monthly_search_estimate")
            item["trend_metrics"]["growth_pct_60d"] = match.get("growth_pct_60d")
            updated += 1

    write(CANON, canon)
    print(f"Augmented {updated} canonical items with synthesized trend metrics")

if __name__ == '__main__':
    main()
