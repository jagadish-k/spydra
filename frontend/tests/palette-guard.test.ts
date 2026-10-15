import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

// BUILD_PLAN 0.12: "Assert bg-red-500 fails the build." In Tailwind v4 an
// unknown utility in markup is silently not generated — only @apply errors —
// so the guarantee is enforced here instead, as two asserts:
//
//   1. structural — tailwind-theme.css still removes the default palette
//      (`--color-*: initial;`). Without that line raw colours compile and
//      "colour carries state" becomes a convention (ADR-0018).
//   2. source scan — no raw palette utility anywhere in src/ or index.html.
//
// ../design resolves to the read-only /design mount in the container and to
// the repo's design/ on a host checkout — same path trick as theme.css.

const PALETTE_UTILITY =
  /(^|[^a-z-])(?:bg|text|border|ring|fill|stroke|from|via|to|shadow|outline|decoration|divide|accent|caret)-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-[0-9]{2,3}\b/;

const SCANNED_EXTENSIONS = new Set([".ts", ".tsx", ".css", ".html"]);

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const name of readdirSync(dir).sort()) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      files.push(...walk(path));
    } else {
      files.push(path);
    }
  }
  return files;
}

test("tailwind-theme.css removes the default palette (--color-*: initial)", () => {
  const themePath = join(
    import.meta.dirname,
    "..",
    "..",
    "design",
    "tokens",
    "tailwind-theme.css",
  );
  const css = readFileSync(themePath, "utf8");
  expect(
    css,
    "design/tokens/tailwind-theme.css must keep `--color-*: initial;` as " +
      "the first line inside @theme — deleting it silently re-admits the " +
      "whole Tailwind palette (ADR-0018)",
  ).toContain("--color-*: initial;");
});

test("no raw Tailwind palette utilities in src/ or index.html", () => {
  const frontendRoot = join(import.meta.dirname, "..");
  const targets = [
    join(frontendRoot, "index.html"),
    ...walk(join(frontendRoot, "src")),
  ].filter((path) => {
    const dot = path.lastIndexOf(".");
    const ext = dot === -1 ? "" : path.slice(dot);
    return SCANNED_EXTENSIONS.has(ext);
  });

  expect(
    targets.length,
    "the scan found nothing — it is looking in the wrong place",
  ).toBeGreaterThan(0);

  const violations: string[] = [];
  for (const path of targets) {
    const rel = path.slice(frontendRoot.length + 1);
    const lines = readFileSync(path, "utf8").split("\n");
    lines.forEach((line, index) => {
      if (PALETTE_UTILITY.test(line)) {
        violations.push(`${rel}:${index + 1}: ${line.trim()}`);
      }
    });
  }

  expect(
    violations,
    "raw Tailwind palette classes are a defect (AGENTS.md rule 6). Use the " +
      "semantic utilities from design/tokens/tailwind-theme.css instead:\n" +
      violations.join("\n"),
  ).toEqual([]);
});
