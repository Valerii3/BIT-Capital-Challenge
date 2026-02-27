from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types
from supabase import Client

logger = logging.getLogger(__name__)

REPORT_TYPES = {"single_stock", "macro", "sector", "combined"}
DEFAULT_REPORT_TYPE = "combined"

# ---------------------------------------------------------------------------
# Single-stock report prompt
# ---------------------------------------------------------------------------

SINGLE_STOCK_REPORT_SYSTEM_PROMPT = """
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
# Macro report prompt
# ---------------------------------------------------------------------------

MACRO_REPORT_SYSTEM_PROMPT = """
You are a portfolio macro strategist writing a macro segment for a concentrated equity portfolio.

You are given a shortlist of macro prediction-market events that already map to stocks in the report.
Your task is to identify the most interesting macro markets right now and explain what they imply for
specific stocks and why.

Hard requirements:
- Prioritize events with clear transmission channels: rates, liquidity, inflation, fiscal, tariffs,
  regulation, labor, or energy.
- Prefer breadth across multiple stocks, but reject vague events with no concrete mechanism.
- Avoid generic summaries. Every selected event must contain a view and a causal argument.
- Use ONLY provided event/market/mapping data. No external facts.
- Be concise, opinionated, and falsifiable.

Return ONLY valid JSON matching this shape:
{
  "executive_summary": "2-4 sentences",
  "selected_events": [
    {
      "event_id": "string",
      "importance": "high|medium|low",
      "market_implication": "what current pricing implies",
      "why_interesting": "why this event is high-signal now",
      "portfolio_implication": "portfolio-level directional implication",
      "stock_implications": [
        {
          "stock_id": "string",
          "direction": "tailwind|headwind|two-sided",
          "reason": "one short causal sentence"
        }
      ],
      "watch_items": ["trigger 1", "trigger 2"]
    }
  ],
  "omitted_event_ids": ["string"]
}

Rules for selected_events:
- Choose at most 5 events.
- If no event is truly interesting, return an empty list.
- stock_implications must include only stocks from the provided report universe.
"""

SECTOR_REPORT_SYSTEM_PROMPT = """
You are a senior sector analyst writing a portfolio market-intelligence brief.

You are given pre-filtered sector events that already map to a stock, but you must still be strict.
Most events should be rejected unless the transmission path is concrete and material.

Hard inclusion rules:
- Include only if there is a direct channel to fundamentals within 6-12 months:
  demand, supply, pricing, regulation, competition, customer concentration, or capex cycle.
- Reject weak narratives, popularity contests, and long-dated optionality with no near-term path.
- Do not include an event just because it is "interesting" globally.

Output must be valid JSON:
{
  "executive_summary": "2-4 sentences",
  "stock_sections": [
    {
      "stock_id": "string",
      "stock_takeaway": "1-2 sentences",
      "events": [
        {
          "event_id": "string",
          "importance": "high|medium|low",
          "consensus": "what market pricing implies",
          "analyst_view": "your view + mechanism",
          "stock_implication": "directional implication for this stock",
          "watch_items": ["trigger 1", "trigger 2"]
        }
      ]
    }
  ],
  "omitted": [
    {
      "stock_id": "string",
      "event_id": "string",
      "reason": "why omitted"
    }
  ]
}

Rules:
- Use only provided stock/event ids.
- If a stock has no valid events, return that stock section with an empty "events" list.
- Keep claims grounded in provided data. No invented numbers.
"""

SECTOR_VERIFIER_SYSTEM_PROMPT = """
You are a strict sector catalyst gatekeeper for public equities.

Decide if a sector event should be included for ONE stock in a 6-12 month report.
Prefer false negatives over false positives.

Return valid JSON only:
{
  "include": true/false,
  "channel": "demand|supply|pricing|regulation|competition|customer|capex|other",
  "reason": "one concise sentence"
}

