// Figma: Banner 11:84 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";

export type BannerTone = "info" | "warning" | "danger";

const TONE_CLASSES: Record<BannerTone, string> = {
  info: "border-info bg-info-tint text-info",
  warning: "border-state-pending bg-state-pending-tint text-state-pending",
  danger: "border-state-broken bg-state-broken-tint text-state-broken",
};

const TONE_ICONS: Record<BannerTone, ReactNode> = {
  info: (
    <svg
      viewBox="0 0 16 16"
      className="mt-0.5 h-4 w-4 shrink-0"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" />
      <path
        d="M8 7.5v3.5M8 5v.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
  warning: (
    <svg
      viewBox="0 0 16 16"
      className="mt-0.5 h-4 w-4 shrink-0"
      aria-hidden="true"
    >
      <path
        d="M8 2L14.5 13.5H1.5Z"
        fill="none"
        stroke="currentColor"
        strokeLinejoin="round"
      />
      <path
        d="M8 6v3.5M8 11.2v.3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
  danger: (
    <svg
      viewBox="0 0 16 16"
      className="mt-0.5 h-4 w-4 shrink-0"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" />
      <path
        d="M5.5 5.5l5 5M10.5 5.5l-5 5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
};

export interface BannerProps {
  tone?: BannerTone;
  action?: { label: string; onAction?: () => void };
  dismissible?: boolean;
  onDismiss?: () => void;
  children: ReactNode;
}

export function Banner({
  tone = "info",
  action,
  dismissible = false,
  onDismiss,
  children,
}: BannerProps) {
  return (
    <div
      className={`flex items-start gap-3 rounded-md border px-4 py-3 text-md ${TONE_CLASSES[tone]}`}
    >
      {TONE_ICONS[tone]}
      <div className="min-w-0 flex-1">{children}</div>
      {action && (
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={action.onAction}
            className="rounded-md border border-line bg-surface px-2.5 py-1 text-sm font-medium text-ink hover:bg-subtle focus-visible:ring-2 focus-visible:ring-focus"
          >
            {action.label}
          </button>
        </div>
      )}
      {dismissible && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded-xs hover:opacity-70 focus-visible:ring-2 focus-visible:ring-focus"
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
