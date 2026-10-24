// Figma: Button — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ButtonHTMLAttributes } from "react";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  // brand-subtle is the on-brand ink: text-inverse flips per theme and would
  // sit dark-on-indigo in dark mode. The active: arm is the pressed feedback
  // (UI_STATES §3a State=active): one existing token per variant, same hue
  // one step further than hover — no new tokens, nothing scales.
  primary:
    "border border-brand bg-brand text-brand-subtle hover:bg-brand-hover hover:border-brand-hover active:bg-brand-hover",
  secondary:
    "border border-line bg-surface text-ink hover:bg-subtle hover:border-line-strong active:bg-subtle active:border-line-strong",
  ghost:
    "border border-transparent text-ink-muted hover:bg-subtle hover:text-ink active:bg-subtle",
  danger:
    "border border-line bg-surface text-state-broken hover:border-state-broken hover:bg-state-broken-tint active:border-state-broken active:bg-state-broken-tint",
};

const SIZE_CLASSES = {
  sm: "h-6 px-2 text-xs gap-1.5",
  md: "h-[30px] px-3 text-md gap-1.5",
} as const;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: keyof typeof SIZE_CLASSES;
  /** State=loading: spinner joins the held label, so the width never moves. */
  loading?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  type = "button",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex shrink-0 items-center justify-center rounded-md font-medium transition-colors duration-[var(--sp-duration-fast)] focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${SIZE_CLASSES[size]} ${VARIANT_CLASSES[variant]} ${className}`}
      {...rest}
    >
      {loading && <Spinner size="sm" onBrand={variant === "primary"} />}
      {children}
    </button>
  );
}
