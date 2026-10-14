import type { Config } from "tailwindcss";

/**
 * Spydra — Tailwind configuration.
 *
 * Every colour here resolves to a CSS custom property declared in
 * design/tokens/tokens.css. That indirection is the point: the light and
 * dark themes swap the variable values, so a component written against
 * `bg-surface` or `text-state-broken` is theme-correct by construction.
 *
 * Consequence, and it is enforced in review: components must not use
 * Tailwind's own palette. `text-red-600` is a defect — it will not follow
 * the theme and it bypasses the single state-to-colour mapping.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx,html}", "./design/mockups/**/*.html"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    // Replace rather than extend: the default palette is removed so a raw
    // `bg-slate-200` fails to compile instead of silently shipping.
    colors: {
      transparent: "transparent",
      current: "currentColor",
      brand: {
        50: "var(--brand-50)",
        100: "var(--brand-100)",
        200: "var(--brand-200)",
        300: "var(--brand-300)",
        400: "var(--brand-400)",
        500: "var(--brand-500)",
        600: "var(--brand-600)",
        700: "var(--brand-700)",
        800: "var(--brand-800)",
        900: "var(--brand-900)",
      },
      bg: {
        base: "var(--bg-base)",
        surface: "var(--bg-surface)",
        subtle: "var(--bg-subtle)",
        raised: "var(--bg-raised)",
        inset: "var(--bg-inset)",
        hover: "var(--bg-hover)",
        selected: "var(--bg-selected)",
        backdrop: "var(--bg-backdrop)",
      },
      border: {
        DEFAULT: "var(--border)",
        strong: "var(--border-strong)",
        focus: "var(--border-focus)",
      },
      text: {
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        muted: "var(--text-muted)",
        inverse: "var(--text-inverse)",
        brand: "var(--text-brand)",
        link: "var(--text-link)",
      },
      state: {
        discovered: "var(--state-discovered)",
        "discovered-bg": "var(--state-discovered-bg)",
        pending: "var(--state-pending)",
        "pending-bg": "var(--state-pending-bg)",
        active: "var(--state-active)",
        "active-bg": "var(--state-active-bg)",
        broken: "var(--state-broken)",
        "broken-bg": "var(--state-broken-bg)",
        paused: "var(--state-paused)",
        "paused-bg": "var(--state-paused-bg)",
        archived: "var(--state-archived)",
        "archived-bg": "var(--state-archived-bg)",
      },
      fb: {
        info: "var(--fb-info)",
        "info-bg": "var(--fb-info-bg)",
        success: "var(--fb-success)",
        warning: "var(--fb-warning)",
        danger: "var(--fb-danger)",
      },
      viz: {
        1: "var(--viz-1)",
        2: "var(--viz-2)",
        3: "var(--viz-3)",
        4: "var(--viz-4)",
        5: "var(--viz-5)",
        6: "var(--viz-6)",
        grid: "var(--viz-grid)",
        axis: "var(--viz-axis)",
      },
    },
    fontFamily: {
      sans: ["Inter var", "Inter", "-apple-system", "sans-serif"],
      mono: ["JetBrains Mono", "ui-monospace", "Menlo", "monospace"],
      brand: ["Space Grotesk", "Inter", "sans-serif"],
    },
    fontSize: {
      "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      xs: ["0.75rem", { lineHeight: "1.125rem" }],
      sm: ["0.8125rem", { lineHeight: "1.25rem" }],
      md: ["0.875rem", { lineHeight: "1.375rem" }],
      lg: ["1rem", { lineHeight: "1.5rem" }],
      xl: ["1.25rem", { lineHeight: "1.75rem" }],
      "2xl": ["1.75rem", { lineHeight: "2.25rem" }],
    },
    fontWeight: { normal: "400", medium: "500", semibold: "600" },
    borderRadius: {
      none: "0",
      xs: "3px",
      sm: "4px",
      md: "6px",
      lg: "8px",
      xl: "12px",
      full: "999px",
    },
    boxShadow: {
      none: "none",
      sm: "var(--shadow-sm)",
      md: "var(--shadow-md)",
      lg: "var(--shadow-lg)",
    },
    extend: {
      spacing: {
        sidebar: "var(--sidebar-width)",
        "sidebar-collapsed": "var(--sidebar-collapsed)",
        topbar: "var(--topbar-height)",
        "row-comfortable": "var(--row-comfortable)",
        "row-compact": "var(--row-compact)",
      },
      transitionDuration: { fast: "120ms", base: "160ms", flash: "400ms" },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
    },
  },
  plugins: [],
};

export default config;
