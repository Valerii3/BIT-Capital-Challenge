from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types
from supabase import Client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Analyst system prompt — forces opinions, not summaries
# ---------------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """
You are a senior equity research analyst writing a market intelligence brief.

Your primary job is triage. Most prediction markets are noise.
Your value comes from identifying the small minority that genuinely matter, explaining WHY they
matter with a defensible causal mechanism, and silently discarding everything else.

═══════════════════════════════════════
TRIAGE RULES — apply before writing anything
═══════════════════════════════════════

INCLUDE a market only if it satisfies at least one of these hard criteria:
1. It directly and explicitly names the company in a way that has real fundamental consequence
   (earnings outcome, product launch, M&A, legal ruling, contract win/loss, management change).
2. It resolves a question with a CLEAR CAUSAL PATH to the company's revenue or competitive position —
   not sentiment, not "this is good for the sector", not a multiple re-rating story without a
   fundamental anchor.
3. The probability is in live-debate territory (40–60%) AND both resolution scenarios lead to
   materially different outcomes for the specific stock.
4. The consensus is >80% but you have a specific, articulable reason it is wrong or incomplete
   — not just a general view that markets can be wrong.

SKIP a market if any of the following apply:
- Purely thematic or sentiment-based; no causal mechanism to this company's fundamentals.
- It is a market-cap ranking or popularity contest not tied to a direct fundamental change.
- It is a near-certain outcome (>90%) with no interesting tail to analyse.
- Volume is below $100K and the question is not uniquely important.
- It duplicates a higher-quality market you are already including.
- Its resolution would not change the investment thesis within a 12-month horizon.

═══════════════════════════════════════
WRITING RULES — only for INCLUDED markets
═══════════════════════════════════════

- State what the current probability implies is the crowd's consensus.
- Give your directional view: do you agree or disagree, and what is the mechanism?
- Describe the stock implication in directional terms.
  Do NOT invent specific EPS, revenue percentage, or valuation multiple estimates
  unless they are directly supported by data in the brief. If the implication is
  sentiment-driven with no fundamental anchor, label it as such.
- If multiple markets in the same event track the same question at different dates,
  treat them as ONE analysis using the probability curve as the signal.
- Do NOT force a trade recommendation. Only add a monitoring implication if the evidence
  clearly warrants one.
- If the honest answer for a stock is "nothing here meets the bar", write that and stop.
  Do not pad.

Tone: analytical, measured. You can say "the market is underestimating X" but only if you
can state the mechanism. Avoid asserting precision you do not have.
"""


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def list_reports(supabase: Client) -> List[Dict[str, Any]]:
    resp = (
        supabase.table("reports")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def create_report(supabase: Client, name: str, stock_ids: List[str]) -> Dict[str, Any]:
    resp = supabase.table("reports").insert(
        {"name": name, "stock_ids": stock_ids, "status": "pending", "event_ids": []}
    ).execute()
    return (resp.data or [{}])[0]


def get_report(supabase: Client, report_id: str) -> Optional[Dict[str, Any]]:
    resp = (
        supabase.table("reports")
        .select("*")
        .eq("id", report_id)
        .single()
        .execute()
    )
    return resp.data


def delete_report(supabase: Client, report_id: str) -> None:
    supabase.table("reports").delete().eq("id", report_id).execute()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _parse_prices(outcomes_str: Optional[str], prices_str: Optional[str]) -> str:
    """Convert raw outcome/price JSON strings into a readable format."""
    try:
        outcomes = json.loads(outcomes_str or "[]")
        prices = json.loads(prices_str or "[]")
        if not outcomes or not prices:
            return "N/A"
        parts = []
        for outcome, price in zip(outcomes, prices):
            pct = round(float(price) * 100, 1)
            parts.append(f"{outcome}: {pct}%")
        return " | ".join(parts)
    except Exception:
        return "N/A"


def _build_prompt(stocks_data: List[Dict[str, Any]], report_date: str) -> str:
    """
    Builds the user-facing prompt with all stock + market data, then asks for
    a structured intelligence brief with genuine analyst opinions.
    """
    data_sections: List[str] = []

    for item in stocks_data:
        stock = item["stock"]
        events = item["events"]

        header = f"STOCK: {stock['name']}"
        if stock.get("ticker"):
            header += f" ({stock['ticker']})"
        if stock.get("sector"):
            header += f" | {stock['sector']}"

        lines = ["═" * 60, header]
        if stock.get("short_description"):
            lines.append(stock["short_description"])
        lines.append("")

        if not events:
            lines.append(
                "No active single-stock prediction markets found for this name."
            )
        else:
            lines.append("RELEVANT SINGLE-STOCK PREDICTION MARKETS:")
            lines.append("")
            for ev in events:
                lines.append(f"  Event: {ev['title']}")
                if ev.get("description"):
                    lines.append(f"  Context: {ev['description']}")
                lines.append("")
                for mkt in ev["markets"]:
                    q = mkt.get("question") or "?"
                    prices = _parse_prices(
                        mkt.get("outcomes"), mkt.get("outcome_prices")
                    )
                    vol = mkt.get("volume_num")
                    vol_str = f"${vol:,.0f}" if vol else "< $1K"
                    lines.append(f"    • Q: {q}")
                    lines.append(f"      Prices: {prices}  |  Volume: {vol_str}")
                lines.append("")

        data_sections.append("\n".join(lines))

    data_block = "\n\n".join(data_sections)

    prompt = f"""DATA FOR ANALYSIS ({report_date}):

