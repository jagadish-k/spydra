import { ThemeToggle } from "./components/ThemeToggle";

// Phase-0 scaffold shell: proves the token pipeline (semantic utilities,
// both themes) and the toggle. The real AppShell arrives in phase 3.
export default function App() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <h1 className="font-brand text-lg font-medium tracking-tight text-ink">
          Spydra
        </h1>
        <ThemeToggle />
      </header>
      <main className="px-4 py-6">
        <p className="text-md text-ink">
          Single-operator crawler control room.
        </p>
        <p className="text-sm text-ink-muted">
          Scaffold standing — domains, templates and runs arrive with the
          phase&nbsp;1 schema.
        </p>
      </main>
    </div>
  );
}
