// Figma: Validation badge — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export type ValidationKind = "pass" | "partial" | "fail";

const KIND_CLASSES: Record<ValidationKind, string> = {
  pass: "bg-state-active-tint text-state-active",
  partial: "bg-state-pending-tint text-state-pending",
  fail: "bg-state-broken-tint text-state-broken",
};

const KIND_LABELS: Record<ValidationKind, string> = {
  pass: "✓ pass",
  partial: "partial",
  fail: "✕ fail",
};

export interface ValidationBadgeProps {
  kind: ValidationKind;
  /** Failing-rule count, shown when present. */
  count?: number;
  /** The failing rule's name — surfaces as the tooltip. */
  rule?: string;
}

export function ValidationBadge({ kind, count, rule }: ValidationBadgeProps) {
  return (
    <span
      title={rule}
      className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-2xs font-medium whitespace-nowrap ${KIND_CLASSES[kind]}`}
    >
      {KIND_LABELS[kind]}
      {count != null && count > 0 && (
        <span className="tabular-nums">· {count}</span>
      )}
    </span>
  );
}
