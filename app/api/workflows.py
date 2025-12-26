from fastapi import APIRouter, Query, Response
from typing import List, Optional
from app.models import WorkflowOut, Workflow as WorkflowORM
import os
import json
import logging
from app.db import AsyncSession
from sqlalchemy import select, desc, func
from fastapi import HTTPException

router = APIRouter()
logger = logging.getLogger("app.api.workflows")


def _load_fallback(limit: int = 10, offset: int = 0):
    # Prefer canonical aggregated file if present
    data_file = os.path.join(os.getcwd(), "data", "canonical_workflows.json")
    if not os.path.exists(data_file):
        data_file = os.path.join(os.getcwd(), "data", "workflows.json")
    if not os.path.exists(data_file):
        return []
    with open(data_file, "r", encoding="utf-8") as f:
        items = json.load(f)
    out = []
    for it in items[offset: offset + limit]:
        out.append({
            "workflow": it.get("workflow") or it.get("title") or it.get("keyword") or "",
            "platform": it.get("platform"),
            "source_id": it.get("source_id"),
            "source_url": it.get("source_url") or it.get("keyword"),
            "keywords": it.get("keywords") or [],
            "country": it.get("country") or it.get("metrics", {}).get("country") or None,
            "popularity_metrics": it.get("popularity_metrics") or it.get("metrics"),
            "popularity_score": it.get("popularity_score"),
            "score_components": it.get("score_components"),
            "last_updated": it.get("last_updated") or it.get("scrape_ts"),
        })
    return out


@router.get("", response_model=List[WorkflowOut])
async def list_workflows(q: Optional[str] = None, platform: Optional[str] = None, country: Optional[str] = None, limit: int = Query(10, ge=1, le=100), page: int = Query(1, ge=1)):
    """List workflows. Attempts DB then falls back to JSON file."""
    try:
        async with AsyncSession() as session:
            stmt = select(WorkflowORM)
            if platform:
                stmt = stmt.where(WorkflowORM.platform == platform)
            if country:
                stmt = stmt.where(WorkflowORM.country == country)
            if q:
                stmt = stmt.where(WorkflowORM.workflow.ilike(f"%{q}%"))
            offset = (page - 1) * limit
            stmt = stmt.order_by(desc(WorkflowORM.popularity_score)).offset(offset).limit(limit)
            res = await session.execute(stmt)
            rows = res.scalars().all()
            # total count for pagination header
            try:
                count_stmt = select(func.count()).select_from(WorkflowORM)
                if platform:
                    count_stmt = count_stmt.where(WorkflowORM.platform == platform)
                if country:
                    count_stmt = count_stmt.where(WorkflowORM.country == country)
                if q:
                    count_stmt = count_stmt.where(WorkflowORM.workflow.ilike(f"%{q}%"))
                total_res = await session.execute(count_stmt)
                total = total_res.scalar_one()
            except Exception:
                total = None

            out = []
            for r in rows:
                # Pydantic v2: use model_validate with from_attributes enabled
                out.append(WorkflowOut.model_validate(r))

            # attach total count header if available
            if total is not None:
                return Response(content=json.dumps([o.model_dump() for o in out]), media_type="application/json", headers={"X-Total-Count": str(total)})
            return out
    except Exception as e:
        logger.warning("DB query failed, using fallback JSON: %s", e)
        return _load_fallback(limit=limit, offset=(page - 1) * limit)


@router.get("/top", response_model=List[WorkflowOut])
async def top_workflows(platform: Optional[str] = None, country: Optional[str] = None, limit: int = Query(10, ge=1, le=100), page: int = Query(1, ge=1)):
    """Return top workflows (DB-backed with fallback)."""
    return await list_workflows(None, platform, country, limit, page)


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(workflow_id: str):
    """Get a workflow by `id` or `source_id`."""
    try:
        async with AsyncSession() as session:
            stmt = select(WorkflowORM).where((WorkflowORM.id == workflow_id) | (WorkflowORM.source_id == workflow_id))
            res = await session.execute(stmt)
            row = res.scalars().first()
            if not row:
                raise HTTPException(status_code=404, detail="workflow not found")
            return WorkflowOut.model_validate(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("DB get failed, using fallback JSON: %s", e)
        # fallback search in canonical JSON
        items = _load_fallback(limit=1000)
        for it in items:
            if it.get("source_id") == workflow_id or it.get("id") == workflow_id:
                return WorkflowOut.model_validate(it)
        raise HTTPException(status_code=404, detail="workflow not found")