Include=true only when the transmission to this stock is concrete and material.
If transmission is generic sentiment, long-dated optionality, or weakly linked, return false.
"""


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def _normalize_report_type(value: Optional[str]) -> str:
    report_type = str(value or "").strip().lower()
    return report_type if report_type in REPORT_TYPES else DEFAULT_REPORT_TYPE



def list_reports(supabase: Client) -> List[Dict[str, Any]]:
    resp = (
        supabase.table("reports")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []



def create_report(
    supabase: Client,
    name: str,
    stock_ids: List[str],
    report_type: str = DEFAULT_REPORT_TYPE,
) -> Dict[str, Any]:
    resp = supabase.table("reports").insert(
        {
            "name": name,
            "stock_ids": stock_ids,
            "status": "pending",
            "event_ids": [],
            "report_type": _normalize_report_type(report_type),
        }
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
# Shared helpers
# ---------------------------------------------------------------------------


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



def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0



def _parse_json_array(raw: Optional[str]) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []



def _parse_prices(outcomes_str: Optional[str], prices_str: Optional[str]) -> str:
    try:
        outcomes = _parse_json_array(outcomes_str)
        prices = _parse_json_array(prices_str)
        if not outcomes or not prices:
            return "N/A"
        parts = []
        for outcome, price in zip(outcomes, prices):
            pct = round(_safe_float(price) * 100, 1)
            parts.append(f"{outcome}: {pct}%")
        return " | ".join(parts)
    except Exception:
        return "N/A"



def _market_debate_score(markets: List[Dict[str, Any]]) -> float:
    best = 0.0
    for market in markets:
        prices = [
            _safe_float(p)
            for p in _parse_json_array(market.get("outcome_prices"))
            if 0.0 <= _safe_float(p) <= 1.0
        ]
        if not prices:
            continue
        nearest = min(abs(p - 0.5) for p in prices)
        # 1.0 at 50/50, 0.0 at 0/100
        score = max(0.0, 1.0 - min(nearest * 2.0, 1.0))
        if score > best:
            best = score
    return best



def _channel_quality_score(reasonings: List[str]) -> float:
    if not reasonings:
        return 0.0
    good = 0
    total = 0
    for reasoning in reasonings:
        if not reasoning:
            continue
        total += 1
        text = reasoning.lower()
        if "[channel:" in text and "channel: other" not in text:
            good += 1
        elif any(
            key in text
            for key in [
                "rates",
                "liquidity",
                "inflation",
                "tariffs",
                "regulation",
                "energy",
                "labor",
                "demand",
                "supply",
                "capex",
            ]
        ):
            good += 1
    return (good / total) if total else 0.0


def _title_cluster_key(title: str) -> str:
    raw = (title or "").lower()
    # Remove date/deadline suffixes (e.g. "by April 30", "in February") while
    # avoiding generic "by X" phrases that change semantic meaning.
    base = re.sub(
        r"\b(?:by|in)\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|q[1-4]|\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?|\d{4})[^?]*\??$",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    base = re.sub(r"[^a-z0-9]+", " ", base).strip()
    return base or re.sub(r"[^a-z0-9]+", " ", raw).strip() or raw


def _candidate_strength(candidate: Dict[str, Any]) -> float:
    score = _safe_float(candidate.get("score"))
    if score > 0:
        return score
    event_volume = _safe_float(candidate.get("event_volume"))
    if event_volume > 0:
        return event_volume
    markets = candidate.get("markets") or []
    if isinstance(markets, list):
        return sum(_safe_float(m.get("volume_num")) for m in markets if isinstance(m, dict))
    return 0.0


def _dedupe_candidates_by_title(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best_by_key: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        title = str(candidate.get("title") or "")
        key = _title_cluster_key(title)
        current = best_by_key.get(key)
        if current is None or _candidate_strength(candidate) > _candidate_strength(current):
            best_by_key[key] = candidate
    deduped = list(best_by_key.values())
    deduped.sort(key=_candidate_strength, reverse=True)
    return deduped


async def _set_report_progress(
    supabase: Client,
    report_id: str,
    progress: Optional[Dict[str, Any]],
) -> None:
    await asyncio.to_thread(
        lambda: supabase.table("reports")
        .update({"progress": progress})
        .eq("id", report_id)
        .execute()
    )


async def _generate_text(
    *,
    api_key: str,
    system_prompt: str,
    prompt: str,
    temperature: float,
    response_mime_type: Optional[str] = None,
) -> str:
    client = genai.Client(api_key=api_key)
    for attempt in range(1, 5):
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=8192,
            )
            if response_mime_type:
                cfg = types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=8192,
                    response_mime_type=response_mime_type,
                )
            resp = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=cfg,
            )
            text = _extract_text(resp)
            if text.strip():
                return text
            raise RuntimeError("Empty LLM response")
        except Exception as err:
            msg = str(err)
            if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and attempt < 4:
                wait = min(2 ** attempt, 16) + random.random()
                logger.warning("Gemini rate-limited, retrying in %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            raise


# ---------------------------------------------------------------------------
# Single-stock report pipeline
# ---------------------------------------------------------------------------


def _build_single_stock_prompt(stocks_data: List[Dict[str, Any]], report_date: str) -> str:
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
            lines.append("No active single-stock prediction markets found for this name.")
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
                    prices = _parse_prices(mkt.get("outcomes"), mkt.get("outcome_prices"))
                    vol = _safe_float(mkt.get("volume_num"))
                    vol_str = f"${vol:,.0f}" if vol > 0 else "< $1K"
                    lines.append(f"    • Q: {q}")
                    lines.append(f"      Prices: {prices}  |  Volume: {vol_str}")
                lines.append("")

        data_sections.append("\n".join(lines))

    data_block = "\n\n".join(data_sections)

    return f"""DATA FOR ANALYSIS ({report_date}):

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


async def _generate_single_stock_report(
    supabase: Client,
    report: Dict[str, Any],
    report_id: str,
    report_date: str,
    api_key: str,
) -> tuple[str, List[str]]:
    stock_ids: List[str] = report.get("stock_ids") or []
    stocks_data: List[Dict[str, Any]] = []
    all_event_ids: List[str] = []

    for stock_id in stock_ids:
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
        stock_label = f"{stock.get('name')} ({stock.get('ticker') or 'N/A'})"
        await _set_report_progress(
            supabase,
            report_id,
            {
                "phase": "single_stock",
                "stage": "collecting_candidates",
                "stock": stock_label,
            },
        )

        mappings_resp = await asyncio.to_thread(
            lambda sid=stock_id: supabase.table("event_stock_mappings")
            .select("event_id")
            .eq("stock_id", sid)
            .eq("affects", True)
            .execute()
        )
        affected_event_ids = [r["event_id"] for r in (mappings_resp.data or [])]

        if not affected_event_ids:
            stocks_data.append({"stock": stock, "events": []})
            continue

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

        ef_resp = await asyncio.to_thread(
            lambda aeids=active_event_ids: supabase.table("event_filtering")
            .select("event_id")
            .in_("event_id", aeids)
            .eq("impact_type", "single_stock")
            .execute()
        )
        single_stock_ids = {r["event_id"] for r in (ef_resp.data or [])}
        single_stock_events = [e for e in active_events if e["id"] in single_stock_ids]

        events_with_markets: List[Dict[str, Any]] = []
        for event in single_stock_events:
            await _set_report_progress(
                supabase,
                report_id,
                {
                    "phase": "single_stock",
                    "stage": "collecting_markets",
                    "stock": stock_label,
                    "event": str(event.get("title") or ""),
                },
            )
            markets_resp = await asyncio.to_thread(
                lambda eid=event["id"]: supabase.table("polymarket_markets")
                .select("question, outcomes, outcome_prices, volume_num")
                .eq("event_id", eid)
                .order("volume_num", desc=True)
                .execute()
            )
            events_with_markets.append({**event, "markets": markets_resp.data or []})

        deduped_events = _dedupe_candidates_by_title(events_with_markets)
        all_event_ids.extend(e["id"] for e in deduped_events)
        stocks_data.append({"stock": stock, "events": deduped_events})
        if len(events_with_markets) != len(deduped_events):
            logger.info(
                "Single-stock dedupe for %s: %d -> %d events",
                stock_label,
                len(events_with_markets),
                len(deduped_events),
            )

    prompt = _build_single_stock_prompt(stocks_data, report_date)
    await _set_report_progress(
        supabase,
        report_id,
        {
            "phase": "single_stock",
            "stage": "writing_section",
        },
    )
    logger.info(
        "Generating single-stock report %s for %d stocks, prompt length %d chars",
        report_id,
        len(stocks_data),
        len(prompt),
    )
    content = await _generate_text(
        api_key=api_key,
        system_prompt=SINGLE_STOCK_REPORT_SYSTEM_PROMPT,
        prompt=prompt,
        temperature=0.0,
    )

    seen: set[str] = set()
    unique_event_ids = [
        eid for eid in all_event_ids if not (eid in seen or seen.add(eid))
    ]
    return content, unique_event_ids


