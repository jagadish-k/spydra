// Figma: Pagination 196:1332 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface PaginationProps {
  page: number;
  pageCount: number;
  onChange?: (page: number) => void;
  summary?: boolean;
}

// First/last/single-page are derived, not passed: they are arithmetic on
// page × pageCount, and a prop for them would drift from the numbers.
export function Pagination({
  page,
  pageCount,
  onChange,
  summary = true,
}: PaginationProps) {
  const single = pageCount <= 1;
  const onFirst = page <= 1;
  const onLast = page >= pageCount;
  const prev = (
    <button
      type="button"
      aria-label="Previous page"
      disabled={single || onFirst}
      onClick={() => onChange?.(page - 1)}
      className="flex h-6 w-6 items-center justify-center rounded-md text-ink-muted hover:bg-subtle hover:text-ink focus-visible:ring-2 focus-visible:ring-focus disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
    >
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
        <path
          d="M10 3L5 8l5 5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
  const next = (
    <button
      type="button"
      aria-label="Next page"
      disabled={single || onLast}
      onClick={() => onChange?.(page + 1)}
      className="flex h-6 w-6 items-center justify-center rounded-md text-ink-muted hover:bg-subtle hover:text-ink focus-visible:ring-2 focus-visible:ring-focus disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
    >
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
        <path
          d="M6 3l5 5-5 5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
  return (
    <nav aria-label="Pagination" className="flex items-center gap-3">
      {prev}
      {summary && (
        <span className="text-xs tabular-nums text-ink-muted">
          Page {page} of {Math.max(pageCount, 1)}
        </span>
      )}
      {next}
    </nav>
  );
}
