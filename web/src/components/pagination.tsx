"use client";

interface Props {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, totalPages, onChange }: Props) {
  if (totalPages <= 1) return null;

  return (
    <div className="mt-4 flex items-center justify-between">
      <span className="text-sm text-muted">
        Page {page + 1} of {totalPages}
      </span>
      <div className="flex gap-2">
        <button
          disabled={page === 0}
          onClick={() => onChange(page - 1)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:border-gray-400 disabled:opacity-40 disabled:hover:border-border"
        >
          Previous
        </button>
        <button
          disabled={page >= totalPages - 1}
          onClick={() => onChange(page + 1)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:border-gray-400 disabled:opacity-40 disabled:hover:border-border"
        >
          Next
        </button>
      </div>
    </div>
  );
}
