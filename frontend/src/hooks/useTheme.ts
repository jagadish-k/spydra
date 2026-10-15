import { useCallback, useState } from "react";
import { storeTheme, toggleTheme, type Theme } from "../lib/theme";

// Dark is opt-in via <html data-theme="dark"> (tokens.css). The inline
// script in index.html has already applied the resolved theme before React
// mounts — read what it decided rather than re-deriving and flashing.
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark"
      : "light",
  );

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = toggleTheme(current);
      if (next === "dark") {
        document.documentElement.setAttribute("data-theme", "dark");
      } else {
        document.documentElement.removeAttribute("data-theme");
      }
      storeTheme((key, value) => localStorage.setItem(key, value), next);
      return next;
    });
  }, []);

  return [theme, toggle];
}
