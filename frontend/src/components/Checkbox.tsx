// Figma: Checkbox — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface CheckboxProps {
  /** "indeterminate" is aria-checked="mixed" + the dash glyph. */
  checked: boolean | "indeterminate";
  label?: string;
  disabled?: boolean;
  onChange?: (checked: boolean) => void;
}

// A real <button role="checkbox"> rather than a styled native input: the
// indeterminate state is a DOM property no static markup can carry.
export function Checkbox({
  checked,
  label,
  disabled = false,
  onChange,
}: CheckboxProps) {
  const mixed = checked === "indeterminate";
  const on = checked === true;
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={mixed ? "mixed" : on}
      disabled={disabled}
      onClick={() => onChange?.(!on)}
      className={`inline-flex cursor-pointer items-center gap-2 text-md focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
        disabled ? "text-disabled-ink" : "text-ink"
      }`}
    >
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-xs border ${
          on || mixed
            ? "border-brand bg-brand text-on-brand"
            : disabled
              ? "border-disabled-line bg-disabled"
              : "border-line-strong bg-surface"
        }`}
      >
        {mixed ? (
          <span className="h-[2px] w-2 rounded-full bg-current" />
        ) : on ? (
          <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
            <path
              d="M2.5 6.5L5 9l4.5-6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : null}
      </span>
      {label}
    </button>
  );
}