# ---------------------------------------------------------------------------
# Sector report pipeline
# ---------------------------------------------------------------------------


def _build_sector_prompt(stocks_data: List[Dict[str, Any]], report_date: str) -> str:
    stock_blocks: List[str] = []

    for item in stocks_data:
        stock = item["stock"]
        selected_events = item.get("events") or []
        pre_count = int(item.get("pre_shortlist_count") or 0)
        raw_count = int(item.get("raw_candidate_count") or 0)
        verified_count = int(item.get("verified_count") or 0)

        lines = [
            "═" * 60,
            f"STOCK: {stock['name']} ({stock.get('ticker') or 'N/A'}) | stock_id={stock['id']} | sector={stock.get('sector') or 'N/A'}",
            f"screening_stats: raw={raw_count}, pre_shortlist={pre_count}, verifier_pass={verified_count}, final={len(selected_events)}",
            "",
        ]

        if not selected_events:
            lines.append("No screened sector events survived inclusion gates for this stock.")
        else:
            lines.append("SCREENED SECTOR EVENTS (already gated):")
            lines.append("")
            for ev in selected_events:
                lines.append(
                    f"- event_id={ev['id']} | score={ev.get('score', 0):.2f} | relevance={ev.get('relevance_score', 0):.2f} | channel={ev.get('channel_score', 0):.2f} | debate={ev.get('debate_score', 0):.2f}"
                )
                lines.append(f"  title: {ev['title']}")
                if ev.get("description"):
                    lines.append(f"  context: {ev['description']}")
                if ev.get("verifier_reason"):
                    lines.append(f"  verifier: {ev['verifier_reason']}")
                lines.append("  top_markets:")
                for mkt in ev.get("markets", [])[:3]:
                    q = mkt.get("question") or "?"
                    prices = _parse_prices(mkt.get("outcomes"), mkt.get("outcome_prices"))
                    vol = _safe_float(mkt.get("volume_num"))
                    lines.append(
                        f"   - Q: {q} | Prices: {prices} | Volume: ${vol:,.0f}"
                    )
                lines.append("")

        stock_blocks.append("\n".join(lines))

    data_block = "\n\n".join(stock_blocks)

    return f"""REPORT DATE: {report_date}

{data_block}

Task:
Write a sector report with real insight, not summary. Use only event_ids provided above.

Return JSON only.
"""


def _fallback_sector_content(
    *,
    report_date: str,
    stocks_data: List[Dict[str, Any]],
) -> tuple[str, List[str]]:
    lines = [
        f"# Sector Market Intelligence Brief — {report_date}",
        "",
        "## Executive Summary",
    ]

    all_selected = [ev for item in stocks_data for ev in (item.get("events") or [])]
    if not all_selected:
        lines.append(
            "No sector prediction markets currently clear the inclusion threshold for this portfolio."
        )
        return "\n".join(lines), []

    lines.append(
        "Only a narrow set of sector markets currently passes strict transmission filters."
    )

    selected_ids: List[str] = []
    for item in stocks_data:
        stock = item["stock"]
        events = item.get("events") or []
        ticker = stock.get("ticker") or "N/A"
        lines.extend(["", f"## {stock['name']} ({ticker})"])
        if not events:
            lines.append(
                f"No sector markets meet the inclusion threshold for {stock['name']} at this time."
            )
            continue

        for ev in events[:3]:
            selected_ids.append(ev["id"])
            lines.extend(
                [
                    "",
                    f"### {ev['title']}",
                    f"Event ID: `{ev['id']}` | Screening score: {ev.get('score', 0):.2f}",
                    f"Stock implication: {ev.get('verifier_reason') or 'Sector transmission is material but outcome-dependent.'}",
                ]
            )

    dedup_ids = list(dict.fromkeys(selected_ids))
    return "\n".join(lines), dedup_ids


