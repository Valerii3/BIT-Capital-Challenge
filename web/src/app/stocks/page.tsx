"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBackend } from "@/lib/backend-api";

type EnrichProgress = {
  step?: "description" | "filtering_markets" | "failed";
  current?: number;
  total?: number;
  error?: string;
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
    try {
      const data = await fetchBackend<Stock[]>("/stocks");
      setStocks(data ?? []);
    } catch (err) {
      console.error("Failed to fetch stocks:", err);
      setStocks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStocks();

    const intervalId = setInterval(() => {
      void fetchStocks();
    }, 5000);

    return () => {
      clearInterval(intervalId);
    };
  }, [fetchStocks]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;

    setAdding(true);
    setError(null);

    try {
      const newStock = await fetchBackend<Stock>("/stocks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmed }),
      });

      setName("");
      setStocks((prev) => {
        if (prev.some((s) => s.id === newStock.id)) return prev;
        return [newStock, ...prev];
      });

      fetchBackend<Stock>(`/stocks/${newStock.id}/enrich`, {
        method: "POST",
      }).catch((err) => {
        console.error("Enrich trigger failed:", err);
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await fetchBackend<{ status: string }>(`/stocks/${id}`, {
        method: "DELETE",
      });
      setStocks((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      console.error("Failed to delete stock:", err);
    }
  }

  function getEnrichingLabel(stock: Stock): string | null {
    if (stock.status !== "enriching" && stock.status !== "failed") return null;

    if (stock.status === "failed") {
      return stock.enrich_progress?.error ?? "Enrichment failed";
    }

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
            const isBusy = stock.status === "enriching";
            const isFailed = stock.status === "failed";
            const enrichingLabel = getEnrichingLabel(stock);

            return (
              <div
                key={stock.id}
                className={`flex items-center justify-between gap-4 px-5 py-4 ${isBusy ? "opacity-75" : ""}`}
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
                    <p className={`mt-1 text-sm italic ${isFailed ? "text-red-600" : "text-muted/80"}`}>
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
