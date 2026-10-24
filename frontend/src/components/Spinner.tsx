// Figma: Spinner — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

const SIZE_CLASSES = {
  sm: "h-3.5 w-3.5",
  md: "h-4 w-4",
} as const;

export interface SpinnerProps {
  size?: keyof typeof SIZE_CLASSES;
  /** on-brand = sitting on a filled brand surface (Button loading). */
  onBrand?: boolean;
}

export function Spinner({ size = "md", onBrand = false }: SpinnerProps) {
  // on-brand is the theme-constant ink for filled brand surfaces:
  // text-inverse flips per theme and would go dark-on-indigo in dark mode.
  return (
    <svg
      viewBox="0 0 16 16"
      role="status"
      aria-label="Loading"
      className={`motion-safe:animate-spin shrink-0 ${SIZE_CLASSES[size]} ${
        onBrand ? "text-on-brand" : "text-ink-subtle"
      }`}
    >
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="26 12"
      />
    </svg>
  );
}
