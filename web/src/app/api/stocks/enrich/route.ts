import { NextRequest, NextResponse } from "next/server";
import { GoogleGenAI } from "@google/genai";
import { createServerClient } from "@/lib/supabase-server";

const MAX_RETRIES = 4;
const RETRY_BACKOFF_BASE_S = 2;

async function callGemini(companyName: string): Promise<{
  ticker: string;
  short_description: string;
  sector: string;
}> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error("GEMINI_API_KEY not configured");

  const ai = new GoogleGenAI({ apiKey });

  const prompt = `Given the company name "${companyName}", return a JSON object with:
- "ticker": the stock ticker symbol (e.g. "NVDA")
- "short_description": 1-2 sentence description of what the company does
- "sector": the sector (e.g. "Technology", "Finance", "Healthcare")

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
      return JSON.parse(text);
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

export async function POST(request: NextRequest) {
  try {
    const { name } = await request.json();
    if (!name || typeof name !== "string" || !name.trim()) {
      return NextResponse.json(
        { error: "name is required" },
        { status: 400 }
      );
    }

    const enriched = await callGemini(name.trim());
    const supabase = createServerClient();

    const { data, error } = await supabase
      .from("stocks")
      .insert({
        name: name.trim(),
        ticker: enriched.ticker || null,
        short_description: enriched.short_description || null,
        sector: enriched.sector || null,
      })
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json(data);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Internal error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
