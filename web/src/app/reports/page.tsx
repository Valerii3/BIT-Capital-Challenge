"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchBackend } from "@/lib/backend-api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ReportStatus = "pending" | "generating" | "ready" | "failed";
type ReportType = "single_stock" | "macro" | "sector";

const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  single_stock: "Single-Stock",
  macro: "Macro",
  sector: "Sector",
};

function normalizeReportType(value: string | null | undefined): ReportType {
  if (value === "macro") return "macro";
  if (value === "sector") return "sector";
  return "single_stock";
}

interface Report {
  id: string;
  name: string;
  report_type?: ReportType | null;
  stock_ids: string[];
  event_ids: string[];
  content: string | null;
  status: ReportStatus;
  error: string | null;
  created_at: string;
}

interface Stock {
  id: string;
  name: string;
  ticker: string | null;
  sector: string | null;
  status?: string | null;
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: ReportStatus }) {
  const map: Record<ReportStatus, { label: string; className: string }> = {
    pending: {
      label: "Pending",
      className: "bg-gray-100 text-gray-600",
    },
    generating: {
      label: "Generating…",
      className: "bg-yellow-50 text-yellow-700 animate-pulse",
    },
    ready: {
      label: "Ready",
      className: "bg-green-50 text-green-700",
    },
    failed: {
      label: "Failed",
      className: "bg-red-50 text-red-700",
    },
  };
  const { label, className } = map[status] ?? map.pending;
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Markdown-ish renderer — handles # headings and **bold** inline
// ---------------------------------------------------------------------------

function renderLine(line: string, idx: number): React.ReactNode {
  const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
  if (headingMatch) {
    const level = headingMatch[1].length;
    const text = headingMatch[2];
    if (level === 1)
      return (
        <h1 key={idx} className="mb-3 mt-6 text-xl font-bold text-foreground">
          {text}
        </h1>
      );
    if (level === 2)
      return (
        <h2 key={idx} className="mb-2 mt-5 text-base font-bold text-foreground border-b border-border pb-1">
          {text}
        </h2>
      );
    return (
      <h3 key={idx} className="mb-1 mt-4 text-sm font-semibold text-foreground">
        {text}
      </h3>
    );
  }

  if (line.trim() === "" || line.trim() === "---") {
    return <div key={idx} className="my-2" />;
  }

  // Inline bold: **text**
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  const rendered = parts.map((part, pi) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={pi}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });

  const isBullet = line.trimStart().startsWith("- ") || line.trimStart().startsWith("• ");
  if (isBullet) {
    return (
      <li key={idx} className="ml-4 text-sm leading-relaxed text-foreground">
        {rendered}
      </li>
    );
  }

  return (
    <p key={idx} className="text-sm leading-relaxed text-foreground">
      {rendered}
    </p>
  );
}

