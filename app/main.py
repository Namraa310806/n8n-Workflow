from fastapi import FastAPI
from app.api.workflows import router as workflows_router
from app.db import init_db
from app.logging_config import configure_logging

configure_logging()

app = FastAPI(title="n8n Popularity Intelligence")
app.include_router(workflows_router, prefix="/workflows", tags=["workflows"])


@app.on_event("startup")
async def on_startup():
    # create tables if needed
    try:
        await init_db()
    except Exception:
        # DB may not be available in local dev; handle gracefully
        pass


@app.get("/health")
async def health():
    return {"status": "ok"}
