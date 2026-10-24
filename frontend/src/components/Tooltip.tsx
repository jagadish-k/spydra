// Figma: Tooltip 201:1406 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";

export type TooltipSide = "top" | "bottom" | "left" | "right";

const SIDE_CLASSES: Record<TooltipSide, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
  left: "right-full top-1/2 -translate-y-1/2 mr-1.5",
  right: "left-full top-1/2 -translate-y-1/2 ml-1.5",
};

export interface TooltipProps {
  label: string;
  side?: TooltipSide;
  children: ReactNode;
}

export function Tooltip({ label, side = "bottom", children }: TooltipProps) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute w-max max-w-[220px] rounded-xs bg-ink px-2 py-1 text-xs text-ink-inverse opacity-0 transition-opacity duration-[var(--sp-duration-fast)] group-hover:opacity-100 group-focus-within:opacity-100 ${SIDE_CLASSES[side]}`}
      >
        {label}
      </span>
    </span>
  );
}