def _render_sector_content(
    *,
    report_date: str,
    stocks_data: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> tuple[str, List[str]]:
    by_stock: Dict[str, Dict[str, Any]] = {
        str(item["stock"]["id"]): item for item in stocks_data
    }
    allowed_ids_by_stock: Dict[str, set[str]] = {
        sid: {str(ev["id"]) for ev in (item.get("events") or [])}
        for sid, item in by_stock.items()
    }
    event_title_by_stock: Dict[str, Dict[str, str]] = {
        sid: {str(ev["id"]): str(ev.get("title") or "Untitled event") for ev in (item.get("events") or [])}
        for sid, item in by_stock.items()
    }

    sections_raw = payload.get("stock_sections")
    if not isinstance(sections_raw, list):
        return _fallback_sector_content(report_date=report_date, stocks_data=stocks_data)

    sections_by_id: Dict[str, Dict[str, Any]] = {}
    for section in sections_raw:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("stock_id") or "")
        if sid in by_stock:
            sections_by_id[sid] = section

    lines = [
        f"# Sector Market Intelligence Brief — {report_date}",
        "",
        "## Executive Summary",
        str(payload.get("executive_summary") or "").strip()
        or "Sector signal is selective; only high-conviction transmission events are included.",
    ]

    selected_ids: List[str] = []

    for sid, item in by_stock.items():
        stock = item["stock"]
        ticker = stock.get("ticker") or "N/A"
        section = sections_by_id.get(sid) or {}
        events_raw = section.get("events")
        stock_events = events_raw if isinstance(events_raw, list) else []

        lines.extend(["", f"## {stock['name']} ({ticker})"])

        rendered = 0
        for ev in stock_events:
            if not isinstance(ev, dict):
                continue
            event_id = str(ev.get("event_id") or "")
            if event_id not in allowed_ids_by_stock.get(sid, set()):
                continue
            rendered += 1
            selected_ids.append(event_id)
            importance = str(ev.get("importance") or "medium").lower()
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            title = event_title_by_stock.get(sid, {}).get(event_id, "Untitled event")

            lines.extend(
                [
                    "",
                    f"### {title}",
                    f"Event ID: `{event_id}` | Importance: {importance.title()}",
                    f"Consensus: {str(ev.get('consensus') or '').strip() or 'Market pricing is mixed.'}",
                    f"Our view: {str(ev.get('analyst_view') or '').strip() or 'Transmission is plausible but conviction is moderate.'}",
                    f"Stock implication: {str(ev.get('stock_implication') or '').strip() or 'Outcome likely influences sector positioning and trading activity.'}",
                ]
            )
            watch_items = ev.get("watch_items")
            if isinstance(watch_items, list):
                clean_watch = [
                    str(w).strip() for w in watch_items if isinstance(w, str) and str(w).strip()
                ][:3]
                if clean_watch:
                    lines.append("Watch items:")
                    for w in clean_watch:
                        lines.append(f"- {w}")

        if rendered == 0:
            lines.append(
                f"No sector markets meet the inclusion threshold for {stock['name']} at this time."
            )

    dedup_ids = list(dict.fromkeys(selected_ids))
    if not dedup_ids:
        return _fallback_sector_content(report_date=report_date, stocks_data=stocks_data)
    return "\n".join(lines), dedup_ids


def _build_sector_verifier_prompt(
    *,
    stock: Dict[str, Any],
    event: Dict[str, Any],
    mapping_reasoning: str,
    markets: List[Dict[str, Any]],
) -> str:
    market_lines = []
    for mkt in markets[:3]:
        q = mkt.get("question") or "?"
        prices = _parse_prices(mkt.get("outcomes"), mkt.get("outcome_prices"))
        vol = _safe_float(mkt.get("volume_num"))
        market_lines.append(f"- Q: {q} | Prices: {prices} | Volume: ${vol:,.0f}")
    if not market_lines:
        market_lines.append("- (no market details)")
    market_block = "\n".join(market_lines)

    return f"""Stock:
name={stock.get("name")}
ticker={stock.get("ticker") or "N/A"}
sector={stock.get("sector") or "N/A"}

Event:
event_id={event.get("id")}
title={event.get("title")}
description={event.get("description") or "(none)"}

Existing mapping reasoning:
{mapping_reasoning or "(none)"}

Top markets:
{market_block}
"""


async def _verify_sector_candidate(
    *,
    api_key: str,
    stock: Dict[str, Any],
    event: Dict[str, Any],
    mapping_reasoning: str,
    markets: List[Dict[str, Any]],
) -> tuple[bool, str]:
    prompt = _build_sector_verifier_prompt(
        stock=stock,
        event=event,
        mapping_reasoning=mapping_reasoning,
        markets=markets,
    )
    try:
        raw = await _generate_text(
            api_key=api_key,
            system_prompt=SECTOR_VERIFIER_SYSTEM_PROMPT,
            prompt=prompt,
            temperature=0.0,
            response_mime_type="application/json",
        )
        parsed = json.loads(raw)
        include = bool(parsed.get("include", False))
        reason = str(parsed.get("reason") or "").strip()
        channel = str(parsed.get("channel") or "").strip()
        suffix = f" [channel: {channel}]" if channel else ""
        return include, (reason + suffix).strip() or ("Included by sector verifier" if include else "Rejected by sector verifier")
    except Exception as err:  # noqa: BLE001
        logger.warning("Sector verifier failed for event %s: %s", event.get("id"), err)
        return False, "Rejected: verifier error"