function ReportContent({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="space-y-0.5">
      {lines.map((line, idx) => renderLine(line, idx))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stock multi-select component used in the create form
// ---------------------------------------------------------------------------

function StockSelector({
  stocks,
  selected,
  onChange,
}: {
  stocks: Stock[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = stocks.filter((s) => {
    const q = search.toLowerCase();
    return (
      s.name.toLowerCase().includes(q) ||
      (s.ticker ?? "").toLowerCase().includes(q)
    );
  });

  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((x) => x !== id));
    } else {
      onChange([...selected, id]);
    }
  }

  const selectedStocks = stocks.filter((s) => selected.includes(s.id));

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-10 w-full items-center justify-between rounded-lg border border-border bg-white px-4 text-sm text-foreground outline-none hover:border-accent"
      >
        <span className={selected.length === 0 ? "text-muted" : ""}>
          {selected.length === 0
            ? "Select stocks to track…"
            : `${selected.length} stock${selected.length > 1 ? "s" : ""} selected`}
        </span>
        <svg
          className={`h-4 w-4 text-muted transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-white shadow-lg">
          <div className="border-b border-border p-2">
            <input
              autoFocus
              type="text"
              placeholder="Search stocks…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-md border border-border px-3 py-1.5 text-sm outline-none focus:border-accent"
            />
          </div>
          <ul className="max-h-56 overflow-y-auto p-1">
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-sm text-muted">No stocks found</li>
            )}
            {filtered.map((s) => {
              const isChecked = selected.includes(s.id);
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => toggle(s.id)}
                    className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-gray-50 ${
                      isChecked ? "font-medium" : ""
                    }`}
                  >
                    <span
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                        isChecked
                          ? "border-accent bg-accent text-white"
                          : "border-border"
                      }`}
                    >
                      {isChecked && (
                        <svg className="h-2.5 w-2.5" fill="currentColor" viewBox="0 0 12 12">
                          <path d="M10 3L5 8.5 2 5.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </span>
                    <span className="flex-1 text-left">{s.name}</span>
                    {s.ticker && (
                      <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                        {s.ticker}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Selected chips */}
      {selectedStocks.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {selectedStocks.map((s) => (
            <span
              key={s.id}
              className="flex items-center gap-1 rounded-full bg-accent/10 px-2.5 py-0.5 text-xs font-medium text-accent"
            >
              {s.name}
              {s.ticker && <span className="opacity-70">({s.ticker})</span>}
              <button
                type="button"
                onClick={() => toggle(s.id)}
                className="ml-0.5 opacity-60 hover:opacity-100"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report card
// ---------------------------------------------------------------------------

function ReportCard({
  report,
  stocksById,
  onDelete,
  onRegenerate,
}: {
  report: Report;
  stocksById: Record<string, Stock>;
  onDelete: (id: string) => void;
  onRegenerate: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isGenerating = report.status === "generating";
  const reportType = normalizeReportType(report.report_type);

  return (
    <div className="rounded-lg border border-border bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-foreground">{report.name}</h3>
            <StatusBadge status={report.status} />
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
              {REPORT_TYPE_LABELS[reportType]}
            </span>
            <span className="text-xs text-muted">{formatDate(report.created_at)}</span>
          </div>

          {/* Stock badges + event count */}
          {report.stock_ids.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {report.stock_ids.map((sid) => {
                const s = stocksById[sid];
                return (
                  <span
                    key={sid}
                    className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700"
                  >
                    {s ? s.name : sid.slice(0, 8)}
                    {s?.ticker && (
                      <span className="ml-1 opacity-60">({s.ticker})</span>
                    )}
                  </span>
                );
              })}
              {report.event_ids?.length > 0 && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                  {report.event_ids.length} event{report.event_ids.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex shrink-0 items-center gap-2">
          {!isGenerating && (
            <button
              onClick={() => onRegenerate(report.id)}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:border-accent hover:text-accent"
            >
              Regenerate
            </button>
          )}
          <button
            onClick={() => onDelete(report.id)}
            disabled={isGenerating}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition-colors hover:border-red-300 hover:text-red-600 disabled:opacity-40"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Error */}
      {report.status === "failed" && report.error && (
        <p className="mt-3 text-sm text-red-600">{report.error}</p>
      )}

      {/* Generating spinner */}
      {isGenerating && (
        <p className="mt-3 text-sm italic text-muted">
          Analysing markets and generating {REPORT_TYPE_LABELS[reportType].toLowerCase()} report…
        </p>
      )}

      {/* Content preview / expand */}
      {report.status === "ready" && report.content && (
        <div className="mt-4">
          {!expanded && (
            <p className="line-clamp-3 text-sm text-muted">{report.content}</p>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 flex items-center gap-1 text-sm font-medium text-accent hover:underline"
          >
            {expanded ? (
              <>
                Collapse
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                </svg>
              </>
            ) : (
              <>
                Read full report
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </>
            )}
          </button>

          {expanded && (
            <div className="mt-4 rounded-lg border border-border bg-gray-50/60 p-5">
              <ReportContent content={report.content} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);

  const [reportName, setReportName] = useState("");
  const [selectedStockIds, setSelectedStockIds] = useState<string[]>([]);
  const [creatingType, setCreatingType] = useState<ReportType | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const creating = creatingType !== null;

  // Build a quick lookup map
  const stocksById: Record<string, Stock> = {};
  for (const s of stocks) stocksById[s.id] = s;

  // Fetch all reports
  const fetchReports = useCallback(async () => {
    try {
      const data = await fetchBackend<Report[]>("/reports");
      setReports(
        (data ?? []).map((report) => ({
          ...report,
          report_type: normalizeReportType(report.report_type),
        }))
      );
    } catch (err) {
      console.error("Failed to fetch reports:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch stocks for the selector
  useEffect(() => {
    fetchBackend<Stock[]>("/stocks")
      .then((data) => setStocks(data ?? []))
      .catch(console.error);
  }, []);

  // Initial load + polling while any report is generating
  useEffect(() => {
    void fetchReports();
  }, [fetchReports]);

  useEffect(() => {
    const hasGenerating = reports.some((r) => r.status === "generating");
    if (!hasGenerating) return;
    const id = setInterval(() => void fetchReports(), 3000);
    return () => clearInterval(id);
  }, [reports, fetchReports]);

  // Create + immediately generate
  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = reportName.trim();
    if (!trimmed || selectedStockIds.length === 0) return;
    const native = e.nativeEvent as SubmitEvent;
    const submitter = native.submitter as HTMLButtonElement | null;
    const reportType: ReportType =
      submitter?.value === "macro"
        ? "macro"
        : submitter?.value === "sector"
          ? "sector"
          : "single_stock";

    setCreatingType(reportType);
    setFormError(null);

    try {
      // 1. Create the report record
      const created = await fetchBackend<Report>("/reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmed,
          stock_ids: selectedStockIds,
          report_type: reportType,
        }),
      });
      setReportName("");
      setSelectedStockIds([]);
      // Insert optimistically as "generating" while the real call runs
      setReports((prev) => [
        {
          ...created,
          report_type: normalizeReportType(created.report_type ?? reportType),
          status: "generating",
        },
        ...prev,
      ]);

      // 2. Generate (blocks until Gemini responds)
      const generated = await fetchBackend<Report>(
        `/reports/${created.id}/generate`,
        { method: "POST" }
      );
      setReports((prev) =>
        prev.map((r) =>
          r.id === generated.id
            ? {
                ...generated,
                report_type: normalizeReportType(generated.report_type),
              }
            : r
        )
      );
    } catch (err: unknown) {
      setFormError(
        err instanceof Error ? err.message : "Something went wrong"
      );
      // Refresh to get accurate statuses
      void fetchReports();
    } finally {
      setCreatingType(null);
    }
  }

  async function handleDelete(id: string) {
    try {
      await fetchBackend<{ status: string }>(`/reports/${id}`, {
        method: "DELETE",
      });
      setReports((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      console.error("Failed to delete report:", err);
    }
  }

  async function handleRegenerate(id: string) {
    // Optimistically mark as generating
    setReports((prev) =>
      prev.map((r) => (r.id === id ? { ...r, status: "generating" } : r))
    );
    try {
      const updated = await fetchBackend<Report>(`/reports/${id}/generate`, {
        method: "POST",
      });
      setReports((prev) =>
        prev.map((r) =>
          r.id === updated.id
            ? {
                ...updated,
                report_type: normalizeReportType(updated.report_type),
              }
            : r
        )
      );
    } catch (err) {
      console.error("Regeneration failed:", err);
      void fetchReports();
    }
  }

  const readyStocks = stocks.filter(
    (s) => s.status === "ready" || !s.status
  );

  return (
    <div className="space-y-6">
      {/* Create form */}
      <div className="rounded-lg border border-border bg-white p-5 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">New Report</h2>
        <form onSubmit={handleCreate} className="space-y-3">
          <input
            type="text"
            placeholder="Report name (e.g. NVDA Deep Dive — Feb 2026)"
            value={reportName}
            onChange={(e) => setReportName(e.target.value)}
            className="h-10 w-full rounded-lg border border-border bg-white px-4 text-sm outline-none placeholder:text-muted focus:border-accent focus:ring-1 focus:ring-accent"
          />

          {readyStocks.length === 0 ? (
            <p className="text-sm text-muted">
              No enriched stocks available. Add stocks on the Stocks tab first.
            </p>
          ) : (
            <StockSelector
              stocks={readyStocks}
              selected={selectedStockIds}
              onChange={setSelectedStockIds}
            />
          )}

          {formError && (
            <p className="text-sm text-red-600">{formError}</p>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              value="single_stock"
              disabled={
                creating ||
                !reportName.trim() ||
                selectedStockIds.length === 0
              }
              className="h-10 rounded-lg bg-accent px-6 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
            >
              {creatingType === "single_stock"
                ? "Generating single-stock report…"
                : "Generate Single-Stock Report"}
            </button>
            <button
              type="submit"
              value="macro"
              disabled={
                creating ||
                !reportName.trim() ||
                selectedStockIds.length === 0
              }
              className="h-10 rounded-lg bg-emerald-600 px-6 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
            >
              {creatingType === "macro"
                ? "Generating macro report…"
                : "Generate Macro Report"}
            </button>
            <button
              type="submit"
              value="sector"
              disabled={
                creating ||
                !reportName.trim() ||
                selectedStockIds.length === 0
              }
              className="h-10 rounded-lg bg-amber-600 px-6 text-sm font-medium text-white transition-colors hover:bg-amber-700 disabled:opacity-50"
            >
              {creatingType === "sector"
                ? "Generating sector report…"
                : "Generate Sector Report"}
            </button>
          </div>
        </form>
      </div>

      {/* Report list */}
      {loading ? (
        <p className="py-12 text-center text-muted">Loading reports…</p>
      ) : reports.length === 0 ? (
        <p className="py-12 text-center text-muted">
          No reports yet. Create one above.
        </p>
      ) : (
        <div className="space-y-4">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              stocksById={stocksById}
              onDelete={handleDelete}
              onRegenerate={handleRegenerate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
