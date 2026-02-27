"use client";

import { useCallback, useState } from "react";
import { fetchBackend } from "@/lib/backend-api";

export type SortOption =
  | "recent"
  | "volume_desc"
  | "volume_asc"
  | "score_desc"
  | "score_asc";

export interface Filters {
  search: string;
  active: boolean | null;
  prefilterPassed: boolean | null;
  impactTypes: string[];
  themeLabels: string[];
  stockIds: string[];
  sort: SortOption;
}

interface Stock {
  id: string;
  name: string;
  ticker: string | null;
}

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "recent", label: "Most recent" },
  { value: "volume_desc", label: "Volume: high → low" },
  { value: "volume_asc", label: "Volume: low → high" },
  { value: "score_desc", label: "Score: high → low" },
  { value: "score_asc", label: "Score: low → high" },
];

const IMPACT_OPTIONS = [
  { value: "macro", label: "Macro" },
  { value: "sector", label: "Sector" },
  { value: "single_stock", label: "Single Stock" },
  { value: "crypto_equity", label: "Crypto Equity" },
  { value: "non_equity", label: "Non-Equity" },
];

const THEME_OPTIONS = [
  { value: "rates_fed", label: "Rates / Fed" },
  { value: "trade_tariffs", label: "Trade / Tariffs" },
  { value: "ai_capex", label: "AI Capex" },
  { value: "dc_power", label: "Datacenters / Power" },
  { value: "semis_supply", label: "Semis Supply" },
  { value: "crypto_reg", label: "Crypto Regulation" },
  { value: "crypto_equity", label: "Crypto Equity" },
  { value: "geopolitics", label: "Geopolitics" },
  { value: "health", label: "Health / Biotech" },
];

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
}

