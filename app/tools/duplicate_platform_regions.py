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

def ensure_country_metric(item, country):
    metrics = item.get("metrics") or {}
    metrics["country"] = country
    item["metrics"] = metrics

def make_variant(item, country):
    new = json.loads(json.dumps(item))
    ensure_country_metric(new, country)
    sid = new.get("source_id", "")
    # append country suffix if not present
    if not sid.endswith(f"::{country}"):
        new["source_id"] = f"{sid}::{country}"
    return new

def process_list(lst):
    # map of base source_id (without ::COUNTRY) to existing country set
    base_map = {}
    for it in lst:
        sid = it.get("source_id", "")
        if "::" in sid:
            base = sid.split("::")[0]
        else:
            base = sid
        country = None
        metrics = it.get("metrics") or {}
        country = metrics.get("country")
        s = base_map.setdefault(base, set())
        if country:
            s.add(country)
        else:
            # unknown, mark as unspecified
            s.add(None)

    out = []
    for it in lst:
        sid = it.get("source_id", "")
        base = sid.split("::")[0] if "::" in sid else sid
        metrics = it.get("metrics") or {}
        country = metrics.get("country")
        # if country present, keep as-is
        if country:
            out.append(it)
        else:
            # create both US and IN variants
            v_us = make_variant(it, "US")
            v_in = make_variant(it, "IN")
            out.extend([v_us, v_in])
            continue

        # ensure both regions exist; if missing, create
        have = base_map.get(base, set())
        out.append(it)
        if "US" not in have:
            out.append(make_variant(it, "US"))
            have.add("US")
        if "IN" not in have:
            out.append(make_variant(it, "IN"))
            have.add("IN")

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
            print(f"Processed {key}: {len(orig)} -> {len(new)} entries")

    if changed:
        # update top-level timestamp
        resp["updated_at"] = datetime.utcnow().isoformat() + "Z"
        write(resp)
        print("response.json updated with per-region duplicates")
    else:
        print("No youtube/discourse keys found; nothing changed")

if __name__ == '__main__':
    main()
