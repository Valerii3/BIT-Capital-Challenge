from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Optional, Tuple

from google import genai
from google.genai import types

MAX_RETRIES = 6
RETRY_BACKOFF_BASE_S = 2

# ---------------------------------------------------------------------------
# Expert system prompts — one per impact type
# ---------------------------------------------------------------------------

MACRO_EXPERT_SYSTEM = """
You are a macro equity strategist for a growth-oriented technology investment team.

Your research lens is:
- Fed path, real yields, liquidity, inflation, labor market
- fiscal policy, shutdowns, tariffs, export controls
- risk-on/risk-off regimes
- second-order effects on growth equities, semis, cloud, fintech, consumer internet
- power and energy constraints where they affect AI/data-center buildout

Your goal is NOT to identify any possible effect.
Your goal is to identify only MATERIAL and PLAUSIBLE effects that a public-equity analyst would care about.

Material effect means at least one of:
- changes revenue demand
- changes capex intensity or financing conditions
- changes margins/cost of capital
- changes regulation / supply chain access
- changes valuation regime for the stock's peer group

Not material:
- generic market mood
- weak correlation
- distant political narratives
- event is important globally but has no clear company transmission

Return ONLY valid JSON:
{
  "affects": true/false,
  "impact_strength": "none" | "low" | "medium" | "high",
  "channel": "rates" | "liquidity" | "inflation" | "tariffs" | "export_controls" | "fiscal" | "labor" | "energy" | "other",
  "reasoning": "one sentence",
  "analyst_note": "one short sentence saying what the analyst should watch"
}

Decision rules:
- Be conservative.
- Prefer false negatives over false positives.
- If the event affects the whole market but not this company more than a generic index effect, answer false.
- A market about a foreign election is false unless there is a clear policy transmission to this company.
- A tariff / export-control market can be true for semis, hardware, industrials, rare-earth users, or China-exposed supply chains.
- A Fed / rate market can be true for long-duration growth, fintech lenders, insurers, brokers, and capital-intensive AI infra names.
"""

SECTOR_EXPERT_SYSTEM = """
You are a sector specialist mapping events to public equities.

You think like a fundamental analyst covering:
- AI infrastructure: semis, GPUs, memory, networking, servers, cloud, data centers, power
- software/platforms where model quality or deployment economics matter
- fintech: payments, brokers, insurtech, digital banking, transaction infrastructure
- digital infrastructure and technology supply chains

Your task is to decide whether the event has a DIRECT SECTOR TRANSMISSION to the company.

A valid transmission must go through one of:
- demand for the company's products/services
- supply availability / export access / component constraints
- competitive positioning / market share
- monetization / pricing power
- capex cycle / infrastructure spend
- regulatory change specific to the sector

Reject weak narratives like:
- "AI is hot therefore every tech stock is affected"
- "best model" means every chip stock benefits
- "crypto rally" means every growth stock benefits

Return ONLY valid JSON:
{
  "affects": true/false,
  "impact_strength": "none" | "low" | "medium" | "high",
  "channel": "demand" | "supply" | "competition" | "pricing" | "capex" | "regulation" | "other",
  "reasoning": "one sentence",
  "analyst_note": "one short sentence"
}

Decision rules:
- The company must be closer than one hop to the event.
- If the event is about model rankings, answer true only for firms whose adoption, cloud demand, or monetization is likely to change materially.
- For AI infra stocks, require evidence of changed compute demand, capex, export restrictions, or customer concentration effects.
- For fintech stocks, require changed payment flows, underwriting, customer acquisition, spreads, or regulation.
- If the event is generic sector chatter without likely economic consequence, answer false.
"""

CRYPTO_EQUITY_EXPERT_SYSTEM = """
You are a crypto-equity specialist for a public-equities research team.

You cover listed companies with DIRECT crypto exposure, including:
- exchanges, brokerages, custody, wallets
- miners / HPC infra with crypto-linked economics
- companies with crypto treasury exposure
- stablecoin / tokenization / payments / on-chain finance infrastructure
- firms whose revenue is directly driven by crypto volumes, fees, spreads, issuance, custody, or mining economics

Your job is to decide whether a crypto-related event materially affects this public company.

Return ONLY valid JSON:
{
  "affects": true/false,
  "impact_strength": "none" | "low" | "medium" | "high",
  "channel": "asset_price" | "trading_volume" | "mining_economics" | "treasury_value" | "regulation" | "stablecoins" | "tokenization" | "adoption" | "other",
  "reasoning": "one sentence",
  "analyst_note": "one short sentence"
}

Hard rules:
1. DIRECT exposure required.
2. If the company is not a crypto-linked equity, answer false.
3. Pure BTC/ETH price-target markets should usually be false for non-crypto equities.
4. Do NOT treat Nvidia, AMD, Micron, generic cloud, or generic semis as crypto_equity just because they sell compute or hardware into the economy.
5. True examples:
   - Coinbase / Robinhood: markets that affect crypto trading, regulation, tokenization, stablecoins
   - IREN / Hut 8 / miners: BTC price, mining difficulty, energy policy, crypto regulation, AI/HPC pivot if company-specific
   - stablecoin/payment infra names: stablecoin regulation, major payment adoption, tokenized-asset policy
6. False examples:
   - "What price will Bitcoin hit in February?" -> false for Nvidia
   - "What price will Ethereum hit in February?" -> false for Nvidia
   - generic crypto sentiment events -> false for companies without direct crypto economics

Be strict and prefer false over weak true.
"""

