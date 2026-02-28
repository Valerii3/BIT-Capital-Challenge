"""
Fetch polymarket_events, apply prefiltering, run LLM classification on
prefilter-passing events, and persist to event_filtering table.
"""
import ast
import json
import logging
import os
import random
import re
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


_ERROR_RESULT = {
    "theme_labels": [],
    "relevance_score": 0.0,
    "confidence": 0.0,
    "impact_type": "non_equity",
    "relevant": False,
}


def classify_one(
    title: str,
    description: str = "",
    tags: str = "",
    volume: float = 0.0,
    model: str = "gemini-2.5-flash",
):
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY / GOOGLE_API_KEY not set")
        return {**_ERROR_RESULT, "reasoning": "error: GEMINI_API_KEY not set"}

    client = genai.Client(api_key=api_key)
    user_prompt = f"""Event title: {title}
Event description: {description}
Tags: {tags}
Volume: ${volume:,.0f}"""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Gemini call attempt %d/%d for '%s'", attempt, MAX_RETRIES, title[:80])
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
                wait = min(RETRY_BACKOFF_BASE_S ** attempt, 32) + random.random()
                logger.warning(
                    "Attempt %d/%d rate-limited (%s), retrying in %.1fs...",
                    attempt, MAX_RETRIES, msg[:80], wait,
                )
                time.sleep(wait)
                continue
            logger.error("Attempt %d/%d non-retryable error: %s", attempt, MAX_RETRIES, msg[:160])
            return {**_ERROR_RESULT, "reasoning": f"error: {msg[:160]}"}

    logger.error("All %d retries exhausted for '%s'", MAX_RETRIES, title[:80])
    return {**_ERROR_RESULT, "reasoning": "rate-limited: retries exhausted"}


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)

    supabase = create_client(url, key)

    logger.info("Fetching active events from polymarket_events...")
    events_resp = (
        supabase.table("polymarket_events")
        .select("*")
        .eq("active", True)
        .execute()
    )
    events = events_resp.data or []
    logger.info("Fetched %d active events", len(events))

    existing_resp = supabase.table("event_filtering").select("event_id").execute()
    existing_ids = {r["event_id"] for r in (existing_resp.data or [])}
    logger.info("Already classified: %d events", len(existing_ids))

    inserted = 0
    llm_run = 0
    relevant_count = 0
    new_events = [
        ev for ev in events
        if str(ev.get("id", "")) and str(ev.get("id", "")) not in existing_ids
    ]
    logger.info("New events to process: %d", len(new_events))

    for ev in new_events:
        event_id = str(ev["id"])

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
            is_relevant = out.get("relevant", False)
            if is_relevant:
                relevant_count += 1
            logger.info(
                "Classified '%s': relevant=%s score=%.2f impact=%s",
                title[:60], is_relevant,
                out.get("relevance_score", 0.0), out.get("impact_type", "?"),
            )
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

    logger.info("Done — inserted=%d  llm_runs=%d  relevant=%d", inserted, llm_run, relevant_count)


if __name__ == "__main__":
    main()
