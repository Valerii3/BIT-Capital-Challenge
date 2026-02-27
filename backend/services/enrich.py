from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Dict

from google import genai
from google.genai import types
from supabase import Client

from services.matching import classify_with_llm_async

logger = logging.getLogger(__name__)

MAX_RETRIES = 4
RETRY_BACKOFF_BASE_S = 2
VALID_IMPACT_TYPES = {"macro", "sector", "crypto_equity", "single_stock"}


def _extract_text(resp: Any) -> str:
    text = getattr(resp, "text", None) or ""
    if text:
        return text
    candidates = getattr(resp, "candidates", None) or []
    if candidates:
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        if parts:
            return getattr(parts[0], "text", "") or ""
    return ""


def enrich_description(company_name: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=api_key)
    prompt = f"""
You are classifying a public company for an equity research workflow used to map prediction-market events to stocks.

Company: {company_name}

Return ONLY valid JSON with:
{{
  "ticker": "string",
  "short_description": "1-2 sentences",
  "sector": "string",
  "impact_types": ["macro" | "sector" | "crypto_equity" | "single_stock", one of these],
}}

Definitions:
- "macro": use for nearly all public companies. Means the stock can be materially affected by rates, inflation, tariffs, fiscal policy, regulation, labor, energy, or broad risk appetite.
- "sector": use when the company has meaningful exposure to sector-specific themes (e.g. AI infrastructure, semis, cloud, fintech, digital payments, insurance tech, crypto infrastructure).
- "crypto_equity": use ONLY if the company has DIRECT and MATERIAL economic exposure to crypto. Examples:
  * exchange / brokerage / custody / wallet / tokenization / stablecoin / payments infrastructure
  * bitcoin miner / validator / treasury company
  * company whose revenue, assets, balance sheet, or core product is directly tied to crypto activity
  Do NOT use "crypto_equity" for indirect exposure only.
  Do NOT use it just because the firm sells chips, servers, cloud, or power to customers who may also serve crypto.
  Do NOT use it for generic "risk-on/risk-off" correlation with bitcoin.
- "single_stock": use only when company-specific events, management actions, earnings, M&A, product launches, legal rulings, or competitor-specific outcomes could directly matter.
Return ONLY valid JSON, no markdown fences.
"""

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
            text = _extract_text(resp)
            parsed = json.loads(text)
            impact_types = [
                str(value)
                for value in (parsed.get("impact_types") or [])
                if isinstance(value, str) and value in VALID_IMPACT_TYPES
            ]
            return {
                "ticker": (str(parsed.get("ticker") or "").strip() or None),
                "short_description": (str(parsed.get("short_description") or "").strip() or None),
                "sector": (str(parsed.get("sector") or "").strip() or None),
                "impact_types": impact_types,
            }
        except Exception as err:  # noqa: BLE001
            msg = str(err)
            retryable = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if retryable and attempt < MAX_RETRIES:
                wait = min(RETRY_BACKOFF_BASE_S**attempt, 16) + random.random()
                time.sleep(wait)
                continue
            raise

    raise RuntimeError("Gemini retries exhausted")


def _stock_error_payload(message: str) -> Dict[str, Any]:
    return {
        "status": "failed",
        "enrich_progress": {
            "step": "failed",
            "error": message[:240],
        },
    }


