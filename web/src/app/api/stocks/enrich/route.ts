import { NextRequest, NextResponse } from "next/server";
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

  const prompt = `Given the company name "${companyName}", return a JSON object with:
- "ticker": the stock ticker symbol (e.g. "NVDA")
- "short_description": 1-2 sentence description of what the company does
- "sector": the sector (e.g. "Technology", "Finance", "Healthcare")

Return ONLY valid JSON, no markdown fences.`;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            temperature: 0,
            responseMimeType: "application/json",
          },
        }),
      }
    );

    if (res.status === 429 || res.status >= 500) {
      if (attempt === MAX_RETRIES) {
        throw new Error(`Gemini API error ${res.status} after ${MAX_RETRIES} retries`);
      }
      const wait = RETRY_BACKOFF_BASE_S ** attempt;
      await new Promise((r) => setTimeout(r, wait * 1000));
      continue;
    }

    if (!res.ok) {
      throw new Error(`Gemini API error: ${res.status}`);
    }

    const body = await res.json();
    const text =
      body?.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
    return JSON.parse(text);
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
