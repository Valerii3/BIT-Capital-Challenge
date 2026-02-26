"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { EventFilters, type Filters } from "@/components/event-filters";
import { Pagination } from "@/components/pagination";

const PAGE_SIZE = 20;

const IMPACT_LABELS: Record<string, string> = {
  macro: "Macro",
  sector: "Sector",
  single_stock: "Single Stock",
  crypto_equity: "Crypto Equity",
  non_equity: "Non-Equity",
};

interface EventRow {
  id: string;
  title: string;
  description: string | null;
  active: boolean;
  volume: number | null;
  updated_at: string;
  event_filtering: {
    prefilter_passed: boolean;
    relevant: boolean | null;
    relevance_score: number | null;
    impact_type: string | null;
    theme_labels: string[] | null;
  } | null;
  polymarket_markets: {
    id: string;
    question: string | null;
    outcomes: string | null;
    outcome_prices: string | null;
    volume_num: number | null;
  }[];
}

const defaultFilters: Filters = {
  search: "",
  active: null,
  prefilterPassed: null,
  impactTypes: [],
  themeLabels: [],
};

export default function EventsPage() {
  const [events, setEvents] = useState<EventRow[]>([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Filters>(defaultFilters);

  const fetchEvents = useCallback(async () => {
    setLoading(true);

    let query = supabase
      .from("polymarket_events")
      .select(
        `*, event_filtering(*), polymarket_markets(id, question, outcomes, outcome_prices, volume_num)`,
        { count: "exact" }
      )
      .order("updated_at", { ascending: false })
      .range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1);

    if (filters.search) {
      query = query.ilike("title", `%${filters.search}%`);
    }
    if (filters.active !== null) {
      query = query.eq("active", filters.active);
    }
    if (filters.prefilterPassed !== null) {
      query = query.not("event_filtering", "is", null);
      query = query.eq(
        "event_filtering.prefilter_passed",
        filters.prefilterPassed
      );
    }
    if (filters.impactTypes.length > 0) {
      query = query.in("event_filtering.impact_type", filters.impactTypes);
    }
    if (filters.themeLabels.length > 0) {
      query = query.contains("event_filtering.theme_labels", filters.themeLabels);
    }

    const { data, count, error } = await query;

    if (error) {
      console.error("Failed to fetch events:", error);
    }

    let rows = (data ?? []) as unknown as EventRow[];

    if (filters.prefilterPassed !== null) {
      rows = rows.filter(
        (e) => e.event_filtering?.prefilter_passed === filters.prefilterPassed
      );
    }
    if (filters.impactTypes.length > 0) {
      rows = rows.filter(
        (e) =>
          e.event_filtering?.impact_type &&
          filters.impactTypes.includes(e.event_filtering.impact_type)
      );
    }
    if (filters.themeLabels.length > 0) {
      rows = rows.filter((e) => {
        const labels = e.event_filtering?.theme_labels ?? [];
        return filters.themeLabels.some((l) => labels.includes(l));
      });
    }

    setEvents(rows);
    setTotal(count ?? 0);
    setLoading(false);
  }, [page, filters]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  useEffect(() => {
    setPage(0);
  }, [filters]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      <EventFilters filters={filters} onChange={setFilters} />

      {loading ? (
        <p className="py-12 text-center text-muted">Loading events...</p>
      ) : events.length === 0 ? (
        <p className="py-12 text-center text-muted">No events found.</p>
      ) : (
        <>
          <div className="mt-4 flex flex-col gap-2">
            {events.map((ev) => (
              <EventCard key={ev.id} event={ev} />
            ))}
          </div>
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        </>
      )}
    </div>
  );
}

function parseJsonArray(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map(String);
    return [];
  } catch {
    return raw
      .replace(/[[\]"]/g, "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
}

function fmtPct(raw: number): string {
  return `${parseFloat((raw * 100).toPrecision(4))}%`;
}

function fmtVol(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

function EventCard({ event }: { event: EventRow }) {
  const [expanded, setExpanded] = useState(false);
  const f = event.event_filtering;
  const markets = (event.polymarket_markets ?? []).filter(
    (m) => m.volume_num != null && m.volume_num >= 100
  );

  return (
    <div
      className="relative flex flex-col gap-2 rounded-lg border border-border bg-white px-5 py-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-400 hover:shadow-[0_0_12px_rgba(37,99,235,0.15)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold leading-snug">{event.title}</h3>
          {event.description && (
            <p
              className={`mt-1 text-sm text-muted ${expanded ? "" : "line-clamp-2"}`}
            >
              {event.description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 text-sm">
          {event.volume != null && (
            <span className="text-xs text-muted">
              Total volume:{" "}
              <span className="font-medium text-foreground">
                ${Number(event.volume).toLocaleString("en-US", { maximumFractionDigits: 0 })}
              </span>
            </span>
          )}
          <span className="text-xs text-muted">
            Last updated:{" "}
            {new Date(event.updated_at).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        {f?.impact_type && (
          <Badge>{IMPACT_LABELS[f.impact_type] ?? f.impact_type}</Badge>
        )}
        {f?.theme_labels?.map((t) => (
          <Badge key={t} variant="blue">
            {t}
          </Badge>
        ))}
        {f?.relevance_score != null && (
          <span className="text-muted">
            score {f.relevance_score.toFixed(2)}
          </span>
        )}
      </div>

      {expanded && markets.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted">
            Markets
          </h4>
          {markets.map((m) => {
            const outcomes = parseJsonArray(m.outcomes);
            const prices = parseJsonArray(m.outcome_prices).map(Number);
            return (
              <div
                key={m.id}
                className="flex items-center gap-3 rounded-lg border border-border bg-gray-50/60 px-3 py-2 text-sm"
              >
                <span className="min-w-0 flex-1 leading-snug">
                  {m.question}
                </span>
                <div className="flex shrink-0 items-center gap-2">
                  {outcomes.map((name, i) => {
                    const isYes = name.toLowerCase() === "yes";
                    const isNo = name.toLowerCase() === "no";
                    const color = isYes
                      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                      : isNo
                        ? "bg-red-50 text-red-600 ring-red-200"
                        : "bg-gray-50 text-gray-700 ring-border";
                    return (
                      <span
                        key={name}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${color}`}
                      >
                        {name} {!isNaN(prices[i]) ? fmtPct(prices[i]) : "—"}
                      </span>
                    );
                  })}
                  {m.volume_num != null && (
                    <span className="text-xs text-muted">
                      {fmtVol(m.volume_num)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {markets.length > 0 && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="mx-auto mt-1 flex h-7 w-7 items-center justify-center rounded-full border border-border text-foreground transition-colors hover:border-accent hover:text-accent"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className={`h-5 w-5 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          >
            <path
              fillRule="evenodd"
              d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
              clipRule="evenodd"
            />
          </svg>
        </button>
      )}
    </div>
  );
}

function Badge({
  children,
  variant = "default",
}: {
  children: React.ReactNode;
  variant?: "default" | "blue";
}) {
  const base = "rounded-full px-2 py-0.5 font-medium";
  const colors =
    variant === "blue"
      ? "bg-blue-50 text-blue-700"
      : "bg-gray-100 text-gray-700";
  return <span className={`${base} ${colors}`}>{children}</span>;
}
