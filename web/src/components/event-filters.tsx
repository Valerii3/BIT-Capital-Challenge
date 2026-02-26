"use client";

import { useState } from "react";

export interface Filters {
  search: string;
  active: boolean | null;
  prefilterPassed: boolean | null;
  impactTypes: string[];
  themeLabels: string[];
}

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
    filters.themeLabels.length;

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
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
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
