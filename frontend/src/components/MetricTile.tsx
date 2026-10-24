// Figma: Metric tile 11:71 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import { Skeleton } from "./Skeleton";

export type MetricTone = "default" | "attention" | "danger";

const TONE_CLASSES: Record<MetricTone, string> = {
  default: "text-ink",
  attention: "text-state-pending",
  danger: "text-state-broken",
};

export interface MetricTileProps {
  label: string;
  /**
   * null is the unavailable state (ADR-0025's partial-counter contract): the
   * tile draws an em dash, not an error — one failed counter never blanks
   * the strip.
   */
  value: number | null;
  detail?: string;
  tone?: MetricTone;
  loading?: boolean;
}

export function MetricTile({
  label,
  value,
  detail,
  tone = "default",
  loading = false,
}: MetricTileProps) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className="mb-0.5 flex items-center gap-[5px] text-xs text-ink-muted">
        {label}
      </div>
      {loading ? (
        <Skeleton shape="text-line" className="w-16" />
      ) : (
        <div
          className={`text-xl leading-xl font-semibold tracking-tight tabular-nums ${TONE_CLASSES[tone]}`}
        >
          {value === null ? "—" : value}
        </div>
      )}
      {detail != null && (
        <div className="text-xs text-ink-subtle">{detail}</div>
      )}
    </div>
  );
}
