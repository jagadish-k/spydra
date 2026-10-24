// Figma: Input 42:156 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { InputHTMLAttributes, ReactNode } from "react";

export interface InputProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "prefix"
> {
  /** Error styling + aria-invalid; the message itself is screen copy. */
  error?: boolean;
  prefix?: ReactNode;
  /** Present = the clear affordance (shown only when a value exists). */
  onClear?: () => void;
}

// The ring sits on the wrapper (focus-within) so the whole field reads as
// focused, not just the bare <input> inside it.
export function Input({
  error = false,
  prefix,
  onClear,
  disabled = false,
  readOnly = false,
  value,
  className = "",
  ...rest
}: InputProps) {
  return (
    <div
      className={`flex h-[30px] items-center gap-2 rounded-md border bg-surface px-3 transition-colors focus-within:ring-2 focus-within:ring-focus focus-within:ring-offset-1 ${
        error
          ? "border-state-broken"
          : "border-line focus-within:border-line-strong"
      } ${
        disabled
          ? "border-disabled-line bg-disabled text-disabled-ink"
          : readOnly
            ? "bg-inset"
            : ""
      } ${className}`}
    >
      {prefix != null && (
        <span className="shrink-0 text-xs text-ink-subtle">{prefix}</span>
      )}
      <input
        value={value}
        disabled={disabled}
        readOnly={readOnly}
        aria-invalid={error || undefined}
        className="w-full min-w-0 flex-1 bg-transparent text-md text-ink outline-none placeholder:text-ink-subtle disabled:cursor-not-allowed"
        {...rest}
      />
      {onClear != null && value != null && String(value).length > 0 && (
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear"
          className="shrink-0 rounded-xs text-ink-subtle hover:text-ink focus-visible:ring-2 focus-visible:ring-focus"
        >
          <svg viewBox="0 0 12 12" className="h-3 w-3">
            <path
              d="M2.5 2.5l7 7M9.5 2.5l-7 7"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
