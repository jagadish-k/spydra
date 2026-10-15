// Theme resolution logic, pure and injectable so it is testable without a
// DOM. The side-effecting half lives in the inline <head> script in
// index.html (before first paint) and in hooks/useTheme.ts (the toggle).
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "spydra-theme";

export function readStoredTheme(
  getItem: (key: string) => string | null,
): Theme | null {
  try {
    const value = getItem(THEME_STORAGE_KEY);
    return value === "dark" || value === "light" ? value : null;
  } catch {
    // localStorage throws in a private window (DESIGN_SYSTEM §Theme);
    // rendering must continue with the fallback.
    return null;
  }
}

export function storeTheme(
  setItem: (key: string, value: string) => void,
  theme: Theme,
): void {
  try {
    setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* private window: the choice is simply not persisted */
  }
}

// First visit respects prefers-color-scheme; once a choice is stored it
// wins on every later load.
export function initialTheme(
  getItem: (key: string) => string | null,
  prefersDark: boolean,
): Theme {
  return readStoredTheme(getItem) ?? (prefersDark ? "dark" : "light");
}

export function toggleTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}
