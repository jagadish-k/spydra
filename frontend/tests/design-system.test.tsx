// The three mandated assertions of BUILD_PLAN 3.9 / UI_STATES §6, plus the
// whole-library guarantees: every component renders under both themes via
// mapped semantic utilities (so data-theme="dark" needs no per-component
// branch), and no component carries a raw palette class (AGENTS rule 6).
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Banner } from "../src/components/Banner";
import { BulkActionBar } from "../src/components/BulkActionBar";
import { Button } from "../src/components/Button";
import { Card } from "../src/components/Card";
import { Checkbox } from "../src/components/Checkbox";
import { Confidence } from "../src/components/Confidence";
import { EmptyState } from "../src/components/EmptyState";
import { ErrorState } from "../src/components/ErrorState";
import { FilterChip } from "../src/components/FilterChip";
import { Input } from "../src/components/Input";
import { LineChart } from "../src/components/LineChart";
import { MetricTile } from "../src/components/MetricTile";
import { Modal } from "../src/components/Modal";
import { Pagination } from "../src/components/Pagination";
import { ProgressBar } from "../src/components/ProgressBar";
import { RowActionMenu } from "../src/components/RowActionMenu";
import { SampleCell } from "../src/components/SampleCell";
import { SearchField } from "../src/components/SearchField";
import { Select } from "../src/components/Select";
import { SelectorField } from "../src/components/SelectorField";
import { Skeleton } from "../src/components/Skeleton";
import { Sparkline } from "../src/components/Sparkline";
import { Spinner } from "../src/components/Spinner";
import { StatePill } from "../src/components/StatePill";
import { TableHeaderCell } from "../src/components/TableHeaderCell";
import { Tabs } from "../src/components/Tabs";
import { Tag } from "../src/components/Tag";
import { Toast } from "../src/components/Toast";
import { Toggle } from "../src/components/Toggle";
import { Tooltip } from "../src/components/Tooltip";
import { ValidationBadge } from "../src/components/ValidationBadge";

const noop = (): void => undefined;

// One representative arm per component — enough markup to exercise every
// component's class surface for the theme and resolution sweeps below.
const LIBRARY: ReadonlyArray<[string, ReactNode]> = [
  ["Banner", <Banner tone="warning">note</Banner>],
  [
    "BulkActionBar",
    <BulkActionBar count={2} actions={[{ id: "pause", label: "Pause" }]} />,
  ],
  ["Button", <Button variant="danger">Go</Button>],
  ["Card", <Card selected>content</Card>],
  ["Checkbox", <Checkbox checked="indeterminate" label="rows" />],
  ["Confidence", <Confidence level="high" />],
  ["EmptyState", <EmptyState kind="filtered" title="Nothing matches" />],
  ["ErrorState", <ErrorState kind="timeout" onRetry={noop} />],
  [
    "FilterChip",
    <FilterChip active removable>
      broken
    </FilterChip>,
  ],
  ["Input", <Input error prefix="https://" value="x" onChange={noop} />],
  ["LineChart", <LineChart series={[{ points: [1, 2, 3] }]} live />],
  ["MetricTile", <MetricTile label="Domains" value={null} />],
  [
    "Modal",
    <Modal kind="confirm-danger" title="Delete?" confirmLabel="Delete">
      body
    </Modal>,
  ],
  ["Pagination", <Pagination page={1} pageCount={5} />],
  [
    "ProgressBar",
    <ProgressBar
      segments={{ queued: 3, inFlight: 2, done: 1, failed: 1 }}
      legend
    />,
  ],
  [
    "RowActionMenu",
    <RowActionMenu open actions={[{ id: "view", label: "View" }]} />,
  ],
  ["SampleCell", <SampleCell result="pending" />],
  ["SearchField", <SearchField value="denim" noResults />],
  ["Select", <Select open options={[{ value: "a", label: "Alpha" }]} />],
  ["SelectorField", <SelectorField selector="a" matches={6} />],
  ["Skeleton", <Skeleton shape="card" />],
  ["Sparkline", <Sparkline values={[1, 2, 1.5]} trend="healthy" />],
  ["Spinner", <Spinner size="sm" onBrand />],
  ["StatePill", <StatePill state="broken" why="failures" />],
  ["TableHeaderCell", <TableHeaderCell sort="asc">Domain</TableHeaderCell>],
  [
    "Tabs",
    <Tabs
      items={[
        { id: "a", label: "A", count: 3 },
        { id: "b", label: "B", disabled: true },
      ]}
      value="a"
    />,
  ],
  [
    "Tag",
    <Tag tone="success" removable disabled>
      ok
    </Tag>,
  ],
  [
    "Toast",
    <Toast tone="danger" action={{ label: "View" }} dismissible>
      msg
    </Toast>,
  ],
  ["Toggle", <Toggle checked disabled label="auto" />],
  ["Tooltip", <Tooltip label="hint">x</Tooltip>],
  ["ValidationBadge", <ValidationBadge kind="fail" count={2} />],
];

