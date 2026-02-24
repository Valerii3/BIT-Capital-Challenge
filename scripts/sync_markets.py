"""
Sync active, non-closed Polymarket markets from Gamma API to Supabase.
Scheduler-agnostic: run via cron or GitHub Actions.
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


def parse_ts(value: Any) -> str | None:
    """Parse ISO timestamp to ISO string for timestamptz; return None if missing/invalid."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def row_from_gamma(m: dict[str, Any], first_seen_at: str | None) -> dict[str, Any]:
    """Map one Gamma market object to polymarket_markets row (snake_case)."""
    condition_id = m.get("conditionId")
    if not condition_id:
        return None
    return {
        "condition_id": str(condition_id),
        "gamma_id": str(m["id"]) if m.get("id") is not None else None,
        "question": m.get("question"),
        "market_description": m.get("description"),
        "outcomes": m.get("outcomes"),
        "outcome_prices": m.get("outcomePrices"),
        "active": m.get("active"),
        "start_date_iso": parse_ts(m.get("startDateIso") or m.get("startDate")),
        "end_date_iso": parse_ts(m.get("endDateIso") or m.get("endDate")),
        "volume_num": m.get("volumeNum"),
        "liquidity_num": m.get("liquidityNum"),
        "category": m.get("category"),
        "first_seen_at": first_seen_at or datetime.now(tz=timezone.utc).isoformat(),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)

    supabase: Client = create_client(url, key)

    # Create sync run
    run = (
        supabase.table("sync_runs")
        .insert(
            {
                "run_status": "running",
                "markets_fetched": 0,
                "markets_upserted": 0,
            }
        )
        .execute()
    )
    if not run.data or len(run.data) == 0:
        logger.error("Failed to create sync_runs row")
        raise SystemExit(1)
    run_id = run.data[0]["id"]
    logger.info("Created sync run id=%s", run_id)

    try:
        # Existing condition_id -> first_seen_at so we preserve on upsert
        existing = (
            supabase.table("polymarket_markets")
            .select("condition_id, first_seen_at")
            .execute()
        )
        first_seen_map = {}
        if existing.data:
            for r in existing.data:
                first_seen_map[r["condition_id"]] = r.get("first_seen_at")

        all_markets: list[dict[str, Any]] = []
        offset = 0

        with httpx.Client(timeout=30.0) as client:
            while True:
                resp = client.get(
                    f"{GAMMA_BASE}/markets",
                    params={
                        "closed": "false",
                        "active": "true",
                        "limit": PAGE_LIMIT,
                        "offset": offset,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    logger.warning("Unexpected response shape: %s", type(data))
                    break
                if len(data) == 0:
                    break
                logger.info("Fetched page offset=%d count=%d", offset, len(data))
                all_markets.extend(data)
                offset += PAGE_LIMIT
                if len(data) < PAGE_LIMIT:
                    break
                time.sleep(DELAY_BETWEEN_PAGES_S)

        markets_fetched = len(all_markets)
        logger.info("Total markets fetched: %d", markets_fetched)

        rows = []
        for m in all_markets:
            cid = m.get("conditionId")
            first_seen = first_seen_map.get(str(cid)) if cid else None
            row = row_from_gamma(m, first_seen)
            if row:
                rows.append(row)

        if rows:
            # Upsert in chunks to avoid huge payloads
            chunk_size = 100
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i : i + chunk_size]
                supabase.table("polymarket_markets").upsert(
                    chunk,
                    on_conflict="condition_id",
                ).execute()
            markets_upserted = len(rows)
        else:
            markets_upserted = 0

        logger.info("Markets upserted: %d", markets_upserted)

        supabase.table("sync_runs").update(
            {
                "run_status": "success",
                "finished_at": datetime.now(tz=timezone.utc).isoformat(),
                "markets_fetched": markets_fetched,
                "markets_upserted": markets_upserted,
                "error": None,
            }
        ).eq("id", run_id).execute()

        logger.info("Sync completed successfully")
    except Exception as e:
        logger.exception("Sync failed: %s", e)
        supabase.table("sync_runs").update(
            {
                "status": "failed",
                "finished_at": datetime.now(tz=timezone.utc).isoformat(),
                "error": str(e),
            }
        ).eq("id", run_id).execute()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
