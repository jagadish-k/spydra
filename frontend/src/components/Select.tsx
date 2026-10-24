// Figma: Select 51:293 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import { useId } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  options: readonly SelectOption[];
  value?: string;
  placeholder?: string;
  open?: boolean;
  error?: boolean;
  disabled?: boolean;
  onChange?: (value: string) => void;
}

// Custom listbox rather than a native <select>: the open arm and the error
// arm are drawn states a native control cannot express. The screen owns
// open/closed and outside-click dismissal.
export function Select({
  options,
  value,
  placeholder,
  open = false,
  error = false,
  disabled = false,
  onChange,
}: SelectProps) {
  const listboxId = useId();
  const selected = options.find((option) => option.value === value);
  return (
    <div className="relative inline-flex min-w-40 flex-col">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-invalid={error || undefined}
        className={`flex h-[30px] items-center justify-between gap-2 rounded-md border px-3 text-md transition-colors focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 ${
          error ? "border-state-broken" : "border-line hover:border-line-strong"
        } ${
          disabled
            ? "cursor-not-allowed border-disabled-line bg-disabled text-disabled-ink"
            : "bg-surface text-ink"
        }`}
      >
        <span className={selected ? "" : "text-ink-subtle"}>
          {selected?.label ?? placeholder ?? ""}
        </span>
        <svg
          viewBox="0 0 16 16"
          className={`h-3.5 w-3.5 shrink-0 transition-transform duration-[var(--sp-duration-fast)] ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        >
          <path
            d="M4 6l4 4 4-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open && !disabled && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute top-full right-0 left-0 z-10 mt-1 max-h-60 overflow-auto rounded-md border border-line bg-surface py-1 shadow-md"
        >
          {options.map((option) => (
            <li key={option.value}>
              <button
                type="button"
                role="option"
                aria-selected={option.value === value}
                onClick={() => onChange?.(option.value)}
                className={`block w-full cursor-pointer px-3 py-1.5 text-left text-sm hover:bg-subtle focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus ${
                  option.value === value
                    ? "bg-selected text-ink-brand"
                    : "text-ink"
                }`}
              >
                {option.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