const rendered = new Map(
  LIBRARY.map(([name, node]) => [name, renderToStaticMarkup(node)]),
);

// ---------------------------------------------------------------------------
// Mandated: Skeleton shape="row" is exactly --sp-row-comfortable tall
// (BUILD_PLAN 3.9, UI_STATES §6 — a wrong-height skeleton is a layout jump
// no screenshot review catches). The height must come from the token chain
// (utility → --spacing mapping → tokens.css), never a literal.
// ---------------------------------------------------------------------------

const repoRoot = join(import.meta.dirname, "..", "..");
const tokensCss = readFileSync(
  join(repoRoot, "design", "tokens", "tokens.css"),
  "utf8",
);
const themeCss = readFileSync(
  join(repoRoot, "design", "tokens", "tailwind-theme.css"),
  "utf8",
);

test("Skeleton shape=row: height is the row-comfortable token, not a literal", () => {
  const markup = renderToStaticMarkup(<Skeleton shape="row" />);
  expect(markup, "the row skeleton wears the spacing-token utility").toContain(
    "h-row-comfortable",
  );
  expect(
    markup.match(/h-\d+(\.\d+)?/g) ?? [],
    "no numeric height utility may sit on the row skeleton",
  ).toEqual([]);
  expect(
    markup.match(/h-\[/g) ?? [],
    "no arbitrary-value height may sit on the row skeleton",
  ).toEqual([]);

  // The chain resolves: the utility is generated from a --spacing mapping
  // that references the token, and the token is a concrete length.
  expect(themeCss).toContain(
    "--spacing-row-comfortable: var(--sp-row-comfortable);",
  );
  const declared = tokensCss.match(/--sp-row-comfortable:\s*([^;]+);/)?.[1];
  expect(
    declared,
    "--sp-row-comfortable must be declared in tokens.css",
  ).toBeDefined();
  expect(declared?.trim()).toMatch(/^\d+px$/);
});

// ---------------------------------------------------------------------------
// Mandated: MetricTile value=null renders the unavailable tile — the em
// dash of the partial-counter contract (ADR-0025), never an error.
// ---------------------------------------------------------------------------

test("MetricTile: a null counter renders the em-dash unavailable tile", () => {
  const markup = renderToStaticMarkup(
    <MetricTile label="Broken" value={null} />,
  );
  expect(markup).toContain("—");
  expect(markup).not.toContain('role="alert"');
  // zero is a number, not a missing counter — the two must not collapse
  expect(renderToStaticMarkup(<MetricTile label="Zero" value={0} />)).toContain(
    ">0<",
  );
});

// ---------------------------------------------------------------------------
// Both themes: components consume semantic utilities, so data-theme="dark"
// needs no per-component branch — and every semantic utility used must
// actually resolve (a token declared in tokens.css but never mapped in
// tailwind-theme.css paints nothing and fails silently: DESIGN_SYSTEM
// "Tokens", UI_STATES §2).
// ---------------------------------------------------------------------------

test("every component renders under data-theme=dark with identical markup", () => {
  for (const [name, node] of LIBRARY) {
    const bare = rendered.get(name)!;
    expect(bare.length, `${name} rendered nothing`).toBeGreaterThan(0);
    const dark = renderToStaticMarkup(<div data-theme="dark">{node}</div>);
    expect(
      dark,
      `${name} branches on theme — it must consume semantic utilities instead`,
    ).toBe(`<div data-theme="dark">${bare}</div>`);
  }
});

/** Class tokens like `disabled:hover:bg-subtle` → `bg-subtle`. */
function bareUtility(token: string): string {
  return token.split(":").at(-1) ?? token;
}

const COLOUR_PREFIXES = new Set([
  "bg",
  "text",
  "border",
  "ring",
  "stroke",
  "fill",
  "outline",
  "decoration",
  "divide",
  "accent",
  "caret",
  "from",
  "via",
  "to",
]);

const KEYWORD_VALUES = new Set([
  "transparent",
  "current",
  "inherit",
  "white",
  "black",
  "none",
  "left",
  "right",
  "center",
  "full",
]);

const declaredThemeVars = new Set(
  [...themeCss.matchAll(/^(  )(--[a-z0-9*-]+):/gm)].map((m) => m[2]),
);

test("every colour utility in the library resolves through the theme", () => {
  const unresolved: string[] = [];
  for (const [name, markup] of rendered) {
    const classes = new Set(
      [...markup.matchAll(/class="([^"]*)"/g)]
        .flatMap((m) => m[1]!.split(/\s+/))
        .map(bareUtility),
    );
    for (const cls of classes) {
      const dash = cls.indexOf("-");
      if (dash === -1) continue;
      const prefix = cls.slice(0, dash);
      const rest = cls.slice(dash + 1);
      if (!COLOUR_PREFIXES.has(prefix)) continue;
      if (KEYWORD_VALUES.has(rest)) continue;
      if (/^\d/.test(rest)) continue; // widths: border-2, ring-2, text-2xs…
      if (/^(b|t|l|r|x|y)(-\d+)?$/.test(rest)) continue; // border sides
      if (/^(offset-|inset)/.test(rest)) continue; // ring-offset-*, ring-inset
      const candidates =
        prefix === "text"
          ? [`--color-${rest}`, `--text-${rest}`] // colour or font size
          : [`--color-${rest}`];
      if (!candidates.some((v) => declaredThemeVars.has(v))) {
        unresolved.push(`${name}: ${cls} (no ${candidates.join(" / ")})`);
      }
    }
  }
  expect(
    unresolved,
    "utilities that generate nothing paint nothing — the token must be " +
      "mapped in design/tokens/tailwind-theme.css (UI_STATES §2):\n" +
      unresolved.join("\n"),
  ).toEqual([]);
});

// Theme-constant by design: the brand ramp and the brand-500 focus colour do
// not shift in dark mode (tokens.css has no dark override for them), nor does
// the on-brand ink that reads against that constant ramp.
const THEME_CONSTANT = new Set([
  "--sp-brand-50",
  "--sp-brand-600",
  "--sp-brand-700",
  "--sp-border-focus",
  "--sp-on-brand",
]);

test("every token the library consumes has a dark value", () => {
  expect(tokensCss).toContain(':root[data-theme="dark"]');
  const darkBlock = tokensCss.slice(
    tokensCss.indexOf(':root[data-theme="dark"]'),
  );
  const darkTokens = new Set(
    [...darkBlock.matchAll(/(--sp-[a-z0-9-]+)\s*:/g)].map((m) => m[1]),
  );

  // colourMapping: "--color-ink" → "var(--sp-text-primary)" — parsed once.
  const colourMapping = new Map(
    [...themeCss.matchAll(/^  (--color-[a-z0-9-]+):\s*([^;]+);/gm)]
      .filter((m) => !m[1]!.includes("*"))
      .map((m) => [m[1]!, m[2]!]),
  );

  const consumed = new Set<string>();
  for (const markup of rendered.values()) {
    for (const cls of [...markup.matchAll(/class="([^"]*)"/g)]
      .flatMap((m) => m[1]!.split(/\s+/))
      .map(bareUtility)) {
      const dash = cls.indexOf("-");
      if (dash === -1) continue;
      if (!COLOUR_PREFIXES.has(cls.slice(0, dash))) continue;
      const rest = cls.slice(dash + 1);
      if (KEYWORD_VALUES.has(rest) || /^\d/.test(rest)) continue;
      const value = colourMapping.get(`--color-${rest}`);
      const token = value?.match(/var\((--sp-[a-z0-9-]+)\)/)?.at(1);
      if (token && !THEME_CONSTANT.has(token)) consumed.add(token);
    }
  }
  expect(consumed.size).toBeGreaterThan(0);
  const missing = [...consumed].filter((token) => !darkTokens.has(token));
  expect(
    missing,
    "tokens without a dark value silently keep their light value — a dark " +
      "mode that is the light theme (DESIGN_SYSTEM anti-patterns):\n" +
      missing.join("\n"),
  ).toEqual([]);
});

// ---------------------------------------------------------------------------
// No raw palette: the src/-wide palette-guard keeps watching everything;
// this guard names the 3.9 deliverable specifically — all 31 component
// files, counted, zero raw palette or arbitrary-colour utilities.
// ---------------------------------------------------------------------------

const PALETTE_UTILITY =
  /(^|[^a-z-])(?:bg|text|border|ring|fill|stroke|from|via|to|shadow|outline|decoration|divide|accent|caret)-(?:[trblxyse]-)?(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-[0-9]{2,3}\b/;
const ARBITRARY_COLOUR =
  /(?:bg|text|border|ring|fill|stroke|from|via|to|shadow|outline|decoration|divide|accent|caret)-\[(?:#|rgb|hsl|oklch|lab|color\()/;

test("components/ carries no raw palette classes — all 31 files scanned", () => {
  const dir = join(import.meta.dirname, "..", "src", "components");
  const files = readdirSync(dir)
    .filter((f) => f.endsWith(".tsx"))
    .sort();
  expect(files.length, "the coded library is 31 components + ThemeToggle").toBe(
    32,
  );
  const violations: string[] = [];
  for (const file of files) {
    readFileSync(join(dir, file), "utf8")
      .split("\n")
      .forEach((line, i) => {
        if (PALETTE_UTILITY.test(line) || ARBITRARY_COLOUR.test(line)) {
          violations.push(`${file}:${i + 1}: ${line.trim()}`);
        }
      });
  }
  expect(
    violations,
    "raw palette classes are a defect (AGENTS rule 6)",
  ).toEqual([]);
});
