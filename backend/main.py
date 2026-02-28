from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import get_backend_cors_origins
from db import get_supabase
from services.enrich import enrich_stock
from services.events import SortOption, list_events
from services.filter import run_filter
from services.ingest import run_ingest
from services.mapping import run_mapping
from services.report import generate_signal_report
from services.reports import (
    create_report,
    delete_report,
    generate_report_content,
    get_report,
    list_reports,
)
from services.stocks import create_stock, delete_stock, get_stock, list_stocks

import logging
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
EUROPE_TZ = ZoneInfo("Europe/Berlin")

def run_pipeline_job():
    logger.info("Scheduler: starting pipeline run")
    try:
        run_ingest()
        logger.info("Scheduler: ingest done")
    except Exception as e:
        logger.error("Scheduler: ingest failed: %s", e)
        return
    try:
        run_filter()
        logger.info("Scheduler: filter done")
    except Exception as e:
        logger.error("Scheduler: filter failed: %s", e)
        return
    try:
        run_mapping()
        logger.info("Scheduler: mapping done")
    except Exception as e:
        logger.error("Scheduler: mapping failed: %s", e)
        return
    logger.info("Scheduler: pipeline run complete")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        run_pipeline_job,
        CronTrigger(hour=12, minute=0, timezone=EUROPE_TZ),
    )
    scheduler.start()
    logger.info("Scheduler started — pipeline daily at 12:00 Europe/Berlin")
    yield
    scheduler.shutdown()

app = FastAPI(title="BIT Capital Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_backend_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateStockRequest(BaseModel):
    name: str = Field(min_length=1)


class CreateReportRequest(BaseModel):
    name: str = Field(min_length=1)
    stock_ids: List[str]
    report_type: Literal["combined", "single_stock", "macro", "sector"] = "combined"


class PipelineRunRequest(BaseModel):
    run_ingest: bool = True
    run_filter: bool = True
    run_mapping: bool = True
    stock_id: Optional[str] = None


def _parse_csv(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/stocks")
def get_stocks() -> List[Dict[str, Any]]:
    supabase = get_supabase()
    return list_stocks(supabase)


@app.post("/stocks")
def post_stock(payload: CreateStockRequest) -> Dict[str, Any]:
    supabase = get_supabase()
    return create_stock(supabase, payload.name.strip())


@app.delete("/stocks/{stock_id}")
def remove_stock(stock_id: str) -> Dict[str, str]:
    supabase = get_supabase()
    delete_stock(supabase, stock_id)
    return {"status": "ok"}


@app.post("/stocks/{stock_id}/enrich")
async def post_enrich_stock(stock_id: str) -> Dict[str, Any]:
    supabase = get_supabase()
    existing = get_stock(supabase, stock_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Stock not found")

    try:
        return await enrich_stock(supabase, stock_id)
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(err)) from err


@app.get("/events")
def get_events(
    search: Optional[str] = None,
    active: Optional[bool] = None,
    prefilter_passed: Optional[bool] = None,
    impact_types: Optional[str] = None,
    stock_ids: Optional[str] = None,
    sort: SortOption = "recent",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    supabase = get_supabase()
    return list_events(
        supabase,
        search=search,
        active=active,
        prefilter_passed=prefilter_passed,
        impact_types=_parse_csv(impact_types),
        stock_ids=_parse_csv(stock_ids),
        sort=sort,
        page=page,
        page_size=page_size,
    )


@app.post("/pipeline/run")
def post_pipeline(payload: PipelineRunRequest) -> Dict[str, Any]:
    try:
        if payload.run_ingest:
            run_ingest()
        if payload.run_filter:
            run_filter()
        if payload.run_mapping:
            run_mapping(stock_id=payload.stock_id)
        return {
            "status": "ok",
            "ingest": payload.run_ingest,
            "filter": payload.run_filter,
            "mapping": payload.run_mapping,
        }
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(err)) from err


@app.post("/reports/generate")
def post_generate_report() -> Dict[str, Any]:
    return generate_signal_report()


@app.get("/reports")
def get_reports() -> List[Dict[str, Any]]:
    supabase = get_supabase()
    return list_reports(supabase)


@app.post("/reports")
def post_report(payload: CreateReportRequest) -> Dict[str, Any]:
    supabase = get_supabase()
    return create_report(
        supabase,
        payload.name.strip(),
        payload.stock_ids,
        payload.report_type,
    )


@app.delete("/reports/{report_id}")
def remove_report(report_id: str) -> Dict[str, str]:
    supabase = get_supabase()
    delete_report(supabase, report_id)
    return {"status": "ok"}


@app.post("/reports/{report_id}/generate")
async def post_generate_report_for_id(report_id: str) -> Dict[str, Any]:
    supabase = get_supabase()
    existing = get_report(supabase, report_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        return await generate_report_content(supabase, report_id)
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(err)) from err
