"""
Assign event_stock_mappings by matching events (from event_filtering) to stocks
based on impact_types: single_stock (regex), macro/sector/crypto_equity (LLM).
"""
import argparse
import json
import logging
import os
import re
import random
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MAX_RETRIES = 6
RETRY_BACKOFF_BASE_S = 2


def escape_regex(s: str) -> str:
    return re.escape(s)


def match_single_stock(
    stock_name: str,
    stock_ticker: str | None,
    event_title: str,
    event_description: str | None,
    market_questions: list[str],
) -> tuple[bool, str]:
    texts = [
        event_title or "",
        event_description or "",
        *market_questions,
    ]
    combined = " ".join(t for t in texts if t).lower()

    patterns = []
    if stock_name and stock_name.strip():
        patterns.append(escape_regex(stock_name.strip()))
    if stock_ticker and stock_ticker.strip():
        patterns.append(escape_regex(stock_ticker.strip()))

    if not patterns:
        return False, "No name or ticker to match"

    for p in patterns:
        if re.search(rf"\b{p}\b", combined, re.IGNORECASE):
            return True, f"Regex match: found in event/markets"

    return False, "No regex match for name or ticker"


def classify_with_llm(
    impact_type: str,
    stock_name: str,
    stock_ticker: str | None,
    stock_sector: str | None,
    event_title: str,
    event_description: str | None,
    market_questions: list[str],
) -> tuple[bool, str]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY / GOOGLE_API_KEY not set")
        return False, "API key not set"

    client = genai.Client(api_key=api_key)
    market_text = "\nMarket questions: " + " | ".join(market_questions) if market_questions else ""

    prompt = f"""You are judging whether a Polymarket event affects a specific public company.

Event (impact_type={impact_type}):
Title: {event_title}
Description: {event_description or "(none)"}{market_text}

Company: {stock_name}{f' ({stock_ticker})' if stock_ticker else ''}{f', sector: {stock_sector}' if stock_sector else ''}

Does this {impact_type} event materially affect this company? Answer with a JSON object:
{{ "affects": true/false, "reasoning": "one sentence" }}

Return ONLY valid JSON, no markdown fences."""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            text = getattr(resp, "text", None) or ""
            if not text and resp.candidates:
                text = resp.candidates[0].content.parts[0].text
            parsed = json.loads(text)
            return bool(parsed.get("affects", False)), str(parsed.get("reasoning", ""))
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = min(RETRY_BACKOFF_BASE_S**attempt, 32) + random.random()
                logger.warning(
                    "Attempt %d/%d rate-limited, retrying in %.1fs...",
                    attempt, MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue
            logger.error("LLM error: %s", msg[:160])
            return False, f"LLM error: {msg[:100]}"

    return False, "LLM retries exhausted"


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign event_stock_mappings")
    parser.add_argument("--stock-id", type=str, help="Process only this stock UUID")
    parser.add_argument("--dry-run", action="store_true", help="Log only, do not insert")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)

    supabase = create_client(url, key)

    stocks_resp = supabase.table("stocks").select("id, name, ticker, sector, impact_types").eq("is_active", True).execute()
    stocks = stocks_resp.data or []
    if args.stock_id:
        stocks = [s for s in stocks if str(s.get("id")) == args.stock_id]
        if not stocks:
            logger.error("Stock %s not found", args.stock_id)
            raise SystemExit(1)
    logger.info("Processing %d stocks", len(stocks))

    ef_resp = (
        supabase.table("event_filtering")
        .select("event_id, impact_type")
        .eq("relevant", True)
        .execute()
    )
    ef_rows = ef_resp.data or []
    event_ids = list({r["event_id"] for r in ef_rows})
    events_by_id: dict[str, list[dict]] = {}
    for r in ef_rows:
        eid = r["event_id"]
        if eid not in events_by_id:
            events_by_id[eid] = []
        events_by_id[eid].append(r)

    if not event_ids:
        logger.info("No relevant events in event_filtering")
        return

    pe_resp = supabase.table("polymarket_events").select("id, title, description").in_("id", event_ids).execute()
    events_data = {r["id"]: r for r in (pe_resp.data or [])}

    pm_resp = supabase.table("polymarket_markets").select("event_id, question").in_("event_id", event_ids).execute()
    markets_by_event: dict[str, list[str]] = {}
    for r in pm_resp.data or []:
        eid = r["event_id"]
        q = r.get("question")
        if q:
            if eid not in markets_by_event:
                markets_by_event[eid] = []
            markets_by_event[eid].append(str(q))

    inserted = 0
    for stock in stocks:
        stock_id = stock["id"]
        stock_name = stock.get("name") or ""
        stock_ticker = stock.get("ticker")
        stock_sector = stock.get("sector")
        impact_types = stock.get("impact_types") or []
        if not isinstance(impact_types, list):
            impact_types = []

        for eid, ef_list in events_by_id.items():
            for ef in ef_list:
                it = ef.get("impact_type")
                if it not in impact_types:
                    continue

                ev = events_data.get(eid, {})
                title = ev.get("title") or ""
                desc = ev.get("description")
                market_questions = markets_by_event.get(eid, [])

                if it == "single_stock":
                    matches, reasoning = match_single_stock(
                        stock_name, stock_ticker, title, desc, market_questions
                    )
                elif it in ("macro", "sector", "crypto_equity"):
                    matches, reasoning = classify_with_llm(
                        it, stock_name, stock_ticker, stock_sector,
                        title, desc, market_questions
                    )
                else:
                    continue

                if matches:
                    if not args.dry_run:
                        supabase.table("event_stock_mappings").upsert(
                            {
                                "event_id": eid,
                                "stock_id": stock_id,
                                "reasoning": reasoning,
                                "relevance_score": 0.8,
                            },
                            on_conflict="event_id,stock_id",
                        ).execute()
                    inserted += 1
                    logger.info("Matched %s -> %s (%s): %s", stock_name, title[:50], it, reasoning[:80])

    logger.info("Done — inserted %d mappings", inserted)


if __name__ == "__main__":
    main()
