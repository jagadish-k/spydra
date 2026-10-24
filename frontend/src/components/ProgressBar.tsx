// Figma: Progress bar 43:270 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface ProgressSegments {
  queued: number;
  inFlight: number;
  done: number;
  failed: number;
}

export type ProgressState =
  "running" | "paused" | "complete" | "failed" | "empty";

export interface ProgressBarProps {
  /** Present = the stacked bar (run monitor / per-row compact use). */
  segments?: ProgressSegments;
  /** Single-state bar; ignored when `segments` is given. */
  state?: ProgressState;
  /** 0..1 for the determinate running bar; absent = indeterminate. */
  fraction?: number;
  legend?: boolean;
}

const SEGMENT_CLASSES = {
  queued: "bg-line-strong",
  inFlight: "bg-viz-1",
  done: "bg-state-active",
  failed: "bg-state-broken",
} as const;

const STATE_FILL_CLASSES: Record<ProgressState, string> = {
  running: "bg-viz-1",
  paused: "bg-state-paused",
  complete: "bg-state-active",
  failed: "bg-state-broken",
  empty: "",
};

// Never a percentage: during discovery the denominator is still growing, so a
// percentage would lie (DESIGN_SYSTEM "three decisions").
export function ProgressBar({
  segments,
  state = "running",
  fraction,
  legend = false,
}: ProgressBarProps) {
  if (segments) {
    const total =
      segments.queued + segments.inFlight + segments.done + segments.failed;
    return (
      <div>
        <div className="flex h-1.5 overflow-hidden rounded-full bg-subtle">
          {total > 0 &&
            (Object.keys(SEGMENT_CLASSES) as Array<keyof ProgressSegments>).map(
              (key) => {
                const count = segments[key];
                if (count <= 0) return null;
                return (
                  <div
                    key={key}
                    className={SEGMENT_CLASSES[key]}
                    style={{ width: `${(count / total) * 100}%` }}
                  />
                );
              },
            )}
        </div>
        {legend && (
          <div className="mt-1.5 flex flex-wrap gap-4 text-xs text-ink-muted">
            {(
              Object.keys(SEGMENT_CLASSES) as Array<keyof ProgressSegments>
            ).map((key) => (
              <span key={key} className="inline-flex items-center gap-[5px]">
                <i
                  className={`inline-block h-[7px] w-[7px] rounded-[2px] ${SEGMENT_CLASSES[key]}`}
                />
                {key === "inFlight" ? "in flight" : key} ({segments[key]})
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  const width =
    state === "complete"
      ? "100%"
      : state === "empty"
        ? "0%"
        : fraction != null
          ? `${Math.min(100, Math.max(0, fraction * 100))}%`
          : // indeterminate: a fixed-width pulse rather than a sliding track —
            // nothing slides in this UI (DESIGN_SYSTEM motion).
            "33%";
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-subtle">
      <div
        className={`h-full rounded-full ${STATE_FILL_CLASSES[state]} ${
          fraction == null && state === "running"
            ? "motion-safe:animate-pulse"
            : ""
        }`}
        style={{ width }}
      />
    </div>
  );
}