async def _generate_sector_report(
    supabase: Client,
    report: Dict[str, Any],
    report_id: str,
    report_date: str,
    api_key: str,
) -> tuple[str, List[str]]:
    stock_ids: List[str] = report.get("stock_ids") or []
    stocks_data: List[Dict[str, Any]] = []
    all_event_ids: List[str] = []

    for stock_id in stock_ids:
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
        stock_label = f"{stock.get('name')} ({stock.get('ticker') or 'N/A'})"
        await _set_report_progress(
            supabase,
            report_id,
            {
                "phase": "sector",
                "stage": "collecting_candidates",
                "stock": stock_label,
            },
        )

        mappings_resp = await asyncio.to_thread(
            lambda sid=stock_id: supabase.table("event_stock_mappings")
            .select("event_id, reasoning")
            .eq("stock_id", sid)
            .eq("affects", True)
            .execute()
        )
        mapping_rows = mappings_resp.data or []
        affected_event_ids = [r["event_id"] for r in mapping_rows if r.get("event_id")]
        mapping_reasoning_by_event = {
            str(r["event_id"]): str(r.get("reasoning") or "")
            for r in mapping_rows
            if r.get("event_id")
        }

        if not affected_event_ids:
            stocks_data.append(
                {
                    "stock": stock,
                    "events": [],
                    "raw_candidate_count": 0,
                    "pre_shortlist_count": 0,
                    "verified_count": 0,
                }
            )
            continue

        events_resp = await asyncio.to_thread(
            lambda eids=affected_event_ids: supabase.table("polymarket_events")
            .select("id, title, description, volume")
            .in_("id", eids)
            .eq("active", True)
            .execute()
        )
        active_events = events_resp.data or []
        active_event_ids = [e["id"] for e in active_events]

        if not active_event_ids:
            stocks_data.append(
                {
                    "stock": stock,
                    "events": [],
                    "raw_candidate_count": 0,
                    "pre_shortlist_count": 0,
                    "verified_count": 0,
                }
            )
            continue

        ef_resp = await asyncio.to_thread(
            lambda aeids=active_event_ids: supabase.table("event_filtering")
            .select("event_id, relevance_score")
            .in_("event_id", aeids)
            .eq("impact_type", "sector")
            .eq("relevant", True)
            .execute()
        )
        ef_rows = ef_resp.data or []
        sector_event_ids = {r["event_id"] for r in ef_rows if r.get("event_id")}
        relevance_by_event = {
            str(r["event_id"]): _safe_float(r.get("relevance_score"))
            for r in ef_rows
            if r.get("event_id")
        }
        sector_events = [e for e in active_events if e["id"] in sector_event_ids]

        if not sector_events:
            stocks_data.append(
                {
                    "stock": stock,
                    "events": [],
                    "raw_candidate_count": 0,
                    "pre_shortlist_count": 0,
                    "verified_count": 0,
                }
            )
            continue

        sector_event_ids_list = [str(e["id"]) for e in sector_events if e.get("id")]
        markets_resp = await asyncio.to_thread(
            lambda eids=sector_event_ids_list: supabase.table("polymarket_markets")
            .select("event_id, question, outcomes, outcome_prices, volume_num")
            .in_("event_id", eids)
            .order("volume_num", desc=True)
            .execute()
        )
        markets_by_event: Dict[str, List[Dict[str, Any]]] = {}
        for row in (markets_resp.data or []):
            event_id = row.get("event_id")
            if event_id:
                markets_by_event.setdefault(str(event_id), []).append(row)

        max_event_volume = max((_safe_float(e.get("volume")) for e in sector_events), default=0.0)
        scored_candidates: List[Dict[str, Any]] = []
        for event in sector_events:
            event_id = str(event["id"])
            event_markets = markets_by_event.get(event_id, [])
            event_volume = _safe_float(event.get("volume"))
            if max_event_volume > 0:
                volume_score = math.log1p(event_volume) / math.log1p(max_event_volume)
            else:
                volume_score = 0.0
            debate_score = _market_debate_score(event_markets)
            mapping_reasoning = mapping_reasoning_by_event.get(event_id, "")
            channel_score = _channel_quality_score([mapping_reasoning])
            relevance_score = min(max(relevance_by_event.get(event_id, 0.0), 0.0), 1.0)

            score = (
                0.35 * relevance_score
                + 0.30 * volume_score
                + 0.20 * channel_score
                + 0.15 * debate_score
            )
            scored_candidates.append(
                {
                    **event,
                    "id": event_id,
                    "score": score,
                    "relevance_score": relevance_score,
                    "debate_score": debate_score,
                    "channel_score": channel_score,
                    "volume_score": volume_score,
                    "mapping_reasoning": mapping_reasoning,
                    "markets": event_markets[:4],
                }
            )

        scored_candidates.sort(key=lambda row: row["score"], reverse=True)
        deduped_candidates = _dedupe_candidates_by_title(scored_candidates)
        pre_shortlist = [c for c in deduped_candidates if c["score"] >= 0.42][:6]
        if not pre_shortlist and deduped_candidates and deduped_candidates[0]["score"] >= 0.60:
            pre_shortlist = [deduped_candidates[0]]

        verified: List[Dict[str, Any]] = []
        for candidate in pre_shortlist:
            await _set_report_progress(
                supabase,
                report_id,
                {
                    "phase": "sector",
                    "stage": "verifying_event",
                    "stock": stock_label,
                    "event": str(candidate.get("title") or ""),
                },
            )
            include, verifier_reason = await _verify_sector_candidate(
                api_key=api_key,
                stock=stock,
                event=candidate,
                mapping_reasoning=str(candidate.get("mapping_reasoning") or ""),
                markets=candidate.get("markets") or [],
            )
            if include:
                verified.append({**candidate, "verifier_reason": verifier_reason})

        selected = verified[:3]
        logger.info(
            "Sector stock %s (%s): raw=%d, deduped=%d, pre_shortlist=%d, verifier_pass=%d, selected=%d",
            stock_id,
            stock.get("ticker") or stock.get("name"),
            len(scored_candidates),
            len(deduped_candidates),
            len(pre_shortlist),
            len(verified),
            len(selected),
        )

        all_event_ids.extend([str(e["id"]) for e in selected if e.get("id")])
        stocks_data.append(
            {
                "stock": stock,
                "events": selected,
                "raw_candidate_count": len(scored_candidates),
                "pre_shortlist_count": len(pre_shortlist),
                "verified_count": len(verified),
            }
        )

    prompt = _build_sector_prompt(stocks_data, report_date)
    await _set_report_progress(
        supabase,
        report_id,
        {
            "phase": "sector",
            "stage": "writing_section",
        },
    )
    logger.info(
        "Generating sector report %s for %d stocks, prompt length %d chars (selected_events=%d)",
        report_id,
        len(stocks_data),
        len(prompt),
        len(all_event_ids),
    )
    raw_text = await _generate_text(
        api_key=api_key,
        system_prompt=SECTOR_REPORT_SYSTEM_PROMPT,
        prompt=prompt,
        temperature=0.0,
        response_mime_type="application/json",
    )
    try:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("Sector response is not JSON object")
        return _render_sector_content(
            report_date=report_date,
            stocks_data=stocks_data,
            payload=parsed,
        )
    except Exception as err:
        logger.warning("Sector report JSON parse failed, using fallback: %s", err)
        return _fallback_sector_content(report_date=report_date, stocks_data=stocks_data)


# ---------------------------------------------------------------------------
# Macro report pipeline
# ---------------------------------------------------------------------------


