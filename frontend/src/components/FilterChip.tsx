// Figma: Filter chip 199:1316 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";

export interface FilterChipProps {
  children: ReactNode;
  active?: boolean;
  removable?: boolean;
  onRemove?: () => void;
  onClick?: () => void;
}

export function FilterChip({
  children,
  active = false,
  removable = false,
  onRemove,
  onClick,
}: FilterChipProps) {
  return (
    <span
      className={`inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-0.5 text-xs transition-colors duration-[var(--sp-duration-fast)] focus-within:ring-2 focus-within:ring-focus ${
        active
          ? "border-focus bg-selected text-ink-brand"
          : "border-line bg-surface text-ink-muted hover:bg-hover hover:text-ink"
      }`}
    >
      <button
        type="button"
        onClick={onClick}
        className="focus-visible:outline-none"
      >
        {children}
      </button>
      {removable && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove filter"
          className="rounded-xs hover:opacity-70 focus-visible:ring-2 focus-visible:ring-focus"
        >
          <svg viewBox="0 0 12 12" className="h-2.5 w-2.5">
            <path
              d="M2.5 2.5l7 7M9.5 2.5l-7 7"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      )}
    </span>
  );
}
