# 0018 — React 19 and Tailwind v4

**Status:** Accepted · 2026-10-15
**Supersedes:** ADR-0011

## Context

ADR-0011 chose React 18 and Tailwind v3. The Tailwind decision was made to
preserve the existing `tailwind.config.ts`, which maps semantic tokens and
removes the default palette so a raw `text-red-600` fails to compile.

The operator wants the latest versions (ADR-0017). Tailwind v4 moves
configuration out of JavaScript and into CSS, which means re-expressing that
mapping — the cost ADR-0011 declined to pay.

## Decision

**React 19** and **Tailwind v4**.

The token mapping moves from `tailwind.config.ts` to CSS-first `@theme`
declarations in `frontend/src/styles/theme.css`. The semantic layer is
unchanged — the same token names, the same two themes, the same rule that
colour carries state and nothing else:

```css
@import "tailwindcss";
@import "../../../design/tokens/tokens.css";
@import "../../../design/tokens/tailwind-theme.css";
```

**Carrying this out surfaced a collision that had to be fixed first.**
Tailwind v4 claims `--color-*`, `--text-*`, `--font-*`, `--radius-*`,
`--shadow-*`, `--leading-*`, `--tracking-*` and `--ease-*` as theme
namespaces. 36 of the project's 116 design tokens sat inside one of them.

The worst case was `--text-*`, which in `tokens.css` holds both font sizes
*and* text colours. Tailwind reads that namespace as font-size, so
`--text-primary: #16191F` would have become a font-size utility whose value
is a hex colour — **no error, no warning, just a broken utility**. Writing
`--text-md: var(--text-md)` in `@theme` is also circular and silently
resolves to nothing.

So every design token is now prefixed **`--sp-*`** (846 references renamed
across `tokens.css`, the mockup stylesheet and the nine mockup pages), and
`design/tokens/tailwind-theme.css` maps `--sp-*` onto Tailwind's namespace.
The prefix makes the collision structurally impossible rather than something
to remember.

**The default palette is still removed.** In v4 that is
`--color-*: initial;` as the first line inside `@theme`, before the semantic
set is declared. This keeps the ADR-0011 guarantee intact: `text-red-600`
does not compile. It is the only thing making "colour carries state"
structural rather than aspirational, and it is the part of the migration
most likely to be dropped silently.

From React 19 the project uses: the `use` hook where it simplifies a
suspense boundary, ref-as-prop (no more `forwardRef` ceremony), and the
improved hydration diagnostics. It does **not** adopt Server Components —
this is a client-rendered SPA behind a BFF, and RSC would mean a rendering
server the topology does not have.

## Consequences

- One source of truth for tokens, in CSS, which is where the design system
  already lives. The `tailwind.config.ts` indirection disappears.
- Tailwind v4's build is substantially faster, which matters given polling
  file-watchers over a bind mount (ADR-0010).
- `forwardRef` removal simplifies every component that wraps an input — and
  the design system has several.
- **Utility names changed with the prefix.** `text-secondary` is now
  `text-ink-muted`, `bg-base` is `bg-canvas`. The mapping table is in
  `tailwind-theme.css`; `DESIGN_SYSTEM.md` carries the same table.
- **Cost:** the token rename touched 846 references across the design system
  and all nine mockups. They were re-verified rendering in both themes
  afterwards, which is the only way to check this — a clean build with a
  broken palette removal looks identical to a correct one until someone
  writes `bg-red-500` and it works. Any v3-shaped Tailwind knowledge is now
  wrong, and so is any memory of the old token names.
