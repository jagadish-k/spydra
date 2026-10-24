// Figma: Sparkline 10:93 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export type SparkTrend = "healthy" | "slipping" | "failing" | "pending";

const TREND_CLASSES: Record<SparkTrend, string> = {
  healthy: "stroke-state-active",
  slipping: "stroke-state-pending",
  failing: "stroke-state-broken",
  pending: "stroke-line-strong",
};

export interface SparklineProps {
  values: readonly number[];
  /** The band is domain knowledge (success-rate banding), so the caller states it. */
  trend: SparkTrend;
}

const W = 72;
const H = 20;

// Hand-written SVG, seven points (spec 006 §2) — no chart library for a
// 72×20 trend. Empty values draw the pending flat line.
export function Sparkline({ values, trend }: SparklineProps) {
  const points = values.filter((v) => Number.isFinite(v));
  let path: string;
  if (points.length < 2) {
    path = `M0 ${H / 2} H${W}`;
  } else {
    const min = Math.min(...points);
    const max = Math.max(...points);
    const span = max - min || 1;
    path = points
      .map((value, index) => {
        const x = (index / (points.length - 1)) * W;
        const y = 2 + (1 - (value - min) / span) * (H - 4);
        return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  }
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`7-day trend: ${trend}`}
      className="block h-5 w-[72px] overflow-visible"
    >
      <path
        d={path}
        fill="none"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={TREND_CLASSES[trend]}
      />
    </svg>
  );
}
