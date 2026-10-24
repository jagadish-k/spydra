// The story-matrix drift guard (chore/3.9, ADR-0043). Stories are
// documentation that mirrors UI_STATES §3 — nothing runs them in `make
// test-web`, so nothing else notices when the mirror rots. Two failure
// modes go red here: a library component that ships without a sibling
// stories file (the next screen slice adds <Widget> and forgets it), and
// a stories file with zero named stories (a rename or a bad merge leaves
// a shell). Raw-palette coverage of stories is NOT repeated: both
// palette-guard.test.ts (walks src/) and design-system.test.tsx (scans
// *.stories.tsx explicitly) already cover them.
//
// preview.tsx is shape-checked by regex, not imported: it is JSX-bearing
// TSX deliberately outside tsconfig.include (.storybook/ is Storybook's
// own runtime surface), and for config-of-config the shape is the
// contract — importing it would pull SB's runtime into vitest for no
// extra assurance.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

const componentsDir = join(import.meta.dirname, "..", "src", "components");

// ThemeToggle is app chrome, not the coded library (chore/3.9 contract).
const EXCLUDED = new Set(["ThemeToggle.tsx"]);

test("every library component has a sibling stories file", () => {
  const missing = readdirSync(componentsDir)
    .filter(
      (f) =>
        f.endsWith(".tsx") && !f.endsWith(".stories.tsx") && !EXCLUDED.has(f),
    )
    .filter(
      (f) => !existsSync(join(componentsDir, `${f.slice(0, -4)}.stories.tsx`)),
    );
  expect(
    missing,
    "a coded-library component without stories is undocumented — add " +
      "<Component>.stories.tsx with one named story per persistent axis " +
      "value (UI_STATES §3, ADR-0043):\n" +
      missing.join("\n"),
  ).toEqual([]);
});

test("every stories file exports at least one named story", () => {
  const empty: string[] = [];
  for (const f of readdirSync(componentsDir).filter((f) =>
    f.endsWith(".stories.tsx"),
  )) {
    const source = readFileSync(join(componentsDir, f), "utf8");
    // The coded CSF3 shape is `export const Name: Story = …` beside
    // `export default meta` — any export const other than `meta` is a
    // story. Counting that shape is the grep-able contract; it stays
    // honest under CSF's `export const meta` spelling too.
    const stories = source.match(/^export const (?!meta\b)\w+/gm) ?? [];
    if (stories.length === 0) empty.push(f);
  }
  expect(
    empty,
    "a stories file with zero named stories renders nothing in SB and " +
      "captures nothing in Chromatic — it is a shell:\n" +
      empty.join("\n"),
  ).toEqual([]);
});

test("preview wires the theme global onto the story canvas", () => {
  const preview = readFileSync(
    join(import.meta.dirname, "..", ".storybook", "preview.tsx"),
    "utf8",
  );
  const items = preview.match(
    /theme:\s*\{[^{}]*toolbar:\s*\{[^{}]*items:\s*\[([^\]]*)\]/,
  )?.[1];
  expect(
    items,
    "globalTypes.theme must declare toolbar items — without them there " +
      "is no light/dark switch and dark tokens are unreachable in SB",
  ).toBeDefined();
  expect(items).toContain('"light"');
  expect(items).toContain('"dark"');
  // Dark tokens are scoped `:root[data-theme="dark"]`, so the wiring must
  // land on documentElement — a wrapper <div data-theme> matches nothing.
  expect(preview).toMatch(
    /document\.documentElement\.(?:setAttribute\(\s*"data-theme"|dataset\.theme)/,
  );
});
