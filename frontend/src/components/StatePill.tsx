// Figma: State pill — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export type DomainState =
  "discovered" | "pending" | "active" | "broken" | "paused" | "archived";

const STATE_CLASSES: Record<DomainState, string> = {
  discovered: "bg-state-discovered-tint text-state-discovered",
  pending: "bg-state-pending-tint text-state-pending",
  active: "bg-state-active-tint text-state-active",
  broken: "bg-state-broken-tint text-state-broken",
  paused: "bg-state-paused-tint text-state-paused",
  archived: "bg-state-archived-tint text-state-archived",
};

export interface StatePillProps {
  state: DomainState;
  /** Why the domain is in this state — surfaces as the tooltip. */
  why?: string;
}

// Six lifecycle states, no seventh without a schema change (UI_STATES §3a).
export function StatePill({ state, why }: StatePillProps) {
  return (
    <span
      title={why}
      className={`inline-flex items-center gap-[5px] rounded-sm py-0.5 pr-2 pl-1.5 text-2xs font-medium whitespace-nowrap ${STATE_CLASSES[state]}`}
    >
      <span className="h-[5px] w-[5px] rounded-full bg-current" />
      {state}
    </span>
  );
}
