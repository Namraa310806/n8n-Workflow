import json
from pathlib import Path
from datetime import datetime

RESP = Path("data") / "response.json"

def load():
    with RESP.open("r", encoding="utf-8") as f:
        return json.load(f)

def write(obj):
    with RESP.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def normalize_base(sid: str):
    return sid.split("::")[0] if sid else sid

def make_variant_from(item, country):
    new = json.loads(json.dumps(item))
    metrics = new.get("metrics", {})
    metrics["country"] = country
    new["metrics"] = metrics
    base = normalize_base(new.get("source_id", ""))
    new["source_id"] = f"{base}::{country}"
    return new

def process_list(lst):
    # map[(base,country)] -> item
    m = {}
    by_base = {}
    for it in lst:
        sid = it.get("source_id", "")
        base = normalize_base(sid)
        metrics = it.get("metrics") or {}
        country = metrics.get("country")
        key = (base, country)
        if key not in m:
            # ensure country is set in metrics for entries that have it
            if country:
                m[key] = it
            else:
                # store as unspecified under (base, None)
                m[key] = it
        by_base.setdefault(base, []).append(key)

    out = []
    for base in list(by_base.keys()):
        # prefer keyed items: existing country-specific, else unspecified
        us_key = (base, "US")
        in_key = (base, "IN")
        unspecified_key = (base, None)

        if us_key in m:
            out.append(m[us_key])
        else:
            src = m.get(in_key) or m.get(unspecified_key)
            if src:
                out.append(make_variant_from(src, "US"))

        if in_key in m:
            out.append(m[in_key])
        else:
            src = m.get(us_key) or m.get(unspecified_key)
            if src:
                out.append(make_variant_from(src, "IN"))

    return out

def main():
    if not RESP.exists():
        print("response.json not found")
        return
    resp = load()
    changed = False
    for key in ("youtube", "discourse"):
        if key in resp:
            orig = resp[key]
            new = process_list(orig)
            resp[key] = new
            changed = True
            print(f"Deduped {key}: {len(orig)} -> {len(new)} entries")

    if changed:
        resp["updated_at"] = datetime.utcnow().isoformat() + "Z"
        write(resp)
        print("response.json deduplicated and ensured US/IN variants")
    else:
        print("No youtube/discourse keys found; nothing changed")

if __name__ == '__main__':
    main()
