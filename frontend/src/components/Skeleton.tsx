// Figma: Skeleton 33:120 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export type SkeletonShape = "row" | "card" | "chart" | "pane" | "text-line";

export interface SkeletonProps {
  shape: SkeletonShape;
  className?: string;
}

// A skeleton holds the height of what it replaces (UI_STATES §1), so heights
// come from the layout tokens — never a literal. Card/chart/pane children are
// absolutely positioned at fractional offsets, mirroring the Figma SCALE
// constraints: resizing the skeleton keeps every bar inside its bounds.
export function Skeleton({ shape, className = "" }: SkeletonProps) {
  const base = "bg-skeleton motion-safe:animate-pulse";

  if (shape === "row") {
    // The table-row placeholder: exactly --sp-row-comfortable, asserted in a
    // test (BUILD_PLAN 3.9) so it cannot drift into a hardcoded height.
    return (
      <div
        aria-hidden="true"
        className={`h-row-comfortable w-full rounded-md ${base} ${className}`}
      />
    );
  }

  if (shape === "text-line") {
    return (
      <div
        aria-hidden="true"
        className={`h-3 w-full rounded-xs ${base} ${className}`}
      />
    );
  }

  if (shape === "card") {
    return (
      <div
        aria-hidden="true"
        className={`relative h-24 w-full overflow-hidden rounded-lg ${base} ${className}`}
      >
        <div className="absolute top-[12%] left-[8%] h-[10%] w-[45%] rounded-xs bg-skeleton-sheen" />
        <div className="absolute top-[40%] left-[8%] h-[8%] w-[84%] rounded-xs bg-skeleton-sheen" />
        <div className="absolute top-[58%] left-[8%] h-[8%] w-[68%] rounded-xs bg-skeleton-sheen" />
        <div className="absolute top-[76%] left-[8%] h-[8%] w-[52%] rounded-xs bg-skeleton-sheen" />
      </div>
    );
  }

  if (shape === "chart") {
    return (
      <div
        aria-hidden="true"
        className={`relative h-40 w-full overflow-hidden rounded-md ${base} ${className}`}
      >
        <div className="absolute inset-x-[6%] bottom-[10%] h-[2px] rounded-xs bg-skeleton-sheen" />
        <div className="absolute bottom-[12%] left-[14%] h-[30%] w-[8%] rounded-xs bg-skeleton-sheen" />
        <div className="absolute bottom-[12%] left-[36%] h-[55%] w-[8%] rounded-xs bg-skeleton-sheen" />
        <div className="absolute bottom-[12%] left-[58%] h-[42%] w-[8%] rounded-xs bg-skeleton-sheen" />
        <div className="absolute bottom-[12%] left-[80%] h-[70%] w-[8%] rounded-xs bg-skeleton-sheen" />
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      className={`relative h-full min-h-40 w-full overflow-hidden rounded-lg ${base} ${className}`}
    >
      <div className="absolute inset-[6%] rounded-md bg-skeleton-sheen" />
      <div className="absolute inset-x-[10%] top-[10%] h-[14%] rounded-xs bg-skeleton" />
    </div>
  );
}
