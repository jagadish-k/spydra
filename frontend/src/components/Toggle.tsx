// Figma: Toggle 51:303 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface ToggleProps {
  checked: boolean;
  label?: string;
  disabled?: boolean;
  onChange?: (checked: boolean) => void;
}

export function Toggle({
  checked,
  label,
  disabled = false,
  onChange,
}: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={`inline-flex cursor-pointer items-center gap-2 text-md focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
        disabled ? "text-disabled-ink" : "text-ink"
      }`}
    >
      <span
        className={`relative h-4 w-[30px] shrink-0 rounded-full transition-colors duration-[var(--sp-duration-fast)] ${
          checked ? "bg-brand" : disabled ? "bg-disabled" : "bg-line-strong"
        }`}
      >
        <span
          className={`absolute top-[1px] left-[1px] h-3.5 w-3.5 rounded-full bg-on-brand transition-transform duration-[var(--sp-duration-fast)] ${
            checked ? "translate-x-[14px]" : ""
          }`}
        />
      </span>
      {label}
    </button>
  );
}
