// Figma: Search field 199:1339 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface SearchFieldProps {
  value: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  /** The no-results arm — a query that ran and found nothing. */
  noResults?: boolean;
}

export function SearchField({
  value,
  onChange,
  placeholder = "Search",
  noResults = false,
}: SearchFieldProps) {
  return (
    <div className="flex h-[30px] min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-surface px-3 transition-colors focus-within:border-line-strong focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-1">
      <svg
        viewBox="0 0 16 16"
        className="h-3.5 w-3.5 shrink-0 text-ink-subtle"
        aria-hidden="true"
      >
        <circle
          cx="7"
          cy="7"
          r="4.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="M10.5 10.5L14 14"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange?.(event.target.value)}
        className="w-full min-w-0 flex-1 bg-transparent text-md text-ink outline-none placeholder:text-ink-subtle"
      />
      {noResults && value.length > 0 && (
        <span className="shrink-0 text-2xs text-ink-subtle">no results</span>
      )}
      {value.length > 0 && (
        <button
          type="button"
          onClick={() => onChange?.("")}
          aria-label="Clear search"
          className="shrink-0 rounded-xs text-ink-subtle hover:text-ink focus-visible:ring-2 focus-visible:ring-focus"
        >
          <svg viewBox="0 0 12 12" className="h-3 w-3">
            <path
              d="M2.5 2.5l7 7M9.5 2.5l-7 7"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
