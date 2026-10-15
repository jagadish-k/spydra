import { useTheme } from "../hooks/useTheme";

export function ThemeToggle() {
  const [theme, toggle] = useTheme();

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-subtle focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2"
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