def _build_macro_prompt(
    *,
    report_date: str,
    stocks: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> str:
    stock_lines = []
    for stock in stocks:
        ticker = stock.get("ticker") or "N/A"
        sector = stock.get("sector") or "N/A"
        stock_lines.append(
            f"- stock_id={stock['id']} | {stock['name']} ({ticker}) | sector={sector}"
        )

    event_blocks: List[str] = []
    for idx, ev in enumerate(candidates, start=1):
        mapped_names = ", ".join(
            f"{s.get('ticker') or s['name']} ({s['id']})" for s in ev["affected_stocks"]
        )
        lines = [
            f"{idx}. event_id={ev['event_id']}",
            f"   title={ev['title']}",
            f"   description={ev.get('description') or '(none)'}",
            f"   ranking_score={ev['score']:.3f} | breadth={ev['breadth_count']}/{ev['portfolio_size']} ({ev['breadth']:.2f}) | event_volume=${ev['event_volume']:,.0f}",
            f"   debate_score={ev['debate_score']:.2f} | channel_quality={ev['channel_score']:.2f} | relevance_score={ev['relevance_score']:.2f}",
            f"   mapped_stocks={mapped_names}",
            "   mapping_reasons:",
        ]
        for reason in ev["reasoning_samples"][:4]:
            lines.append(f"   - {reason}")
        lines.append("   top_markets:")
        for market in ev["top_markets"]:
            price_view = _parse_prices(market.get("outcomes"), market.get("outcome_prices"))
            mvol = _safe_float(market.get("volume_num"))
            lines.append(
                f"   - Q: {market.get('question') or '?'} | Prices: {price_view} | Volume: ${mvol:,.0f}"
            )
        event_blocks.append("\n".join(lines))

    stock_block = "\n".join(stock_lines)
    events_block = "\n\n".join(event_blocks)

    return f"""REPORT DATE: {report_date}

REPORT STOCK UNIVERSE:
{stock_block}

SHORTLISTED MACRO EVENTS (pre-ranked):
{events_block}

Task:
1) Choose up to 5 events that are most interesting RIGHT NOW for this portfolio.
2) For each selected event, explain what market pricing implies, why this is high-signal,
   and what it implies for specific stocks.
3) Exclude low-signal events.

Return JSON only.
"""


def _fallback_macro_content(
    *,
    report_date: str,
    candidates: List[Dict[str, Any]],
) -> tuple[str, List[str]]:
    if not candidates:
        content = (
            f"# Macro Market Intelligence Brief — {report_date}\n\n"
            "## Executive Summary\n"
            "No active macro prediction markets currently clear the materiality threshold for this portfolio."
        )
        return content, []

    selected = candidates[: min(3, len(candidates))]
    lines = [
        f"# Macro Market Intelligence Brief — {report_date}",
        "",
        "## Executive Summary",
        "Macro signal is mixed; the most actionable setup is in events with both broad portfolio reach and clear transmission channels.",
        "",
        "## Highest-Signal Prediction Markets",
    ]

    for ev in selected:
        lines.extend(
            [
                "",
                f"### {ev['title']}",
                f"Event ID: `{ev['event_id']}` | Ranking score: {ev['score']:.2f}",
                f"Why interesting now: Broad impact across {ev['breadth_count']}/{ev['portfolio_size']} tracked stocks with active pricing/volume.",
                "Stocks most exposed:",
            ]
        )
        for stock in ev["affected_stocks"][:5]:
            label = stock.get("ticker") or stock.get("name") or stock["id"]
            reason = stock.get("reasoning") or "Mapped as materially exposed via macro channel."
            lines.append(f"- {label}: {reason}")

    return "\n".join(lines), [ev["event_id"] for ev in selected]



def _render_macro_content(
    *,
    report_date: str,
    selected_events: List[Dict[str, Any]],
    candidates_by_id: Dict[str, Dict[str, Any]],
    executive_summary: str,
) -> tuple[str, List[str]]:
    chosen = [ev for ev in selected_events if ev.get("event_id") in candidates_by_id]
    if not chosen:
        return _fallback_macro_content(
            report_date=report_date,
            candidates=list(candidates_by_id.values()),
        )

    lines = [
        f"# Macro Market Intelligence Brief — {report_date}",
        "",
        "## Executive Summary",
        executive_summary.strip() or "No high-conviction macro signal for this portfolio right now.",
        "",
        "## Highest-Signal Prediction Markets",
    ]

    selected_ids: List[str] = []

    for event in chosen[:5]:
        event_id = str(event.get("event_id"))
        base = candidates_by_id[event_id]
        selected_ids.append(event_id)

        importance = str(event.get("importance") or "medium").lower()
        if importance not in {"high", "medium", "low"}:
            importance = "medium"

        lines.extend(
            [
                "",
                f"### {base['title']}",
                f"Event ID: `{event_id}` | Importance: {importance.title()}",
                f"What pricing implies: {str(event.get('market_implication') or '').strip() or 'Consensus is still evolving across outcomes.'}",
                f"Why it is interesting now: {str(event.get('why_interesting') or '').strip() or 'This event combines macro relevance with direct portfolio transmission.'}",
                f"Portfolio implication: {str(event.get('portfolio_implication') or '').strip() or 'Directional impact depends on resolution path and channel strength.'}",
                "Stocks most exposed:",
            ]
        )

        stock_implications = event.get("stock_implications") or []
        valid_implications = []
        for item in stock_implications:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("stock_id") or "")
            if sid not in {s["id"] for s in base["affected_stocks"]}:
                continue
            direction = str(item.get("direction") or "two-sided").lower()
            if direction not in {"tailwind", "headwind", "two-sided"}:
                direction = "two-sided"
            reason = str(item.get("reason") or "").strip() or "Causal path is material but uncertain."
            valid_implications.append((sid, direction, reason))

        if not valid_implications:
            for stock in base["affected_stocks"][:5]:
                sid = stock["id"]
                reason = stock.get("reasoning") or "Mapped as materially exposed to this macro event."
                valid_implications.append((sid, "two-sided", reason))

        for sid, direction, reason in valid_implications[:6]:
            stock = next((s for s in base["affected_stocks"] if s["id"] == sid), None)
            label = (stock or {}).get("ticker") or (stock or {}).get("name") or sid
            lines.append(f"- {label} ({direction}): {reason}")

        watch_items = [w for w in (event.get("watch_items") or []) if isinstance(w, str) and w.strip()]
        if watch_items:
            lines.append("Watch items:")
            for w in watch_items[:3]:
                lines.append(f"- {w.strip()}")

    return "\n".join(lines), selected_ids


