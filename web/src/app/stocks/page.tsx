"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

interface Stock {
  id: string;
  ticker: string | null;
  name: string;
  short_description: string | null;
  sector: string | null;
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

      setName("");
      await fetchStocks();
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
          {stocks.map((stock) => (
            <div
              key={stock.id}
              className="flex items-center justify-between gap-4 px-5 py-4"
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
                {stock.short_description && (
                  <p className="mt-1 text-sm text-muted">
                    {stock.short_description}
                  </p>
                )}
              </div>
              <button
                onClick={() => handleDelete(stock.id)}
                className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:border-red-300 hover:text-red-600"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
