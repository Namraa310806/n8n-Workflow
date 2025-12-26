import os
import json
import re
import uuid
import asyncio
from typing import List, Dict, Any, DefaultDict
from collections import defaultdict, Counter
from app.processing.score import aggregate_workflow
from datetime import datetime

from app.db import AsyncSession
from sqlalchemy import select
from app.models import Workflow as WorkflowORM

DATA_RAW = os.path.join(os.getcwd(), "data", "workflows.json")
DATA_CANON = os.path.join(os.getcwd(), "data", "canonical_workflows.json")


def normalize_title(t: str) -> str:
    if not t:
        return ""
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def group_evidence(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in items:
        title = it.get("title") or it.get("keyword") or ""
        key = normalize_title(title)
        if not key:
            # fallback to source_id
            key = it.get("source_id") or str(uuid.uuid4())
        groups[key].append(it)
    return groups


async def upsert_to_db(canonical_items: List[Dict[str, Any]]):
    # attempt to upsert into Postgres using SQLAlchemy core + PostgreSQL ON CONFLICT
    try:
        from app.db import engine
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        async with engine.begin() as conn:
            for item in canonical_items:
                row = {
                    "id": item.get("id") or str(uuid.uuid4()),
                    "workflow": item.get("workflow"),
                    "platform": item.get("platform"),
                    "source_id": item.get("source_id"),
                    "source_url": item.get("source_url"),
                    "keywords": item.get("keywords") or [],
                    "country": item.get("country"),
                    "popularity_metrics": item.get("popularity_metrics") or {},
                    "popularity_score": float(item.get("popularity_score") or 0.0),
                    "score_components": item.get("score_components") or {},
                    "last_updated": item.get("last_updated"),
                    "evidence_count": int(item.get("evidence_count") or 0),
                }

                # coerce last_updated to datetime if it's a string
                if isinstance(row.get("last_updated"), str):
                    try:
                        ts = row["last_updated"].rstrip("Z")
                        from datetime import datetime as _dt

                        row["last_updated"] = _dt.fromisoformat(ts)
                    except Exception:
                        row["last_updated"] = None

                table = WorkflowORM.__table__
                stmt = pg_insert(table).values(**row)
                update_cols = {
                    "workflow": stmt.excluded.workflow,
                    "platform": stmt.excluded.platform,
                    "source_url": stmt.excluded.source_url,
                    "keywords": stmt.excluded.keywords,
                    "country": stmt.excluded.country,
                    "popularity_metrics": stmt.excluded.popularity_metrics,
                    "popularity_score": stmt.excluded.popularity_score,
                    "score_components": stmt.excluded.score_components,
                    "last_updated": stmt.excluded.last_updated,
                    "evidence_count": stmt.excluded.evidence_count,
                }
                stmt = stmt.on_conflict_do_update(index_elements=["source_id"], set_=update_cols)
                await conn.execute(stmt)
        return True
    except Exception:
        import traceback
        traceback.print_exc()
        return False


async def run_ingest(write_json_fallback: bool = True):
    if not os.path.exists(DATA_RAW):
        print("No raw data found at", DATA_RAW)
        return
    with open(DATA_RAW, "r", encoding="utf-8") as f:
        raw = json.load(f)

    groups = group_evidence(raw)
    canonical: List[Dict[str, Any]] = []
    for key, evidence in groups.items():
        # choose display workflow name as the most common title in evidence
        titles = [e.get("title") or e.get("keyword") or "" for e in evidence]
        title_counts = Counter(titles)
        workflow_name = title_counts.most_common(1)[0][0] if titles else key

        # pick primary platform as the most frequent platform among evidence
        platforms = [e.get("platform") for e in evidence if e.get("platform")]
        platform = Counter(platforms).most_common(1)[0][0] if platforms else "mixed"

        # attempt to pick country by majority evidence if present
        countries = [e.get("metrics", {}).get("country") for e in evidence if e.get("metrics", {}).get("country")]
        country = None
        if countries:
            country = Counter(countries).most_common(1)[0][0]

        # aggregate metrics and compute score
        agg = aggregate_workflow(evidence)

        # compute aggregated totals across evidence (safe numeric coercion)
        total_views = 0
        total_likes = 0
        total_comments = 0
        for e in evidence:
            m = e.get("metrics") or {}
            try:
                total_views += int(m.get("views") or 0)
            except Exception:
                pass
            try:
                total_likes += int(m.get("likes") or 0)
            except Exception:
                pass
            # comments/replies field might be named differently
            try:
                total_comments += int(m.get("comments") or m.get("replies") or 0)
            except Exception:
                pass

        like_to_view_ratio = None
        comment_to_view_ratio = None
        if total_views > 0:
            like_to_view_ratio = total_likes / total_views
            comment_to_view_ratio = total_comments / total_views

        # pick a representative source_id/url
        rep = evidence[0]
        rep_metrics = rep.get("metrics") or {}

        # merge representative metrics with aggregated totals and computed ratios
        popularity_metrics = dict(rep_metrics)
        popularity_metrics.update({
            "views": total_views,
            "likes": total_likes,
            "comments": total_comments,
            "like_to_view_ratio": like_to_view_ratio,
            "comment_to_view_ratio": comment_to_view_ratio,
        })

        canonical_item = {
            "id": str(uuid.uuid4()),
            "workflow": workflow_name,
            "platform": platform,
            "source_id": rep.get("source_id"),
            "source_url": rep.get("source_url"),
            "keywords": [],
            "country": country,
            "evidence_count": len(evidence),
            "evidence": evidence,
            "popularity_metrics": popularity_metrics,
            "popularity_score": agg.get("popularity_score"),
            "score_components": agg.get("score_components"),
            "last_updated": datetime.utcnow(),
        }
        canonical.append(canonical_item)

    # try write to DB, else fallback to JSON
    ok = await upsert_to_db(canonical)
    if ok:
        print(f"Upserted {len(canonical)} canonical workflows to DB")
    else:
        if write_json_fallback:
            os.makedirs(os.path.dirname(DATA_CANON), exist_ok=True)

            # serialize datetimes to ISO strings when writing fallback JSON
            def _serialize(o):
                if isinstance(o, datetime):
                    return o.isoformat() + "Z"
                raise TypeError("Type not serializable")

            with open(DATA_CANON, "w", encoding="utf-8") as f:
                json.dump(canonical, f, ensure_ascii=False, indent=2, default=_serialize)
            print(f"Wrote {len(canonical)} canonical workflows to {DATA_CANON}")
        else:
            print("DB upsert failed and JSON fallback disabled")


if __name__ == "__main__":
    asyncio.run(run_ingest())
