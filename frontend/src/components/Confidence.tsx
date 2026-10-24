// Figma: Confidence — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export type ConfidenceLevel = "high" | "good" | "medium" | "low";

// The number of lit bars carries the signal as well as the colour: high=4
// down to low=1 (DESIGN_SYSTEM).
const LEVELS: Record<ConfidenceLevel, { lit: number; onClass: string }> = {
  high: { lit: 4, onClass: "bg-state-active" },
  good: { lit: 3, onClass: "bg-state-active" },
  medium: { lit: 2, onClass: "bg-state-pending" },
  low: { lit: 1, onClass: "bg-state-broken" },
};

export interface ConfidenceProps {
  level: ConfidenceLevel;
}

export function Confidence({ level }: ConfidenceProps) {
  const { lit, onClass } = LEVELS[level];
  return (
    <span
      role="img"
      aria-label={`model confidence: ${level}`}
      className="inline-flex items-center gap-[2px]"
    >
      {[1, 2, 3, 4].map((bar) => (
        <i
          key={bar}
          className={`inline-block h-[9px] w-[3px] rounded-[1px] ${
            bar <= lit ? onClass : "bg-line-strong"
          }`}
        />
      ))}
    </span>
  );
}
