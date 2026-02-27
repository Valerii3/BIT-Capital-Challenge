import { NextRequest, NextResponse } from "next/server";
import { GoogleGenAI } from "@google/genai";
import { createServerClient } from "@/lib/supabase-server";
import {
  matchSingleStock,
  classifyWithLLM,
  type StockInfo,
  type EventInfo,
} from "@/lib/event-stock-mapping";

const MAX_RETRIES = 4;
const RETRY_BACKOFF_BASE_S = 2;

async function enrichDescription(companyName: string): Promise<{
  ticker: string | null;
  short_description: string | null;
  sector: string | null;
  impact_types: string[];
}> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error("GEMINI_API_KEY not configured");

  const ai = new GoogleGenAI({ apiKey });
  const prompt = `Given the company name "${companyName}", return a JSON object with:
- "ticker": the stock ticker symbol (e.g. "NVDA")
- "short_description": 1-2 sentence description of what the company does
- "sector": the sector (e.g. "Technology", "Finance", "Healthcare")
- "impact_types": array of which impact types this company depends on. Choose from: "macro", "sector", "crypto_equity", "single_stock". Can be multiple, e.g. ["macro", "sector"].

Return ONLY valid JSON, no markdown fences.`;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await ai.models.generateContent({
        model: "gemini-3-flash-preview",
        contents: prompt,
        config: {
          tools: [{ googleSearch: {} }],
          temperature: 0,
          responseMimeType: "application/json",
        },
      });

      const text = response.text ?? "";
      const parsed = JSON.parse(text) as {
        ticker?: string;
        short_description?: string;
        sector?: string;
        impact_types?: string[];
      };
      const validImpactTypes = ["macro", "sector", "crypto_equity", "single_stock"];
      const impact_types = (parsed.impact_types || [])
        .filter((t: unknown) => typeof t === "string" && validImpactTypes.includes(t));

      return {
        ticker: parsed.ticker && String(parsed.ticker).trim() ? String(parsed.ticker).trim() : null,
        short_description:
          parsed.short_description && String(parsed.short_description).trim()
            ? String(parsed.short_description).trim()
            : null,
        sector:
          parsed.sector && String(parsed.sector).trim()
            ? String(parsed.sector).trim()
            : null,
        impact_types,
      };
    } catch (err: unknown) {
      const status =
        err instanceof Error && "status" in err
          ? (err as { status: number }).status
          : 0;
      const isRetryable = status === 429 || status >= 500;

      if (isRetryable && attempt < MAX_RETRIES) {
        const wait = RETRY_BACKOFF_BASE_S ** attempt;
        await new Promise((r) => setTimeout(r, wait * 1000));
        continue;
      }
      throw err;
    }
  }
  throw new Error("Gemini retries exhausted");
}

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    if (!id) {
      return NextResponse.json({ error: "stock id required" }, { status: 400 });
    }

    const supabase = createServerClient();

    const { data: stock, error: stockError } = await supabase
      .from("stocks")
      .select("*")
      .eq("id", id)
      .single();

    if (stockError || !stock) {
      return NextResponse.json({ error: "Stock not found" }, { status: 404 });
    }

    if (stock.status === "ready") {
      return NextResponse.json(stock);
    }

    const name = stock.name as string;

    // Step 1: Enrich description
    const enriched = await enrichDescription(name);

    await supabase
      .from("stocks")
      .update({
        ticker: enriched.ticker,
        short_description: enriched.short_description,
        sector: enriched.sector,
        impact_types: enriched.impact_types,
        enrich_progress: { step: "filtering_markets", current: 0, total: 0 },
      })
      .eq("id", id);

    const stockInfo: StockInfo = {
      id,
      name,
      ticker: enriched.ticker,
      sector: enriched.sector,
      impact_types: enriched.impact_types,
    };

    if (stockInfo.impact_types.length === 0) {
      await supabase
        .from("stocks")
        .update({ status: "ready", enrich_progress: null })
        .eq("id", id);
      return NextResponse.json(
        await supabase.from("stocks").select("*").eq("id", id).single().then((r) => r.data)
      );
    }

    // Step 2: Fetch candidate events
    const { data: efRows } = await supabase
      .from("event_filtering")
      .select("event_id, impact_type")
      .eq("relevant", true)
      .in("impact_type", stockInfo.impact_types);

    const candidateEvents = efRows || [];
    const total = candidateEvents.length;

    await supabase
      .from("stocks")
      .update({
        enrich_progress: { step: "filtering_markets", current: 0, total },
      })
      .eq("id", id);

    let processed = 0;
    for (const row of candidateEvents) {
      const eventId = row.event_id as string;
      const impactType = row.impact_type as string;

      const { data: eventRow } = await supabase
        .from("polymarket_events")
        .select("id, title, description")
        .eq("id", eventId)
        .single();

      const { data: marketRows } = await supabase
        .from("polymarket_markets")
        .select("question")
        .eq("event_id", eventId);

      const marketQuestions = (marketRows || [])
        .map((m) => m.question)
        .filter(Boolean) as string[];

      const eventInfo: EventInfo = {
        event_id: eventId,
        impact_type: impactType,
        title: eventRow?.title ?? "",
        description: eventRow?.description ?? null,
        market_questions: marketQuestions,
      };

      let shouldInsert = false;
      let reasoning = "";

      if (impactType === "single_stock") {
        const result = matchSingleStock(stockInfo, eventInfo);
        shouldInsert = result.matches;
        reasoning = result.reasoning;
      } else if (
        impactType === "macro" ||
        impactType === "sector" ||
        impactType === "crypto_equity"
      ) {
        const result = await classifyWithLLM(
          impactType as "macro" | "sector" | "crypto_equity",
          stockInfo,
          eventInfo
        );
        shouldInsert = result.affects;
        reasoning = result.reasoning;
      }

      if (shouldInsert) {
        await supabase.from("event_stock_mappings").upsert(
          {
            event_id: eventId,
            stock_id: id,
            reasoning,
            relevance_score: 0.8,
          },
          { onConflict: "event_id,stock_id" }
        );
      }

      processed++;
      if (processed % 5 === 0 || processed === total) {
        await supabase
          .from("stocks")
          .update({
            enrich_progress: {
              step: "filtering_markets",
              current: processed,
              total,
            },
          })
          .eq("id", id);
      }
    }

    await supabase
      .from("stocks")
      .update({ status: "ready", enrich_progress: null })
      .eq("id", id);

    const { data: finalStock } = await supabase
      .from("stocks")
      .select("*")
      .eq("id", id)
      .single();

    return NextResponse.json(finalStock);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Internal error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