SINGLE_STOCK_EXPERT_SYSTEM = """
You are a single-name equity analyst.

You only mark an event as relevant if it is a genuinely company-specific catalyst.

A valid company-specific catalyst includes:
- event explicitly names the company
- earnings, guidance, product launch, M&A, CEO/legal/regulatory issue
- major customer/supplier dependency
- direct competitor outcome that clearly changes this company's demand or share
- company-specific policy or contract award/loss

Return ONLY valid JSON:
{
  "affects": true/false,
  "impact_strength": "none" | "low" | "medium" | "high",
  "channel": "earnings" | "guidance" | "product" | "competition" | "customer" | "supplier" | "regulation" | "management" | "legal" | "other",
  "reasoning": "one sentence",
  "analyst_note": "one short sentence"
}

Hard rules:
- If the company is not explicitly named and no direct transmission exists, answer false.
- Do not mark something true just because the company operates in the same broad theme.
- Price-target or popularity markets are usually false unless they directly reference the company and matter fundamentally.
- A leaderboard question is not a company catalyst unless it is likely to affect monetization, adoption, or share in the next investment horizon.
"""

_EXPERT_SYSTEMS: dict[str, str] = {
    "macro": MACRO_EXPERT_SYSTEM,
    "sector": SECTOR_EXPERT_SYSTEM,
    "crypto_equity": CRYPTO_EQUITY_EXPERT_SYSTEM,
    "single_stock": SINGLE_STOCK_EXPERT_SYSTEM,
}

# ---------------------------------------------------------------------------
# Few-shot examples per impact type
# Format: list of (user_message, model_response) tuples
# ---------------------------------------------------------------------------

