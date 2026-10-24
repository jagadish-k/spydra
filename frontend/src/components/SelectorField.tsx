// Figma: Selector field 11:142 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import { Spinner } from "./Spinner";

export interface SelectorFieldProps {
  selector: string;
  /**
   * Match count against the loaded DOM; null = still resolving. Drives the
   * whole state axis: 0 = no match (muted — valid selector, empty result),
   * >1 = warning (multi-match), 1 = default.
   */
  matches: number | null;
  /** A resolved sample value shown under the selector. */
  resolved?: string;
  label?: string;
  required?: boolean;
  /** Syntactically invalid selector — the red state, distinct from no-match. */
  invalid?: boolean;
  disabled?: boolean;
  onChange?: (value: string) => void;
}

export function SelectorField({
  selector,
  matches,
  resolved,
  label,
  required = false,
  invalid = false,
  disabled = false,
  onChange,
}: SelectorFieldProps) {
  const warning = !invalid && matches != null && matches > 1;
  const stateClass = invalid
    ? "border-state-broken bg-state-broken-tint"
    : warning
      ? "border-state-pending bg-state-pending-tint"
      : "border-transparent";

  const matchesText =
    matches === null
      ? "resolving…"
      : matches === 0
        ? "no matches"
        : `${matches} match${matches === 1 ? "" : "es"}`;
  const matchesClass =
    matches === 0
      ? "text-ink-subtle"
      : warning
        ? "text-state-pending"
        : "text-ink-muted";

  return (
    <div
      className={`grid grid-cols-[110px_1fr] items-start gap-x-3 gap-y-1 rounded-md border p-3 transition-colors duration-[var(--sp-duration-fast)] hover:bg-hover ${stateClass}`}
    >
      {label != null && (
        <div className="flex items-center gap-[5px] pt-1.5 text-sm font-medium text-ink">
          {label}
          {required && <span className="text-state-broken">*</span>}
        </div>
      )}
      <div className="flex min-w-0 flex-col gap-[5px]">
        <input
          value={selector}
          disabled={disabled}
          onChange={(event) => onChange?.(event.target.value)}
          spellCheck={false}
          aria-invalid={invalid || undefined}
          className="w-full min-w-0 rounded-xs bg-inset px-1.5 py-1 font-mono text-xs text-ink outline-none focus-visible:ring-2 focus-visible:ring-focus disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled-ink"
        />
        <div className="flex min-w-0 items-baseline gap-2 text-sm">
          <span className="shrink-0 text-ink-subtle">→</span>
          {resolved != null && resolved.length > 0 ? (
            <span className="min-w-0 truncate font-medium text-ink">
              {resolved}
            </span>
          ) : (
            <span className="text-ink-subtle italic">unresolved</span>
          )}
          <span
            className={`ml-auto flex shrink-0 items-center gap-1 text-xs tabular-nums ${matchesClass}`}
          >
            {matches === null && <Spinner size="sm" />}
            {matchesText}
          </span>
        </div>
      </div>
    </div>
  );
}
