"""
Fetch polymarket_events, apply prefiltering, run LLM classification on
prefilter-passing events, and persist to event_filtering table.
"""
import ast
import json
import os
import random
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client

load_dotenv()

BLOCKLIST_TAGS = {
    'sports', 'soccer', 'basketball', 'ncaa', 'ncaa basketball',
    'epl', 'premier league', 'la liga', 'games', 'esports',
    'counter strike 2',
    'movies', 'music', 'oscars', 'awards', 'celebrities',
    'culture', 'box office',
    'daily temperature',
    'up or down', 'crypto prices', 'daily', 'hit price',
    'multi strikes', 'pre-market',
}

WHITELIST_TAGS = {
    'finance', 'business', 'equities', 'stocks', 'earnings',
    'ipos', 'big tech', 'economy', 'economic policy',
    'macro indicators', 'fed', 'fed rates',
    'tech', 'ai', 'openai',
    'geopolitics', 'politics', 'congress', 'trump',
    'china', 'iran', 'foreign policy', 'trade',
    'crypto',
}

THEMES = [
    {"id": "rates_fed", "label": "Rates / Fed / inflation / recession", "weight": 1.0},
    {"id": "trade_tariffs", "label": "Trade policy / tariffs / export controls / sanctions", "weight": 1.0},
    {"id": "ai_capex", "label": "AI capex / hyperscaler spend / AI bubble narrative", "weight": 1.0},
    {"id": "dc_power", "label": "Datacenters / power / grid constraints / energy infrastructure", "weight": 1.0},
    {"id": "semis_supply", "label": "Semis supply chain (NVDA/TSMC/MU/export controls)", "weight": 1.0},
    {"id": "crypto_reg", "label": "Crypto regulation / stablecoins / ETFs / SEC", "weight": 1.0},
    {"id": "crypto_equity", "label": "Crypto equity proxies (miners / exchanges / fintech rails)", "weight": 1.0},
    {"id": "geopolitics", "label": "War / geopolitics (only if oil/shipping/sanctions)", "weight": 0.6},
    {"id": "health", "label": "Health/biotech (only if public equities exposure)", "weight": 0.4},
]
THEME_IDS = [t["id"] for t in THEMES]
THEME_LABELS = {t["id"]: t["label"] for t in THEMES}
THEME_WEIGHTS = {t["id"]: t["weight"] for t in THEMES}

SYSTEM_PROMPT = f"""You are classifying Polymarket events for relevance to public equities using BIT Capital's focus. Return JSON only.

Themes (choose 0-4 max):
{json.dumps([{"id": t["id"], "label": t["label"]} for t in THEMES], ensure_ascii=False, indent=2)}

Definitions:
- relevant = true only if there is a clear equity transmission channel.
- relevance_score: 0..1 (how equity-relevant from BIT focus)
- confidence: 0..1 (how sure you are)
- impact_type: one of ["macro","sector","single_stock","crypto_equity","non_equity"]

Scoring guidance:
- 0.9-1.0: explicit Fed/CPI/tariffs/export controls/SEC-ETF/stablecoin law/semiconductor choke point or explicit public company event
- 0.6-0.8: clear sector transmission but no specific company
- 0.3-0.5: plausible but weak/second-order
- 0.0-0.2: no clear equity link

Respond ONLY with:
{{
  "theme_labels": ["..."],
  "relevance_score": 0.0,
  "confidence": 0.0,
  "impact_type": "macro|sector|single_stock|crypto_equity|non_equity",
  "relevant": true/false,
  "reasoning": "one sentence referencing the transmission channel"
}}"""


def check_tags(tags):
    if not isinstance(tags, list):
        return 'no_tags'
    tags_lower = {t.lower().strip() for t in tags}
    if tags_lower & WHITELIST_TAGS:
        return 'keep'
    if tags_lower & BLOCKLIST_TAGS:
        return 'block'
    return 'unknown'


def parse_tags(tags):
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        try:
            return ast.literal_eval(tags)
        except (ValueError, SyntaxError):
            return []
    return []


def regex_filter(title):
    if not title:
        return 'keep'
    if re.search(r'\d{1,2}:\d{2}\s*[AP]M\s*-\s*\d{1,2}:\d{2}\s*[AP]M\s*ET', title, re.IGNORECASE):
        return 'block'
    if re.search(r'\b\d{1,2}\s*[AP]M\s+ET\b', title, re.IGNORECASE):
        return 'block'
    return 'keep'


def classify_one(
    title: str,
    description: str = "",
    tags: str = "",
    volume: float = 0.0,
    model: str = "gemini-2.5-flash-lite",
    max_retries: int = 6,
):
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {
            "theme_labels": [],
            "relevance_score": 0.0,
            "confidence": 0.0,
            "impact_type": "non_equity",
            "relevant": False,
            "reasoning": "error: GEMINI_API_KEY not set",
        }
    client = genai.Client(api_key=api_key)
    user_prompt = f"""Event title: {title}
Event description: {description}
Tags: {tags}
Volume: ${volume:,.0f}"""
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            text = getattr(resp, "text", None) or ""
            if not text and resp.candidates:
                text = resp.candidates[0].content.parts[0].text
            return json.loads(text)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                sleep_s = min(2 ** attempt, 32) + random.random()
                time.sleep(sleep_s)
                continue
            return {
                "theme_labels": [],
                "relevance_score": 0.0,
                "confidence": 0.0,
                "impact_type": "non_equity",
                "relevant": False,
                "reasoning": f"error: {msg[:160]}",
            }
    return {
        "theme_labels": [],
        "relevance_score": 0.0,
        "confidence": 0.0,
        "impact_type": "non_equity",
        "relevant": False,
        "reasoning": "rate-limited: retries exhausted",
    }


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)

    supabase = create_client(url, key)

    events_resp = (
        supabase.table("polymarket_events")
        .select("*")
        .eq("active", True)
        .limit(500)
        .execute()
    )
    events = events_resp.data or []

    existing_resp = supabase.table("event_filtering").select("event_id").execute()
    existing_ids = {r["event_id"] for r in (existing_resp.data or [])}

    inserted = 0
    llm_run = 0
    relevant_count = 0

    for ev in events:
        event_id = str(ev.get("id", ""))
        if not event_id or event_id in existing_ids:
            continue

        tags = parse_tags(ev.get("tags"))
        tag_decision = check_tags(tags)
        title = ev.get("title") or ""
        title_result = regex_filter(title)
        prefilter_passed = tag_decision in ("keep", "unknown") and title_result == "keep"

        row = {
            "event_id": event_id,
            "tag_decision": tag_decision,
            "prefilter_passed": prefilter_passed,
        }
        supabase.table("event_filtering").insert(row).execute()
        inserted += 1
        existing_ids.add(event_id)

        if prefilter_passed:
            out = classify_one(
                title=title,
                description=str(ev.get("description") or ""),
                tags=str(tags),
                volume=float(ev.get("volume") or 0.0),
            )
            llm_run += 1
            if out.get("relevant"):
                relevant_count += 1
            supabase.table("event_filtering").update(
                {
                    "relevant": out.get("relevant"),
                    "relevance_score": out.get("relevance_score"),
                    "confidence": out.get("confidence"),
                    "impact_type": out.get("impact_type"),
                    "reasoning": out.get("reasoning"),
                    "theme_labels": out.get("theme_labels", []),
                }
            ).eq("event_id", event_id).execute()

    print(f"Inserted: {inserted} rows")
    print(f"LLM runs: {llm_run}")
    print(f"Relevant: {relevant_count}")


if __name__ == "__main__":
    main()