_FEW_SHOT_EXAMPLES: dict[str, list[tuple[str, str]]] = {
    "macro": [],
    "sector": [
        (
            "Event:\nTitle: Which company has the best AI model end of March?\nDescription: (none)\n\n"
            "Company: Nvidia (NVDA), sector: Semiconductors",
            '{"affects": false, "impact_strength": "none", "channel": "competition", '
            '"reasoning": "This event tracks AI model quality rankings which does not directly '
            'affect Nvidia GPU demand, capex, or revenue.", '
            '"analyst_note": "Nvidia sells chips to all AI labs; no single ranking changes its competitive position."}',
        ),
    ],
    "crypto_equity": [
        (
            "Event:\nTitle: What price will Bitcoin hit in February?\nDescription: (none)\n\n"
            "Company: Nvidia (NVDA), sector: Semiconductors",
            '{"affects": false, "impact_strength": "none", "channel": "asset_price", '
            '"reasoning": "Nvidia sells GPUs broadly and has no direct crypto-linked revenue, '
            'treasury, exchange, custody, or mining economics.", '
            '"analyst_note": "Do not conflate indirect GPU demand with direct crypto exposure."}',
        ),
        (
            "Event:\nTitle: Will Congress pass a stablecoin bill this quarter?\nDescription: (none)\n\n"
            "Company: Robinhood (HOOD), sector: Fintech / Digital Brokerage",
            '{"affects": true, "impact_strength": "medium", "channel": "regulation", '
            '"reasoning": "Regulatory clarity on stablecoins would directly affect Robinhood\'s '
            'crypto product expansion, user engagement, and monetization.", '
            '"analyst_note": "Robinhood derives meaningful revenue from crypto trading and custody."}',
        ),
        (
            "Event:\nTitle: Will Ethereum ETF inflows exceed Bitcoin ETF inflows this month?\nDescription: (none)\n\n"
            "Company: Coinbase (COIN), sector: Crypto Exchange",
            '{"affects": true, "impact_strength": "high", "channel": "trading_volume", '
            '"reasoning": "Coinbase is the primary custodian for most US spot crypto ETFs; '
            'higher ETF inflows drive direct custody and trading fee revenue.", '
            '"analyst_note": "Coinbase earns fees on both BTC and ETH ETF assets under custody."}',
        ),
    ],
    "single_stock": [
        (
            "Event:\nTitle: Which company has the best AI model end of March?\nDescription: (none)\n\n"
            "Company: Nvidia (NVDA), sector: Semiconductors",
            '{"affects": false, "impact_strength": "none", "channel": "competition", '
            '"reasoning": "This market asks about AI model quality rankings; Nvidia is a chip '
            'supplier, not an AI model competitor, and is not explicitly named.", '
            '"analyst_note": "Single-stock events must name or directly implicate the company."}',
        ),
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_user_message(
    stock_name: str,
    stock_ticker: Optional[str],
    stock_sector: Optional[str],
    event_title: str,
    event_description: Optional[str],
    market_questions: list[str],
) -> str:
    market_text = ""
    if market_questions:
        market_text = "\nMarket questions: " + " | ".join(market_questions)
    company_str = stock_name
    if stock_ticker:
        company_str += f" ({stock_ticker})"
    if stock_sector:
        company_str += f", sector: {stock_sector}"
    return (
        f"Event:\nTitle: {event_title}\n"
        f"Description: {event_description or '(none)'}"
        f"{market_text}\n\n"
        f"Company: {company_str}"
    )


def _parse_llm_response(text: str) -> Tuple[bool, str]:
    parsed = json.loads(text)
    affects = bool(parsed.get("affects", False))
    reasoning = str(parsed.get("reasoning", ""))
    channel = str(parsed.get("channel", ""))
    analyst_note = str(parsed.get("analyst_note", ""))
    parts = [p for p in [reasoning, f"[channel: {channel}]" if channel else "", analyst_note] if p]
    return affects, " | ".join(parts)


def _build_contents(impact_type: str, user_message: str) -> list[types.Content]:
    contents: list[types.Content] = []
    for user_ex, model_ex in _FEW_SHOT_EXAMPLES.get(impact_type, []):
        contents.append(types.Content(role="user", parts=[types.Part(text=user_ex)]))
        contents.append(types.Content(role="model", parts=[types.Part(text=model_ex)]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))
    return contents


# ---------------------------------------------------------------------------
# Sync classify (kept for backward compatibility with any existing callers)
# ---------------------------------------------------------------------------

def classify_with_llm(
    impact_type: str,
    stock_name: str,
    stock_ticker: Optional[str],
    stock_sector: Optional[str],
    event_title: str,
    event_description: Optional[str],
    market_questions: list[str],
) -> Tuple[bool, str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return False, "API key not set"

    system_prompt = _EXPERT_SYSTEMS.get(impact_type)
    if system_prompt is None:
        return False, f"Unknown impact_type: {impact_type}"

    client = genai.Client(api_key=api_key)
    user_message = _build_user_message(
        stock_name, stock_ticker, stock_sector,
        event_title, event_description, market_questions,
    )
    contents = _build_contents(impact_type, user_message)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            text = getattr(resp, "text", None) or ""
            if not text and getattr(resp, "candidates", None):
                text = resp.candidates[0].content.parts[0].text
            return _parse_llm_response(text)
        except Exception as err:  # noqa: BLE001
            msg = str(err)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = min(RETRY_BACKOFF_BASE_S ** attempt, 32) + random.random()
                time.sleep(wait)
                continue
            return False, f"LLM error: {msg[:100]}"

    return False, "LLM retries exhausted"


# ---------------------------------------------------------------------------
# Async classify (used by enrich.py for concurrent event processing)
# ---------------------------------------------------------------------------

async def classify_with_llm_async(
    impact_type: str,
    stock_name: str,
    stock_ticker: Optional[str],
    stock_sector: Optional[str],
    event_title: str,
    event_description: Optional[str],
    market_questions: list[str],
    semaphore: asyncio.Semaphore,
) -> Tuple[bool, str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return False, "API key not set"

    system_prompt = _EXPERT_SYSTEMS.get(impact_type)
    if system_prompt is None:
        return False, f"Unknown impact_type: {impact_type}"

    client = genai.Client(api_key=api_key)
    user_message = _build_user_message(
        stock_name, stock_ticker, stock_sector,
        event_title, event_description, market_questions,
    )
    contents = _build_contents(impact_type, user_message)

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                )
                text = getattr(resp, "text", None) or ""
                if not text and getattr(resp, "candidates", None):
                    text = resp.candidates[0].content.parts[0].text
                return _parse_llm_response(text)
            except Exception as err:  # noqa: BLE001
                msg = str(err)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    wait = min(RETRY_BACKOFF_BASE_S ** attempt, 32) + random.random()
                    await asyncio.sleep(wait)
                    continue
                return False, f"LLM error: {msg[:100]}"

    return False, "LLM retries exhausted"
