import json
import os
import random
import time
from typing import Any, Dict

from google import genai
from google.genai import types
from supabase import Client

from services.matching import classify_with_llm, match_single_stock

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
    prompt = (
        f'Given the company name "{company_name}", return a JSON object with:\n'
        '- "ticker": the stock ticker symbol (e.g. "NVDA")\n'
        '- "short_description": 1-2 sentence description of what the company does\n'
        '- "sector": the sector (e.g. "Technology", "Finance", "Healthcare")\n'
        '- "impact_types": array of impact types from ["macro", "sector", "crypto_equity", "single_stock"]\n\n'
        'Return ONLY valid JSON, no markdown fences.'
    )

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


def enrich_stock(supabase: Client, stock_id: str) -> Dict[str, Any]:
    stock_resp = (
        supabase.table("stocks")
        .select("*")
        .eq("id", stock_id)
        .single()
        .execute()
    )
    stock = stock_resp.data
    if not stock:
        raise ValueError("Stock not found")

    if stock.get("status") == "ready":
        return stock

    supabase.table("stocks").update(
        {
            "status": "enriching",
            "enrich_progress": {"step": "description"},
        }
    ).eq("id", stock_id).execute()

    try:
        enriched = enrich_description(str(stock.get("name") or ""))

        supabase.table("stocks").update(
            {
                "ticker": enriched["ticker"],
                "short_description": enriched["short_description"],
                "sector": enriched["sector"],
                "impact_types": enriched["impact_types"],
                "status": "enriching",
                "enrich_progress": {"step": "filtering_markets", "current": 0, "total": 0},
            }
        ).eq("id", stock_id).execute()

        impact_types = list(enriched["impact_types"])
        if not impact_types:
            supabase.table("stocks").update(
                {"status": "ready", "enrich_progress": None}
            ).eq("id", stock_id).execute()
            final_resp = supabase.table("stocks").select("*").eq("id", stock_id).single().execute()
            return final_resp.data

        ef_resp = (
            supabase.table("event_filtering")
            .select("event_id, impact_type")
            .eq("relevant", True)
            .in_("impact_type", impact_types)
            .execute()
        )
        candidates = ef_resp.data or []
        total = len(candidates)

        supabase.table("stocks").update(
            {
                "enrich_progress": {
                    "step": "filtering_markets",
                    "current": 0,
                    "total": total,
                }
            }
        ).eq("id", stock_id).execute()

        processed = 0
        for row in candidates:
            event_id = row["event_id"]
            impact_type = row["impact_type"]

            event_resp = (
                supabase.table("polymarket_events")
                .select("id, title, description")
                .eq("id", event_id)
                .single()
                .execute()
            )
            event = event_resp.data or {}

            markets_resp = (
                supabase.table("polymarket_markets")
                .select("question")
                .eq("event_id", event_id)
                .execute()
            )
            market_questions = [
                str(m.get("question"))
                for m in (markets_resp.data or [])
                if m.get("question")
            ]

            if impact_type == "single_stock":
                matches, reasoning = match_single_stock(
                    str(stock.get("name") or ""),
                    enriched["ticker"],
                    str(event.get("title") or ""),
                    event.get("description"),
                    market_questions,
                )
            else:
                matches, reasoning = classify_with_llm(
                    impact_type,
                    str(stock.get("name") or ""),
                    enriched["ticker"],
                    enriched["sector"],
                    str(event.get("title") or ""),
                    event.get("description"),
                    market_questions,
                )

            if matches:
                supabase.table("event_stock_mappings").upsert(
                    {
                        "event_id": event_id,
                        "stock_id": stock_id,
                        "reasoning": reasoning,
                        "relevance_score": 0.8,
                    },
                    on_conflict="event_id,stock_id",
                ).execute()

            processed += 1
            if processed % 5 == 0 or processed == total:
                supabase.table("stocks").update(
                    {
                        "enrich_progress": {
                            "step": "filtering_markets",
                            "current": processed,
                            "total": total,
                        }
                    }
                ).eq("id", stock_id).execute()

        supabase.table("stocks").update(
            {
                "status": "ready",
                "enrich_progress": None,
            }
        ).eq("id", stock_id).execute()

        final_resp = supabase.table("stocks").select("*").eq("id", stock_id).single().execute()
        return final_resp.data
    except Exception as err:  # noqa: BLE001
        supabase.table("stocks").update(
            _stock_error_payload(str(err))
        ).eq("id", stock_id).execute()
        raise
