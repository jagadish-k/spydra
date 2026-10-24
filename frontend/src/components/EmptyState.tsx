// Figma: Empty state — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";
import { Button } from "./Button";

export type EmptyKind = "first-run" | "filtered" | "no-results";

// First-run offers the primary action; filtered must never offer to create —
// the data exists and the filter is hiding it (UI_STATES §1).
const KIND_ICONS: Record<EmptyKind, ReactNode> = {
  "first-run": (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <circle
        cx="16"
        cy="16"
        r="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M16 10v12M10 16h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
  filtered: (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <path
        d="M5 8h22l-8.5 10v7l-5 2.5V18Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  ),
  "no-results": (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <circle
        cx="14"
        cy="14"
        r="9"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M21 21L27 27M10 14h8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
};

export interface EmptyStateProps {
  kind: EmptyKind;
  title: string;
  body?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  kind,
  title,
  body,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="px-4 py-12 text-center text-ink-subtle">
      <div className="mb-3 flex justify-center opacity-50">
        {KIND_ICONS[kind]}
      </div>
      <h3 className="mb-1 text-lg font-medium text-ink-muted">{title}</h3>
      {body != null && <p className="mb-4 text-md">{body}</p>}
      {actionLabel != null && (
        <Button
          variant={kind === "first-run" ? "primary" : "secondary"}
          size="sm"
          onClick={onAction}
        >
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