async def enrich_stock(supabase: Client, stock_id: str) -> Dict[str, Any]:
    stock_resp = await asyncio.to_thread(
        lambda: supabase.table("stocks").select("*").eq("id", stock_id).single().execute()
    )
    stock = stock_resp.data
    if not stock:
        raise ValueError("Stock not found")

    if stock.get("status") == "ready":
        return stock

    await asyncio.to_thread(
        lambda: supabase.table("stocks").update(
            {
                "status": "enriching",
                "enrich_progress": {"step": "description"},
            }
        ).eq("id", stock_id).execute()
    )

    try:
        enriched = await asyncio.to_thread(
            enrich_description, str(stock.get("name") or "")
        )

        await asyncio.to_thread(
            lambda: supabase.table("stocks").update(
                {
                    "ticker": enriched["ticker"],
                    "short_description": enriched["short_description"],
                    "sector": enriched["sector"],
                    "impact_types": enriched["impact_types"],
                    "status": "enriching",
                    "enrich_progress": {"step": "filtering_markets", "current": 0, "total": 0},
                }
            ).eq("id", stock_id).execute()
        )

        impact_types = list(enriched["impact_types"])
        if not impact_types:
            await asyncio.to_thread(
                lambda: supabase.table("stocks").update(
                    {"status": "ready", "enrich_progress": None}
                ).eq("id", stock_id).execute()
            )
            final_resp = await asyncio.to_thread(
                lambda: supabase.table("stocks").select("*").eq("id", stock_id).single().execute()
            )
            return final_resp.data

        ef_resp = await asyncio.to_thread(
            lambda: supabase.table("event_filtering")
            .select("event_id, impact_type")
            .eq("relevant", True)
            .in_("impact_type", impact_types)
            .execute()
        )
        raw_candidates = ef_resp.data or []

        # Skip already-processed candidates (have non-null affects)
        existing_resp = await asyncio.to_thread(
            lambda: supabase.table("event_stock_mappings")
            .select("event_id")
            .eq("stock_id", stock_id)
            .not_.is_("affects", "null")
            .execute()
        )
        done_event_ids = {r["event_id"] for r in (existing_resp.data or [])}
        candidates = [c for c in raw_candidates if c["event_id"] not in done_event_ids]
        total = len(candidates)

        await asyncio.to_thread(
            lambda: supabase.table("stocks").update(
                {
                    "enrich_progress": {
                        "step": "filtering_markets",
                        "current": 0,
                        "total": total,
                    }
                }
            ).eq("id", stock_id).execute()
        )

        # Concurrently process all candidates — max 5 simultaneous LLM calls
        semaphore = asyncio.Semaphore(5)
        progress_lock = asyncio.Lock()
        processed_count = 0

        async def process_candidate(row: dict) -> None:
            nonlocal processed_count
            event_id = row["event_id"]
            event_impact_type = row["impact_type"]

            # Fetch event and its market questions in parallel
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

            # All impact types go through the expert LLM (single_stock included)
            matches, reasoning = await classify_with_llm_async(
                event_impact_type,
                str(stock.get("name") or ""),
                enriched["ticker"],
                enriched["sector"],
                str(event.get("title") or ""),
                event.get("description"),
                market_questions,
                semaphore,
            )

            await asyncio.to_thread(
                lambda: supabase.table("event_stock_mappings").upsert(
                    {
                        "event_id": event_id,
                        "stock_id": stock_id,
                        "affects": matches,
                        "reasoning": reasoning,
                        "relevance_score": 0.8 if matches else None,
                    },
                    on_conflict="event_id,stock_id",
                ).execute()
            )

            async with progress_lock:
                processed_count += 1
                current = processed_count

            if current % 5 == 0 or current == total:
                await asyncio.to_thread(
                    lambda c=current: supabase.table("stocks").update(
                        {
                            "enrich_progress": {
                                "step": "filtering_markets",
                                "current": c,
                                "total": total,
                            }
                        }
                    ).eq("id", stock_id).execute()
                )

        results = await asyncio.gather(
            *[process_candidate(row) for row in candidates],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.warning("process_candidate error: %s", r)

        await asyncio.to_thread(
            lambda: supabase.table("stocks").update(
                {
                    "status": "ready",
                    "enrich_progress": None,
                }
            ).eq("id", stock_id).execute()
        )

        final_resp = await asyncio.to_thread(
            lambda: supabase.table("stocks").select("*").eq("id", stock_id).single().execute()
        )
        return final_resp.data
    except Exception as err:  # noqa: BLE001
        await asyncio.to_thread(
            lambda: supabase.table("stocks").update(
                _stock_error_payload(str(err))
            ).eq("id", stock_id).execute()
        )
        raise
