import json
import os
import random
import re
import time
from typing import Optional, Tuple

from google import genai
from google.genai import types

MAX_RETRIES = 6
RETRY_BACKOFF_BASE_S = 2


def match_single_stock(
    stock_name: str,
    stock_ticker: Optional[str],
    event_title: str,
    event_description: Optional[str],
    market_questions: list[str],
) -> Tuple[bool, str]:
    texts = [event_title or "", event_description or "", *market_questions]
    combined = " ".join(text for text in texts if text).lower()

    patterns = []
    if stock_name and stock_name.strip():
        patterns.append(re.escape(stock_name.strip()))
    if stock_ticker and stock_ticker.strip():
        patterns.append(re.escape(stock_ticker.strip()))

    if not patterns:
        return False, "No name or ticker to match"

    for pattern in patterns:
        if re.search(rf"\b{pattern}\b", combined, re.IGNORECASE):
            return True, "Regex match: found in event/markets"

    return False, "No regex match for name or ticker"


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
            if not text and getattr(resp, "candidates", None):
                text = resp.candidates[0].content.parts[0].text
            parsed = json.loads(text)
            return bool(parsed.get("affects", False)), str(parsed.get("reasoning", ""))
        except Exception as err:  # noqa: BLE001
            msg = str(err)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = min(RETRY_BACKOFF_BASE_S**attempt, 32) + random.random()
                time.sleep(wait)
                continue
            return False, f"LLM error: {msg[:100]}"

    return False, "LLM retries exhausted"
