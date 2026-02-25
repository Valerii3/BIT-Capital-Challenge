"""
Sync active Polymarket events (volume >= 1k) and their markets from
Gamma API to Supabase. Marks rows not seen in this run as inactive.

Scheduler-agnostic: run via cron, GitHub Actions, etc.
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
PAGE_LIMIT = 100
DELAY_BETWEEN_PAGES_S = 0.5
MIN_VOLUME = 1000


def parse_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def event_row(ev: dict[str, Any], run_ts: str) -> dict[str, Any]:
    return {
        "id": str(ev["id"]),
        "title": ev.get("title") or "",
        "description": ev.get("description"),
        "start_date": parse_ts(ev.get("startDate")),
        "end_date": parse_ts(ev.get("endDate")),
        "active": True,
        "liquidity": ev.get("liquidity"),
        "volume": ev.get("volume"),
        "updated_at": run_ts,
    }


def market_row(m: dict[str, Any], event_id: str, run_ts: str) -> dict[str, Any] | None:
    mid = m.get("id")
    if not mid:
        return None
    return {
        "id": str(mid),
        "event_id": event_id,
        "question": m.get("question"),
        "outcomes": m.get("outcomes"),
        "outcome_prices": m.get("outcomePrices"),
        "active": True,
        "volume_num": m.get("volumeNum"),
        "liquidity_num": m.get("liquidityNum"),
        "updated_at": run_ts,
    }


def paginate_events(client: httpx.Client) -> list[dict[str, Any]]:
    all_events: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = client.get(
            f"{GAMMA_BASE}/events",
            params={
                "closed": "false",
                "active": "true",
                "volume_min": MIN_VOLUME,
                "limit": PAGE_LIMIT,
                "offset": offset,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or len(data) == 0:
            break
        logger.info("Fetched events page offset=%d count=%d", offset, len(data))
        all_events.extend(data)
        if len(data) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        time.sleep(DELAY_BETWEEN_PAGES_S)
    return all_events


def upsert_chunks(supabase: Client, table: str, rows: list[dict], chunk_size: int = 100) -> None:
    for i in range(0, len(rows), chunk_size):
        supabase.table(table).upsert(rows[i : i + chunk_size]).execute()


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)

    supabase: Client = create_client(url, key)
    run_ts = datetime.now(tz=timezone.utc).isoformat()

    run = (
        supabase.table("sync_runs")
        .insert({"run_status": "running"})
        .execute()
    )
    if not run.data:
        logger.error("Failed to create sync_runs row")
        raise SystemExit(1)
    run_id = run.data[0]["id"]
    logger.info("Sync run id=%s  run_ts=%s", run_id, run_ts)

    try:
        # Load existing IDs so we can count inserts vs updates
        existing_event_ids: set[str] = set()
        resp = supabase.table("polymarket_events").select("id").execute()
        if resp.data:
            existing_event_ids = {r["id"] for r in resp.data}

        existing_market_ids: set[str] = set()
        resp = supabase.table("polymarket_markets").select("id").execute()
        if resp.data:
            existing_market_ids = {r["id"] for r in resp.data}

        # Fetch from Gamma
        with httpx.Client(timeout=30.0) as client:
            all_events = paginate_events(client)

        logger.info("Total events fetched: %d", len(all_events))

        # Build rows
        ev_rows: list[dict[str, Any]] = []
        mk_rows: list[dict[str, Any]] = []
        for ev in all_events:
            er = event_row(ev, run_ts)
            ev_rows.append(er)
            for m in ev.get("markets") or []:
                mr = market_row(m, er["id"], run_ts)
                if mr:
                    mk_rows.append(mr)

        # Count inserts vs updates
        events_inserted = sum(1 for r in ev_rows if r["id"] not in existing_event_ids)
        events_updated = len(ev_rows) - events_inserted
        markets_inserted = sum(1 for r in mk_rows if r["id"] not in existing_market_ids)
        markets_updated = len(mk_rows) - markets_inserted

        logger.info(
            "Events: %d inserted, %d updated | Markets: %d inserted, %d updated",
            events_inserted, events_updated, markets_inserted, markets_updated,
        )

        # Upsert events first (markets FK depends on them)
        if ev_rows:
            upsert_chunks(supabase, "polymarket_events", ev_rows)
        if mk_rows:
            upsert_chunks(supabase, "polymarket_markets", mk_rows)

        # Mark stale rows as inactive
        stale_markets = (
            supabase.table("polymarket_markets")
            .update({"active": False})
            .eq("active", True)
            .lt("updated_at", run_ts)
            .execute()
        )
        markets_deactivated = len(stale_markets.data) if stale_markets.data else 0

        stale_events = (
            supabase.table("polymarket_events")
            .update({"active": False})
            .eq("active", True)
            .lt("updated_at", run_ts)
            .execute()
        )
        events_deactivated = len(stale_events.data) if stale_events.data else 0

        logger.info(
            "Deactivated: %d events, %d markets", events_deactivated, markets_deactivated,
        )

        supabase.table("sync_runs").update(
            {
                "run_status": "success",
                "finished_at": datetime.now(tz=timezone.utc).isoformat(),
                "events_inserted": events_inserted,
                "events_updated": events_updated,
                "markets_inserted": markets_inserted,
                "markets_updated": markets_updated,
                "events_deactivated": events_deactivated,
                "markets_deactivated": markets_deactivated,
                "error": None,
            }
        ).eq("id", run_id).execute()

        logger.info("Sync completed successfully")

    except Exception as e:
        logger.exception("Sync failed: %s", e)
        supabase.table("sync_runs").update(
            {
                "run_status": "failed",
                "finished_at": datetime.now(tz=timezone.utc).isoformat(),
                "error": str(e),
            }
        ).eq("id", run_id).execute()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
