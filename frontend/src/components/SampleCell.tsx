// Figma: Sample cell 10:83 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export type SampleResult = "pass" | "fail" | "partial" | "pending";

const RESULT_CLASSES: Record<SampleResult, string> = {
  pass: "text-state-active",
  fail: "bg-state-broken-tint font-semibold text-state-broken",
  partial: "bg-state-pending-tint text-state-pending",
  // A pending sample has no result yet — neutral, not an error.
  pending: "text-ink-subtle",
};

const RESULT_GLYPHS: Record<SampleResult, string> = {
  pass: "✓",
  fail: "✕",
  partial: "~",
  pending: "—",
};

export interface SampleCellProps {
  result: SampleResult;
  /** Sample URL or field name — surfaces as the tooltip. */
  title?: string;
}

// One cell of the sample matrix: turns red the moment a selector stops
// resolving on any sample, before anything is approved (spec 006 §5).
export function SampleCell({ result, title }: SampleCellProps) {
  return (
    <div
      title={title}
      className={`rounded-sm px-1.5 py-1 text-center text-2xs whitespace-nowrap ${RESULT_CLASSES[result]}`}
    >
      {RESULT_GLYPHS[result]}
    </div>
  );
}
