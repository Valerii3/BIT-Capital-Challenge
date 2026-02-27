/**
 * Event-to-stock mapping logic:
 * - single_stock: regex on event title + description + market questions (name + ticker)
 * - macro / sector / crypto_equity: LLM classification
 */
import { GoogleGenAI } from "@google/genai";

export type ImpactType = "macro" | "sector" | "crypto_equity" | "single_stock";

export interface StockInfo {
  id: string;
  name: string;
  ticker: string | null;
  sector: string | null;
  impact_types: string[];
}

export interface EventInfo {
  event_id: string;
  impact_type: string;
  title: string;
  description: string | null;
  market_questions: string[];
}

export interface MatchResult {
  event_id: string;
  relevance_score: number | null;
  reasoning: string;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Regex match for single_stock: name and ticker in title + description + market questions */
export function matchSingleStock(
  stock: Pick<StockInfo, "name" | "ticker">,
  event: Pick<EventInfo, "title" | "description" | "market_questions">
): { matches: boolean; reasoning: string } {
  const texts: string[] = [
    event.title || "",
    event.description || "",
    ...(event.market_questions || []),
  ];
  const combined = texts.filter(Boolean).join(" ").toLowerCase();

  const patterns: string[] = [];
  if (stock.name?.trim()) {
    patterns.push(escapeRegex(stock.name.trim()));
  }
  if (stock.ticker?.trim()) {
    patterns.push(escapeRegex(stock.ticker.trim()));
  }

  if (patterns.length === 0) {
    return { matches: false, reasoning: "No name or ticker to match" };
  }

  for (const p of patterns) {
    const re = new RegExp(`\\b${p}\\b`, "i");
    if (re.test(combined)) {
      return {
        matches: true,
        reasoning: `Regex match: found "${p}" in event/markets`,
      };
    }
  }
  return { matches: false, reasoning: "No regex match for name or ticker" };
}

const MAX_LLM_RETRIES = 4;
const RETRY_BACKOFF_MS = 2000;

/** LLM classification for macro / sector / crypto_equity */
export async function classifyWithLLM(
  impactType: "macro" | "sector" | "crypto_equity",
  stock: StockInfo,
  event: EventInfo
): Promise<{ affects: boolean; reasoning: string }> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error("GEMINI_API_KEY not configured");

  const ai = new GoogleGenAI({ apiKey });

  const marketText =
    event.market_questions?.length > 0
      ? "\nMarket questions: " + event.market_questions.join(" | ")
      : "";

  const prompt = `You are judging whether a Polymarket event affects a specific public company.

Event (impact_type=${impactType}):
Title: ${event.title}
Description: ${event.description || "(none)"}${marketText}

Company: ${stock.name}${stock.ticker ? ` (${stock.ticker})` : ""}${stock.sector ? `, sector: ${stock.sector}` : ""}

Does this ${impactType} event materially affect this company? Answer with a JSON object:
{ "affects": true/false, "reasoning": "one sentence" }

Return ONLY valid JSON, no markdown fences.`;

  for (let attempt = 1; attempt <= MAX_LLM_RETRIES; attempt++) {
    try {
      const response = await ai.models.generateContent({
        model: "gemini-2.0-flash",
        contents: prompt,
        config: {
          temperature: 0,
          responseMimeType: "application/json",
        },
      });

      const text = response.text ?? "";
      const parsed = JSON.parse(text) as { affects?: boolean; reasoning?: string };
      return {
        affects: !!parsed.affects,
        reasoning: parsed.reasoning ?? "No reasoning provided",
      };
    } catch (err) {
      const status =
        err instanceof Error && "status" in err
          ? (err as { status: number }).status
          : 0;
      const isRetryable = status === 429 || status >= 500;

      if (isRetryable && attempt < MAX_LLM_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS * attempt));
        continue;
      }
      return {
        affects: false,
        reasoning: `LLM error: ${err instanceof Error ? err.message : "Unknown"}`,
      };
    }
  }
  return { affects: false, reasoning: "LLM retries exhausted" };
}
