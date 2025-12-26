from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Float, Integer, JSON, TIMESTAMP, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from app.base import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True)
    workflow = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False, unique=True)
    source_url = Column(String)
    keywords = Column(JSON)
    country = Column(String, index=True)
    popularity_metrics = Column(JSONB)
    popularity_score = Column(Float, index=True)
    score_components = Column(JSONB)
    last_updated = Column(TIMESTAMP)
    evidence_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class EvidenceItem(BaseModel):
    platform: str
    source_id: str
    title: Optional[str]
    metrics: Dict[str, Any]
    scrape_ts: Optional[str]


class WorkflowOut(BaseModel):
    workflow: str
    platform: str
    source_id: str
    source_url: Optional[str]
    keywords: Optional[List[str]]
    country: Optional[str]
    popularity_metrics: Optional[Dict[str, Any]]
    popularity_score: Optional[float]
    score_components: Optional[Dict[str, Any]]
    last_updated: Optional[str]

    class Config:
        from_attributes = True
