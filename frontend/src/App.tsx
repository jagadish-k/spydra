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
          Scaffold standing. The screens arrive in phase&nbsp;3 — components
          first (<code>3.9</code>), then Domains, Review and the run monitor.
          Phase&nbsp;1 is deliberately headless: &ldquo;no UI, no model&rdquo;.
        </p>
        <p className="mt-4 text-sm text-ink-muted">
          Serve this through the edge at <code>http://127.0.0.1:8080</code>, not
          the Vite port. The edge is the one origin (ADR&#8209;0015);{" "}
          <code>VITE_API_BASE</code> is empty because every call is
          same&#8209;origin through it.
        </p>
      </main>
    </div>
  );
}