{data_block}

{"═" * 60}

Apply the triage rules from your system instructions before writing anything.
Then produce the brief using only markets that cleared the INCLUDE bar.

# Morning Market Intelligence Brief — {report_date}

## Executive Summary
[1-2 sentences. State the strongest signal across the portfolio, or honestly note that
no high-conviction signals are present today. Do not pad this section.]

[For each stock — write a section ONLY if at least one market passed triage:]

## [Stock Name] ([Ticker])

[One paragraph per INCLUDED market. Each paragraph must cover:
  — what the probability says the crowd believes
  — your directional view and the specific mechanism behind it
  — the directional stock implication (no invented numbers)
Do not write a paragraph for markets you triaged as SKIP.
If no markets for this stock cleared the bar, write one sentence:
"No markets meet the inclusion threshold for [stock] at this time."]

## Live Debates
[Include this section ONLY if you have 40-60% markets where both resolutions lead to
materially different outcomes for the portfolio. For each: name the question, describe
both outcomes and their stock implications, state which side you think is underweighted
and why. If no such markets exist, omit this section entirely.]
"""

    return prompt


# ---------------------------------------------------------------------------
# Main async generation function
# ---------------------------------------------------------------------------

async def generate_report_content(supabase: Client, report_id: str) -> Dict[str, Any]:
    """
    1. Marks the report as "generating"
    2. For each stock in the report:
       a. Finds active events mapped with affects=True
       b. Filters to single_stock impact type only
       c. Fetches market data (question, prices, volume)
    3. Builds a structured analyst prompt and calls Gemini
    4. Saves the generated content, marks report "ready"
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    # Mark generating
    await asyncio.to_thread(
        lambda: supabase.table("reports")
        .update({"status": "generating"})
        .eq("id", report_id)
        .execute()
    )

    try:
        # Fetch report
        report_resp = await asyncio.to_thread(
            lambda: supabase.table("reports")
            .select("*")
            .eq("id", report_id)
            .single()
            .execute()
        )
        report = report_resp.data
        if not report:
            raise ValueError("Report not found")

        stock_ids: List[str] = report.get("stock_ids") or []
        report_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

        stocks_data: List[Dict[str, Any]] = []
        all_event_ids: List[str] = []  # collected across all stocks

        for stock_id in stock_ids:
            # Fetch stock details
            stock_resp = await asyncio.to_thread(
                lambda sid=stock_id: supabase.table("stocks")
                .select("*")
                .eq("id", sid)
                .single()
                .execute()
            )
            stock = stock_resp.data
            if not stock:
                logger.warning("Stock %s not found, skipping", stock_id)
                continue

            # Find events where this stock is affected (affects=True)
            mappings_resp = await asyncio.to_thread(
                lambda sid=stock_id: supabase.table("event_stock_mappings")
                .select("event_id")
                .eq("stock_id", sid)
                .eq("affects", True)
                .execute()
            )
            affected_event_ids = [
                r["event_id"] for r in (mappings_resp.data or [])
            ]

            if not affected_event_ids:
                stocks_data.append({"stock": stock, "events": []})
                continue

            # Fetch active events from that list
            events_resp = await asyncio.to_thread(
                lambda eids=affected_event_ids: supabase.table("polymarket_events")
                .select("id, title, description")
                .in_("id", eids)
                .eq("active", True)
                .execute()
            )
            active_events = events_resp.data or []
            active_event_ids = [e["id"] for e in active_events]

            if not active_event_ids:
                stocks_data.append({"stock": stock, "events": []})
                continue

            # Filter to single_stock impact type only
            ef_resp = await asyncio.to_thread(
                lambda aeids=active_event_ids: supabase.table("event_filtering")
                .select("event_id")
                .in_("event_id", aeids)
                .eq("impact_type", "single_stock")
                .execute()
            )
            single_stock_ids = {r["event_id"] for r in (ef_resp.data or [])}

            single_stock_events = [
                e for e in active_events if e["id"] in single_stock_ids
            ]

            # For each event, fetch markets ordered by volume desc
            events_with_markets: List[Dict[str, Any]] = []
            for event in single_stock_events:
                markets_resp = await asyncio.to_thread(
                    lambda eid=event["id"]: supabase.table("polymarket_markets")
                    .select("question, outcomes, outcome_prices, volume_num")
                    .eq("event_id", eid)
                    .order("volume_num", desc=True)
                    .execute()
                )
                events_with_markets.append(
                    {**event, "markets": markets_resp.data or []}
                )

            all_event_ids.extend(e["id"] for e in events_with_markets)
            stocks_data.append({"stock": stock, "events": events_with_markets})

        # Build prompt and call Gemini
        prompt = _build_prompt(stocks_data, report_date)
        logger.info(
            "Generating report %s for %d stocks, prompt length %d chars",
            report_id, len(stocks_data), len(prompt),
        )

        client = genai.Client(api_key=api_key)
        content = ""

        for attempt in range(1, 5):
            try:
                resp = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=REPORT_SYSTEM_PROMPT,
                        temperature=0.0,
                        max_output_tokens=8192,
                    ),
                )
                content = getattr(resp, "text", None) or ""
                if not content and getattr(resp, "candidates", None):
                    content = resp.candidates[0].content.parts[0].text or ""
                break
            except Exception as err:
                msg = str(err)
                if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and attempt < 4:
                    wait = min(2 ** attempt, 16) + random.random()
                    logger.warning("Gemini rate-limited, retrying in %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                raise

        # Deduplicate event ids (preserve order)
        seen: set[str] = set()
        unique_event_ids = [
            eid for eid in all_event_ids if not (eid in seen or seen.add(eid))  # type: ignore[func-returns-value]
        ]

        now_iso = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: supabase.table("reports")
            .update(
                {
                    "content": content,
                    "status": "ready",
                    "error": None,
                    "event_ids": unique_event_ids,
                    "updated_at": now_iso,
                }
            )
            .eq("id", report_id)
            .execute()
        )

        final_resp = await asyncio.to_thread(
            lambda: supabase.table("reports")
            .select("*")
            .eq("id", report_id)
            .single()
            .execute()
        )
        return final_resp.data

    except Exception as err:
        now_iso = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: supabase.table("reports")
            .update(
                {
                    "status": "failed",
                    "error": str(err)[:500],
                    "updated_at": now_iso,
                }
            )
            .eq("id", report_id)
            .execute()
        )
        raise
