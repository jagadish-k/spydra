// Figma: Tag 43:146 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";

export type TagTone = "neutral" | "info" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<TagTone, string> = {
  neutral: "bg-subtle text-ink-muted",
  info: "bg-info-tint text-info",
  success: "bg-state-active-tint text-state-active",
  warning: "bg-state-pending-tint text-state-pending",
  danger: "bg-state-broken-tint text-state-broken",
};

export interface TagProps {
  tone?: TagTone;
  removable?: boolean;
  disabled?: boolean;
  onRemove?: () => void;
  children: ReactNode;
}

export function Tag({
  tone = "neutral",
  removable = false,
  disabled = false,
  onRemove,
  children,
}: TagProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-1.5 py-px text-2xs font-medium whitespace-nowrap ${TONE_CLASSES[tone]} ${
        disabled ? "cursor-not-allowed opacity-50" : ""
      }`}
    >
      {children}
      {removable && (
        <button
          type="button"
          onClick={disabled ? undefined : onRemove}
          disabled={disabled}
          aria-label="Remove tag"
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
