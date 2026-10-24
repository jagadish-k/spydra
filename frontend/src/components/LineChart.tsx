// Figma: Line chart 201:1489 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface LineSeries {
  points: readonly number[];
}

export interface LineChartProps {
  /** One or two series; more would need colours the ramp reserves for six. */
  series: readonly LineSeries[];
  /** live = the last point pulses (an SSE-fed chart); absent = static. */
  live?: boolean;
  ariaLabel?: string;
  className?: string;
}

const SERIES_CLASSES = ["stroke-viz-1", "stroke-viz-2"] as const;

const W = 100;
const H = 40;

function toPath(points: readonly number[]): string {
  const clean = points.filter((v) => Number.isFinite(v));
  if (clean.length < 2) return "";
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  return clean
    .map((value, index) => {
      const x = (index / (clean.length - 1)) * W;
      const y = 3 + (1 - (value - min) / span) * (H - 6);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function lastPoint(points: readonly number[]): { x: number; y: number } | null {
  const clean = points.filter((v) => Number.isFinite(v));
  if (clean.length < 2) return null;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  return {
    x: W,
    y: 3 + (1 - (clean[clean.length - 1]! - min) / span) * (H - 6),
  };
}

// Hand-written SVG, like Sparkline — Recharts arrives with the first screen
// that needs axes and time scales (spec 006 §2), not for two polylines.
// No-data is derived: empty series draws the grid and a label, never axes
// that pretend to have data.
export function LineChart({
  series,
  live = false,
  ariaLabel = "line chart",
  className = "",
}: LineChartProps) {
  const hasData = series.some(
    (s) => s.points.filter(Number.isFinite).length >= 2,
  );
  return (
    <div className={`relative h-40 w-full ${className}`}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={ariaLabel}
        className="h-full w-full"
      >
        {[0.25, 0.5, 0.75].map((t) => (
          <line
            key={t}
            x1="0"
            x2={W}
            y1={H * t}
            y2={H * t}
            strokeWidth="1"
            className="stroke-viz-grid"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {hasData &&
          series.slice(0, 2).map((s, index) => {
            const d = toPath(s.points);
            if (!d) return null;
            return (
              <path
                key={index}
                d={d}
                fill="none"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={SERIES_CLASSES[index] ?? SERIES_CLASSES[0]!}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        {hasData &&
          live &&
          series.slice(0, 2).map((s, index) => {
            const point = lastPoint(s.points);
            if (!point) return null;
            return (
              <g key={`pulse-${index}`}>
                <circle
                  cx={point.x}
                  cy={point.y}
                  r="2.5"
                  className="motion-safe:animate-ping text-viz-1"
                  fill="currentColor"
                  opacity="0.6"
                />
                <circle
                  cx={point.x}
                  cy={point.y}
                  r="1.5"
                  className="fill-viz-1"
                />
              </g>
            );
          })}
      </svg>
      {!hasData && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-ink-subtle">
          no data
        </div>
      )}
    </div>
  );
}
