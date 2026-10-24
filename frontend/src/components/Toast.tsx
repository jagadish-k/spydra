// Figma: Toast 34:201 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";
import { Button } from "./Button";

export type ToastTone = "info" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<ToastTone, string> = {
  info: "text-info",
  success: "text-state-active",
  warning: "text-state-pending",
  danger: "text-state-broken",
};

const TONE_ICONS: Record<ToastTone, ReactNode> = {
  info: (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" />
      <path
        d="M8 7.5v3.5M8 5v.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  ),
  success: (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" />
      <path
        d="M5 8.5L7 10.5L11 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  ),
  warning: (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
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
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
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

export interface ToastProps {
  tone: ToastTone;
  action?: { label: string; onAction?: () => void };
  dismissible?: boolean;
  onDismiss?: () => void;
  children: ReactNode;
}

export function Toast({
  tone,
  action,
  dismissible = false,
  onDismiss,
  children,
}: ToastProps) {
  return (
    <div
      // danger interrupts (alert); the rest are polite status announcements
      role={tone === "danger" ? "alert" : "status"}
      className="flex items-start gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-md shadow-md"
    >
      <span className={`mt-0.5 shrink-0 ${TONE_CLASSES[tone]}`}>
        {TONE_ICONS[tone]}
      </span>
      <div className="min-w-0 flex-1 text-ink">{children}</div>
      {action && (
        <Button size="sm" variant="ghost" onClick={action.onAction}>
          {action.label}
        </Button>
      )}
      {dismissible && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
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
