// Figma: Error state — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";
import { Button } from "./Button";

export type ErrorKind = "fetch" | "permission" | "timeout" | "partial";

const KIND_ICONS: Record<ErrorKind, ReactNode> = {
  fetch: (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <path
        d="M8 12a8 8 0 0116 0c0 4 1.5 5.5 3 7H5c1.5-1.5 3-3 3-7Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M12 23l-2 4M20 23l2 4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M6 4l20 24"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
  permission: (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <rect
        x="7"
        y="14"
        width="18"
        height="13"
        rx="2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M11 14v-3a5 5 0 0110 0v3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <circle cx="16" cy="20" r="1.6" fill="currentColor" />
    </svg>
  ),
  timeout: (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <circle
        cx="16"
        cy="16"
        r="11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M16 9v7l5 3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
  partial: (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <circle
        cx="16"
        cy="16"
        r="11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M16 5v11l9.5 5.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  ),
};

const KIND_TITLES: Record<ErrorKind, string> = {
  fetch: "Could not load this",
  permission: "Permission denied",
  timeout: "Timed out",
  partial: "Some parts failed to load",
};

export interface ErrorStateProps {
  kind: ErrorKind;
  /** The reason, always shown — an error state never strands the user. */
  reason?: string;
  title?: string;
  onRetry?: () => void;
}

export function ErrorState({ kind, reason, title, onRetry }: ErrorStateProps) {
  return (
    <div role="alert" className="px-4 py-12 text-center text-ink-subtle">
      <div className="mb-3 flex justify-center text-state-broken opacity-70">
        {KIND_ICONS[kind]}
      </div>
      <h3 className="mb-1 text-lg font-medium text-ink-muted">
        {title ?? KIND_TITLES[kind]}
      </h3>
      {reason != null && <p className="mb-4 text-md">{reason}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