export function EventFilters({ filters, onChange }: Props) {
  const [open, setOpen] = useState(false);

  const activeCount =
    (filters.active !== null ? 1 : 0) +
    (filters.prefilterPassed !== null ? 1 : 0) +
    filters.impactTypes.length +
    filters.themeLabels.length +
    filters.stockIds.length;

  return (
    <div>
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Search events..."
          value={filters.search}
          onChange={(e) => onChange({ ...filters, search: e.target.value })}
          className="h-10 flex-1 rounded-lg border border-border bg-white px-4 text-sm outline-none placeholder:text-muted focus:border-accent focus:ring-1 focus:ring-accent"
        />
        <select
          value={filters.sort}
          onChange={(e) =>
            onChange({ ...filters, sort: e.target.value as SortOption })
          }
          className={`h-10 appearance-none rounded-lg border bg-white px-3 pr-8 text-sm font-medium outline-none transition-colors ${
            filters.sort !== "recent"
              ? "border-accent text-accent"
              : "border-border text-foreground"
          }`}
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16' fill='%236b7280'%3E%3Cpath fill-rule='evenodd' d='M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z' clip-rule='evenodd'/%3E%3C/svg%3E")`,
            backgroundRepeat: "no-repeat",
            backgroundPosition: "right 0.5rem center",
          }}
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <button
          onClick={() => setOpen((o) => !o)}
          className={`relative h-10 rounded-lg border px-4 text-sm font-medium transition-colors ${
            open || activeCount > 0
              ? "border-accent bg-blue-50 text-accent"
              : "border-border text-foreground hover:border-gray-400"
          }`}
        >
          Filters
          {activeCount > 0 && (
            <span className="ml-1.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[10px] font-bold text-white">
              {activeCount}
            </span>
          )}
        </button>
      </div>

      {open && (
        <div className="mt-3 rounded-lg border border-border bg-white p-5">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <FilterSection title="Status">
              <TriToggle
                label="Active"
                value={filters.active}
                onChange={(v) => onChange({ ...filters, active: v })}
              />
            </FilterSection>

            <FilterSection title="Prefilter">
              <TriToggle
                label="Passed"
                value={filters.prefilterPassed}
                onChange={(v) => onChange({ ...filters, prefilterPassed: v })}
              />
            </FilterSection>

            <FilterSection title="Impact Type">
              {IMPACT_OPTIONS.map((opt) => (
                <Checkbox
                  key={opt.value}
                  label={opt.label}
                  checked={filters.impactTypes.includes(opt.value)}
                  onChange={(checked) =>
                    onChange({
                      ...filters,
                      impactTypes: checked
                        ? [...filters.impactTypes, opt.value]
                        : filters.impactTypes.filter((v) => v !== opt.value),
                    })
                  }
                />
              ))}
            </FilterSection>

            <FilterSection title="Themes">
              {THEME_OPTIONS.map((opt) => (
                <Checkbox
                  key={opt.value}
                  label={opt.label}
                  checked={filters.themeLabels.includes(opt.value)}
                  onChange={(checked) =>
                    onChange({
                      ...filters,
                      themeLabels: checked
                        ? [...filters.themeLabels, opt.value]
                        : filters.themeLabels.filter((v) => v !== opt.value),
                    })
                  }
                />
              ))}
            </FilterSection>

            <FilterSection title="Stock" className="sm:col-span-2">
              <StockFilter
                selectedIds={filters.stockIds}
                onSelect={(ids) => onChange({ ...filters, stockIds: ids })}
              />
            </FilterSection>
          </div>

          {activeCount > 0 && (
            <button
              onClick={() =>
                onChange({
                  search: filters.search,
                  active: null,
                  prefilterPassed: null,
                  impactTypes: [],
                  themeLabels: [],
                  stockIds: [],
                  sort: filters.sort,
                })
              }
              className="mt-4 text-sm text-accent hover:underline"
            >
              Clear all filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function FilterSection({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
        {title}
      </h4>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}

function TriToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | null;
  onChange: (v: boolean | null) => void;
}) {
  const options: { v: boolean | null; label: string }[] = [
    { v: null, label: "All" },
    { v: true, label: `${label}: Yes` },
    { v: false, label: `${label}: No` },
  ];
  return (
    <div className="flex gap-1">
      {options.map((opt) => (
        <button
          key={String(opt.v)}
          onClick={() => onChange(opt.v)}
          className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
            value === opt.v
              ? "bg-accent text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-border accent-accent"
      />
      {label}
    </label>
  );
}

function StockFilter({
  selectedIds,
  onSelect,
}: {
  selectedIds: string[];
  onSelect: (ids: string[]) => void;
}) {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchStocks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBackend<Stock[]>("/stocks");
      setStocks(data);
    } catch (error) {
      console.error("Failed to fetch stocks:", error);
      setStocks([]);
    }
    setLoading(false);
  }, []);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? stocks.filter(
        (s) =>
          (s.name || "").toLowerCase().includes(q) ||
          (s.ticker || "").toLowerCase().includes(q)
      )
    : stocks;

  const selectedStocks = stocks.filter((s) => selectedIds.includes(s.id));

  function addStock(stock: Stock) {
    if (selectedIds.includes(stock.id)) return;
    onSelect([...selectedIds, stock.id]);
  }

  function removeStock(id: string) {
    onSelect(selectedIds.filter((sid) => sid !== id));
  }

  return (
    <div className="relative">
      <div className="flex flex-wrap gap-1.5">
        {selectedStocks.map((s) => (
          <span
            key={s.id}
            className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700"
          >
            {s.ticker ? `${s.name} (${s.ticker})` : s.name}
            <button
              type="button"
              onClick={() => removeStock(s.id)}
              className="rounded-full p-0.5 hover:bg-blue-200"
              aria-label="Remove"
            >
              <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </span>
        ))}
      </div>
      <div className="mt-2">
        <input
          type="text"
          placeholder="Type to search stocks..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            setOpen(true);
            if (!loading && stocks.length === 0) {
              void fetchStocks();
            }
          }}
          className="h-9 w-full rounded-lg border border-border bg-white px-3 text-sm outline-none placeholder:text-muted focus:border-accent focus:ring-1 focus:ring-accent"
        />
        {open && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={() => setOpen(false)}
              aria-hidden="true"
            />
            <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-48 overflow-auto rounded-lg border border-border bg-white shadow-lg">
              {loading ? (
                <p className="px-3 py-2 text-sm text-muted">Loading...</p>
              ) : filtered.length === 0 ? (
                <p className="px-3 py-2 text-sm text-muted">No stocks found</p>
              ) : (
                filtered.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      addStock(s);
                      setQuery("");
                      setOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                      selectedIds.includes(s.id) ? "bg-blue-50 text-blue-700" : ""
                    }`}
                  >
                    <span className="font-medium">{s.name}</span>
                    {s.ticker && (
                      <span className="text-xs text-muted">{s.ticker}</span>
                    )}
                  </button>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