async def _generate_macro_report(
    supabase: Client,
    report: Dict[str, Any],
    report_id: str,
    report_date: str,
    api_key: str,
) -> tuple[str, List[str]]:
    stock_ids: List[str] = report.get("stock_ids") or []
    if not stock_ids:
        return _fallback_macro_content(report_date=report_date, candidates=[])

    stocks_resp = await asyncio.to_thread(
        lambda ids=stock_ids: supabase.table("stocks")
        .select("id, name, ticker, sector, short_description")
        .in_("id", ids)
        .execute()
    )
    stocks = stocks_resp.data or []
    stocks_by_id = {str(s["id"]): s for s in stocks if s.get("id")}

    mappings_resp = await asyncio.to_thread(
        lambda ids=stock_ids: supabase.table("event_stock_mappings")
        .select("event_id, stock_id, reasoning")
        .in_("stock_id", ids)
        .eq("affects", True)
        .execute()
    )
    mappings = mappings_resp.data or []
    if not mappings:
        return _fallback_macro_content(report_date=report_date, candidates=[])

    mappings_by_event: Dict[str, List[Dict[str, Any]]] = {}
    for row in mappings:
        event_id = row.get("event_id")
        stock_id = row.get("stock_id")
        if not event_id or not stock_id:
            continue
        mappings_by_event.setdefault(str(event_id), []).append(row)

    mapped_event_ids = list(mappings_by_event.keys())
    if not mapped_event_ids:
        return _fallback_macro_content(report_date=report_date, candidates=[])

    ef_resp = await asyncio.to_thread(
        lambda eids=mapped_event_ids: supabase.table("event_filtering")
        .select("event_id, relevance_score")
        .in_("event_id", eids)
        .eq("impact_type", "macro")
        .eq("relevant", True)
        .execute()
    )
    ef_rows = ef_resp.data or []
    ef_by_event = {str(r["event_id"]): r for r in ef_rows if r.get("event_id")}
    macro_event_ids = list(ef_by_event.keys())
    if not macro_event_ids:
        return _fallback_macro_content(report_date=report_date, candidates=[])

    events_resp = await asyncio.to_thread(
        lambda eids=macro_event_ids: supabase.table("polymarket_events")
        .select("id, title, description, volume")
        .in_("id", eids)
        .eq("active", True)
        .execute()
    )
    active_events = events_resp.data or []
    active_event_ids = [str(e["id"]) for e in active_events if e.get("id")]
    if not active_event_ids:
        return _fallback_macro_content(report_date=report_date, candidates=[])

    markets_resp = await asyncio.to_thread(
        lambda eids=active_event_ids: supabase.table("polymarket_markets")
        .select("event_id, question, outcomes, outcome_prices, volume_num")
        .in_("event_id", eids)
        .order("volume_num", desc=True)
        .execute()
    )
    markets = markets_resp.data or []
    markets_by_event: Dict[str, List[Dict[str, Any]]] = {}
    for market in markets:
        event_id = market.get("event_id")
        if event_id:
            markets_by_event.setdefault(str(event_id), []).append(market)

    max_event_volume = max((_safe_float(ev.get("volume")) for ev in active_events), default=0.0)
    portfolio_size = max(1, len(stock_ids))

    candidates: List[Dict[str, Any]] = []
    for event in active_events:
        event_id = str(event.get("id"))
        mapping_rows = mappings_by_event.get(event_id, [])
        if not mapping_rows:
            continue

        unique_stock_ids = sorted({str(m.get("stock_id")) for m in mapping_rows if m.get("stock_id")})
        affected_stocks: List[Dict[str, Any]] = []
        for sid in unique_stock_ids:
            stock = stocks_by_id.get(sid)
            if not stock:
                continue
            reasoning = next(
                (str(m.get("reasoning") or "") for m in mapping_rows if str(m.get("stock_id")) == sid),
                "",
            )
            affected_stocks.append(
                {
                    "id": sid,
                    "name": stock.get("name"),
                    "ticker": stock.get("ticker"),
                    "sector": stock.get("sector"),
                    "reasoning": reasoning,
                }
            )

        if not affected_stocks:
            continue

        breadth_count = len(affected_stocks)
        breadth = breadth_count / portfolio_size
        event_volume = _safe_float(event.get("volume"))
        if max_event_volume > 0:
            volume_score = math.log1p(event_volume) / math.log1p(max_event_volume)
        else:
            volume_score = 0.0

        event_markets = markets_by_event.get(event_id, [])
        debate_score = _market_debate_score(event_markets)
        reasonings = [str(m.get("reasoning") or "") for m in mapping_rows]
        channel_score = _channel_quality_score(reasonings)
        relevance_score = _safe_float((ef_by_event.get(event_id) or {}).get("relevance_score"))

        score = (
            0.45 * breadth
            + 0.25 * volume_score
            + 0.20 * debate_score
            + 0.10 * channel_score
        )

        candidates.append(
            {
                "event_id": event_id,
                "title": event.get("title") or "Untitled event",
                "description": event.get("description"),
                "event_volume": event_volume,
                "breadth": breadth,
                "breadth_count": breadth_count,
                "portfolio_size": portfolio_size,
                "volume_score": volume_score,
                "debate_score": debate_score,
                "channel_score": channel_score,
                "relevance_score": relevance_score,
                "score": score,
                "affected_stocks": affected_stocks,
                "reasoning_samples": [r for r in reasonings if r][:4],
                "top_markets": event_markets[:3],
            }
        )

    if not candidates:
        return _fallback_macro_content(report_date=report_date, candidates=[])

    candidates.sort(key=lambda row: row["score"], reverse=True)
    deduped_candidates = _dedupe_candidates_by_title(candidates)
    shortlist = deduped_candidates[: min(10, len(deduped_candidates))]
    if len(candidates) != len(deduped_candidates):
        logger.info(
            "Macro dedupe for report %s: %d -> %d events",
            report_id,
            len(candidates),
            len(deduped_candidates),
        )

    prompt = _build_macro_prompt(
        report_date=report_date,
        stocks=stocks,
        candidates=shortlist,
    )
    await _set_report_progress(
        supabase,
        report_id,
        {
            "phase": "macro",
            "stage": "writing_section",
            "event": str(shortlist[0].get("title")) if shortlist else None,
        },
    )

    logger.info(
        "Generating macro report %s with %d shortlisted events (from %d candidates)",
        report_id,
        len(shortlist),
        len(deduped_candidates),
    )

    raw_text = await _generate_text(
        api_key=api_key,
        system_prompt=MACRO_REPORT_SYSTEM_PROMPT,
        prompt=prompt,
        temperature=0.15,
        response_mime_type="application/json",
    )

    try:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("Macro response is not a JSON object")
    except Exception as err:
        logger.warning("Macro report JSON parse failed, using fallback: %s", err)
        return _fallback_macro_content(report_date=report_date, candidates=shortlist)

    selected_events = parsed.get("selected_events")
    if not isinstance(selected_events, list):
        selected_events = []

    summary = str(parsed.get("executive_summary") or "").strip()
    content, selected_ids = _render_macro_content(
        report_date=report_date,
        selected_events=[e for e in selected_events if isinstance(e, dict)],
        candidates_by_id={row["event_id"]: row for row in shortlist},
        executive_summary=summary,
    )
    return content, selected_ids


