"""
Dev helper: resume or complete event-stock matching for stalled stocks.

Stalled = stocks with status in (enriching, failed), or stocks that have
candidates (from event_filtering) with no event_stock_mappings row or
affects IS NULL.

Usage:
  python scripts/resume_stock_matching.py [--stock-id UUID] [--dry-run]
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# Allow importing from backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from services.matching import classify_with_llm_async

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run_matching(
    supabase, stock_id: str, stock: dict, candidates: list[dict]
) -> int:
    """Process candidates, upsert event_stock_mappings with affects. Returns processed count."""
    semaphore = asyncio.Semaphore(5)
    progress_lock = asyncio.Lock()
    processed = 0

    async def process_one(row: dict) -> None:
        nonlocal processed
        event_id = row["event_id"]
        event_impact_type = row["impact_type"]

        event_resp, markets_resp = await asyncio.gather(
            asyncio.to_thread(
                lambda eid=event_id: supabase.table("polymarket_events")
                .select("id, title, description")
                .eq("id", eid)
                .single()
                .execute()
            ),
            asyncio.to_thread(
                lambda eid=event_id: supabase.table("polymarket_markets")
                .select("question")
                .eq("event_id", eid)
                .execute()
            ),
        )
        event = event_resp.data or {}
        market_questions = [
            str(m.get("question"))
            for m in (markets_resp.data or [])
            if m.get("question")
        ]

        matches, reasoning = await classify_with_llm_async(
            event_impact_type,
            str(stock.get("name") or ""),
            stock.get("ticker"),
            stock.get("sector"),
            str(event.get("title") or ""),
            event.get("description"),
            market_questions,
            semaphore,
        )

        await asyncio.to_thread(
            lambda: supabase.table("event_stock_mappings")
            .upsert(
                {
                    "event_id": event_id,
                    "stock_id": stock_id,
                    "affects": matches,
                    "reasoning": reasoning,
                    "relevance_score": 0.8 if matches else None,
                },
                on_conflict="event_id,stock_id",
            )
            .execute()
        )
        async with progress_lock:
            processed += 1
            current = processed
        if current % 10 == 0:
            logger.info("  Processed %d/%d", current, len(candidates))

    results = await asyncio.gather(
        *[process_one(row) for row in candidates],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            logger.warning("  Error: %s", r)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resume event-stock matching for stalled stocks"
    )
    parser.add_argument("--stock-id", type=str, help="Process only this stock UUID")
    parser.add_argument("--dry-run", action="store_true", help="Log only, do not write")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)

    supabase = create_client(url, key)

    # Find stalled stocks: status enriching/failed
    query = supabase.table("stocks").select("id, name, ticker, sector, impact_types")
    query = query.in_("status", ["enriching", "failed"])
    if args.stock_id:
        query = query.eq("id", args.stock_id)
    stocks_resp = query.execute()
    stalled = stocks_resp.data or []

    if not stalled:
        logger.info("No stalled stocks (status enriching/failed) found")
        return

    logger.info("Found %d stalled stock(s)", len(stalled))

    for stock in stalled:
        stock_id = str(stock["id"])
        impact_types = stock.get("impact_types") or []
        if not isinstance(impact_types, list):
            impact_types = []
        if not impact_types:
            logger.warning("Stock %s (%s) has no impact_types, skipping", stock_id, stock.get("name"))
            continue

        ef_resp = supabase.table("event_filtering").select("event_id, impact_type").eq(
            "relevant", True
        ).in_("impact_type", impact_types).execute()
        raw_candidates = ef_resp.data or []

        existing_resp = (
            supabase.table("event_stock_mappings")
            .select("event_id")
            .eq("stock_id", stock_id)
            .not_.is_("affects", "null")
            .execute()
        )
        done_ids = {r["event_id"] for r in (existing_resp.data or [])}
        candidates = [c for c in raw_candidates if c["event_id"] not in done_ids]

        if not candidates:
            logger.info(
                "Stock %s (%s): all %d candidates already processed, marking ready",
                stock_id,
                stock.get("name"),
                len(raw_candidates),
            )
            if not args.dry_run:
                supabase.table("stocks").update(
                    {"status": "ready", "enrich_progress": None}
                ).eq("id", stock_id).execute()
            continue

        logger.info(
            "Stock %s (%s): processing %d/%d candidates",
            stock_id,
            stock.get("name"),
            len(candidates),
            len(raw_candidates),
        )
        if args.dry_run:
            logger.info("  [dry-run] would process %d candidates", len(candidates))
            continue

        n = asyncio.run(run_matching(supabase, stock_id, stock, candidates))
        logger.info("  Processed %d candidates", n)

        supabase.table("stocks").update(
            {"status": "ready", "enrich_progress": None}
        ).eq("id", stock_id).execute()
        logger.info("  Marked stock %s as ready", stock_id)

    logger.info("Done")


if __name__ == "__main__":
    main()
