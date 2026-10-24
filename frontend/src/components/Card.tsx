// Figma: Card — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";
import { Skeleton } from "./Skeleton";

export interface CardProps {
  children?: ReactNode;
  /** State=Hover: only offered on cards the user can act on. */
  interactive?: boolean;
  selected?: boolean;
  /** State=Loading: content swaps for a size-tolerant skeleton. */
  loading?: boolean;
  className?: string;
}

export function Card({
  children,
  interactive = false,
  selected = false,
  loading = false,
  className = "",
}: CardProps) {
  return (
    <div
      className={`rounded-lg border bg-surface transition-colors duration-[var(--sp-duration-fast)] ${
        selected ? "border-focus bg-selected" : "border-line"
      } ${interactive ? "cursor-pointer hover:border-line-strong" : ""} ${className}`}
    >
      {loading ? <Skeleton shape="card" /> : children}
    </div>
  );
}