def _strip_first_h1(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        if lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


async def _generate_combined_report(
    supabase: Client,
    report: Dict[str, Any],
    report_id: str,
    report_date: str,
    api_key: str,
) -> tuple[str, List[str]]:
    logger.info("Generating combined report %s: macro section", report_id)
    await _set_report_progress(
        supabase,
        report_id,
        {"phase": "combined", "stage": "starting_macro_section"},
    )
    macro_content, macro_event_ids = await _generate_macro_report(
        supabase=supabase,
        report=report,
        report_id=report_id,
        report_date=report_date,
        api_key=api_key,
    )

    logger.info("Generating combined report %s: sector section", report_id)
    await _set_report_progress(
        supabase,
        report_id,
        {"phase": "combined", "stage": "starting_sector_section"},
    )
    sector_content, sector_event_ids = await _generate_sector_report(
        supabase=supabase,
        report=report,
        report_id=report_id,
        report_date=report_date,
        api_key=api_key,
    )

    logger.info("Generating combined report %s: stock-specific section", report_id)
    await _set_report_progress(
        supabase,
        report_id,
        {"phase": "combined", "stage": "starting_stock_specific_section"},
    )
    stock_content, stock_event_ids = await _generate_single_stock_report(
        supabase=supabase,
        report=report,
        report_id=report_id,
        report_date=report_date,
        api_key=api_key,
    )

    combined = "\n\n".join(
        [
            f"# Unified Market Intelligence Brief — {report_date}",
            "## Macro",
            _strip_first_h1(macro_content) or "No macro section generated.",
            "## Sector",
            _strip_first_h1(sector_content) or "No sector section generated.",
            "## Stock-Specific",
            _strip_first_h1(stock_content) or "No stock-specific section generated.",
        ]
    )

    all_ids = macro_event_ids + sector_event_ids + stock_event_ids
    unique_event_ids = list(dict.fromkeys([str(eid) for eid in all_ids if eid]))

    logger.info(
        "Combined report %s sections done: macro=%d events, sector=%d events, stock=%d events",
        report_id,
        len(macro_event_ids),
        len(sector_event_ids),
        len(stock_event_ids),
    )
    return combined, unique_event_ids


# ---------------------------------------------------------------------------
# Main async generation function
# ---------------------------------------------------------------------------


async def generate_report_content(supabase: Client, report_id: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    await asyncio.to_thread(
        lambda: supabase.table("reports")
        .update({"status": "generating"})
        .eq("id", report_id)
        .execute()
    )

    try:
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

        report_type = _normalize_report_type(report.get("report_type"))
        report_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
        logger.info("Starting generation for report %s (type=%s)", report_id, report_type)
        await _set_report_progress(
            supabase,
            report_id,
            {
                "phase": report_type,
                "stage": "initializing",
            },
        )

        if report_type == "macro":
            content, event_ids = await _generate_macro_report(
                supabase=supabase,
                report=report,
                report_id=report_id,
                report_date=report_date,
                api_key=api_key,
            )
        elif report_type == "sector":
            content, event_ids = await _generate_sector_report(
                supabase=supabase,
                report=report,
                report_id=report_id,
                report_date=report_date,
                api_key=api_key,
            )
        elif report_type == "combined":
            content, event_ids = await _generate_combined_report(
                supabase=supabase,
                report=report,
                report_id=report_id,
                report_date=report_date,
                api_key=api_key,
            )
        else:
            content, event_ids = await _generate_single_stock_report(
                supabase=supabase,
                report=report,
                report_id=report_id,
                report_date=report_date,
                api_key=api_key,
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: supabase.table("reports")
            .update(
                {
                    "content": content,
                    "status": "ready",
                    "error": None,
                    "event_ids": event_ids,
                    "updated_at": now_iso,
                    "report_type": report_type,
                    "progress": None,
                }
            )
            .eq("id", report_id)
            .execute()
        )
        logger.info(
            "Finished generation for report %s (type=%s, events=%d)",
            report_id,
            report_type,
            len(event_ids),
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
        logger.exception("Report generation failed for %s", report_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: supabase.table("reports")
            .update(
                {
                    "status": "failed",
                    "error": str(err)[:500],
                    "updated_at": now_iso,
                    "progress": None,
                }
            )
            .eq("id", report_id)
            .execute()
        )
        raise
