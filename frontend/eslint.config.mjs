import js from "@eslint/js";

// Minimal on purpose: typescript@7 (the Go port) has no JS API, so
// typescript-eslint cannot attach — tsc --noEmit is the type check and
// prettier owns formatting. This keeps eslint running its JS-recommended
// rules over what it can parse (the .mjs/.js config files) so the tool
// stays wired for whenever TS 7 gains parser support. tests/palette-guard
// .test.ts is the real source of the "no raw palette classes" rule.
export default [
  { ignores: ["dist/", "node_modules/"] },
  js.configs.recommended,
];
