"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

type EnrichProgress = {
  step?: "description" | "filtering_markets";
  current?: number;
  total?: number;
};

interface Stock {
  id: string;
  ticker: string | null;
  name: string;
  short_description: string | null;
  sector: string | null;
  status?: string | null;
  enrich_progress?: EnrichProgress | null;
  created_at: string;
}

export default function StocksPage() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStocks = useCallback(async () => {
    setLoading(true);
    const { data, error } = await supabase
      .from("stocks")
      .select("*")
      .eq("is_active", true)
      .order("created_at", { ascending: false });

    if (error) console.error("Failed to fetch stocks:", error);
    setStocks((data ?? []) as Stock[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchStocks();
  }, [fetchStocks]);

  useEffect(() => {
    const channel = supabase
      .channel("stocks-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "stocks" },
        (payload) => {
          if (payload.eventType === "INSERT") {
            setStocks((prev) => {
              const newRow = payload.new as Stock;
              if (prev.some((s) => s.id === newRow.id)) return prev;
              return [newRow, ...prev];
            });
          } else if (payload.eventType === "UPDATE") {
            setStocks((prev) =>
              prev.map((s) =>
                s.id === (payload.new as Stock).id
                  ? (payload.new as Stock)
                  : s
              )
            );
          } else if (payload.eventType === "DELETE") {
            setStocks((prev) =>
              prev.filter((s) => s.id !== (payload.old as { id: string }).id)
            );
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;

    setAdding(true);
    setError(null);

    try {
      const res = await fetch("/api/stocks/enrich", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `Request failed (${res.status})`);
      }

      const newStock = (await res.json()) as Stock;
      setName("");
      setStocks((prev) => {
        if (prev.some((s) => s.id === newStock.id)) return prev;
        return [newStock, ...prev];
      });

      fetch(`/api/stocks/${newStock.id}/enrich`, {
        method: "POST",
      }).catch((err) => console.error("Enrich trigger failed:", err));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(id: string) {
    const { error } = await supabase.from("stocks").delete().eq("id", id);
    if (error) {
      console.error("Failed to delete stock:", error);
      return;
    }
    setStocks((prev) => prev.filter((s) => s.id !== id));
  }

  function getEnrichingLabel(stock: Stock): string | null {
    if (stock.status !== "enriching") return null;
    const p = stock.enrich_progress;
    if (!p) return "Generating description for stock...";
    if (p.step === "description") return "Generating description for stock...";
    if (p.step === "filtering_markets" && p.total != null) {
      const cur = p.current ?? 0;
      return `Filtering equity markets (${cur} / ${p.total})`;
    }
    return "Generating description for stock...";
  }

  return (
    <div>
      <form onSubmit={handleAdd} className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Company name (e.g. NVIDIA)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-10 flex-1 rounded-lg border border-border bg-white px-4 text-sm outline-none placeholder:text-muted focus:border-accent focus:ring-1 focus:ring-accent"
        />
        <button
          type="submit"
          disabled={adding || !name.trim()}
          className="h-10 rounded-lg bg-accent px-5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
        >
          {adding ? "Adding..." : "Add"}
        </button>
      </form>

      {error && (
        <p className="mt-2 text-sm text-red-600">{error}</p>
      )}

      {loading ? (
        <p className="py-12 text-center text-muted">Loading stocks...</p>
      ) : stocks.length === 0 ? (
        <p className="py-12 text-center text-muted">
          No stocks in universe yet. Add one above.
        </p>
      ) : (
        <div className="mt-4 divide-y divide-border rounded-lg border border-border">
          {stocks.map((stock) => {
            const isEnriching = stock.status === "enriching";
            const enrichingLabel = getEnrichingLabel(stock);

            return (
              <div
                key={stock.id}
                className={`flex items-center justify-between gap-4 px-5 py-4 ${isEnriching ? "opacity-75" : ""}`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{stock.name}</span>
                    {stock.ticker && (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                        {stock.ticker}
                      </span>
                    )}
                    {stock.sector && (
                      <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                        {stock.sector}
                      </span>
                    )}
                  </div>
                  {enrichingLabel ? (
                    <p className="mt-1 text-sm text-muted/80 italic">
                      {enrichingLabel}
                    </p>
                  ) : (
                    stock.short_description && (
                      <p className="mt-1 text-sm text-muted">
                        {stock.short_description}
                      </p>
                    )
                  )}
                </div>
                <button
                  onClick={() => handleDelete(stock.id)}
                  className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:border-red-300 hover:text-red-600"
                >
                  Delete
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
