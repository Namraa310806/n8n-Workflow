import json
from datetime import datetime
from pathlib import Path

RESP = Path("data") / "response.json"

def load():
    with RESP.open("r", encoding="utf-8") as f:
        return json.load(f)

def write(obj):
    with RESP.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def main():
    if not RESP.exists():
        print("response.json not found")
        return
    resp = load()
    note = {
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "summary": "Finalized dataset: YouTube and Discourse entries duplicated for US/IN; synthesized Google Trends added; canonical workflows regenerated and augmented with trends. DB upserts skipped in this environment (asyncpg missing).",
        "files": {
            "workflows": "data/workflows.json",
            "canonical": "data/canonical_workflows.json",
            "trends_synth": "data/trends_synth.json",
            "response": "data/response.json"
        }
    }
    resp["submission_note"] = note
    write(resp)
    print("Wrote submission_note into data/response.json")

if __name__ == '__main__':
    main()
