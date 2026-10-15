# 0011 — React + TypeScript + Vite + Tailwind v3

**Status:** Superseded by [ADR-0018](0018-react19-tailwind4.md) · 2026-10-15

> Superseded the same day it was written: the operator asked for latest
> versions, which reverses the React 18 and Tailwind v3 choices below. The
> *reasoning* for the surrounding choices — TanStack Query, no global store,
> URL-encoded filter state, hand-written sparklines — still stands and is
> carried forward.

## Context

The operator asked for React, in TypeScript, built with Vite. The remaining
choices are the ones that surround it: styling, server state, routing, tables,
charts.

The design system already exists as CSS custom properties plus a
`tailwind.config.ts` written in Tailwind v3's config format, and the nine
screens already exist as static HTML mockups built against it.

## Decision

- **React 18 + TypeScript strict + Vite.** `strict: true` and
  `noUncheckedIndexedAccess: true`. No `any`.
- **Tailwind CSS v3**, not v4. v4 moves configuration into CSS (`@theme`) and
  would require rewriting the existing `tailwind.config.ts` and re-deriving
  the token mapping. The config **replaces** the default palette rather than
  extending it, so a raw `text-red-600` fails to compile — this is how the
  "colour carries state only" rule is enforced structurally rather than by
  review.
- **TanStack Query** for all server state. **No global store.** Local UI state
  is `useState` or context; a screen's filter state lives in the URL.
- **React Router** for routing, with filter and sort state encoded in the
  query string so any view is linkable.
- **TanStack Table** for the data tables, headless so it uses the design
  system's markup.
- **Recharts** for the two real charts (run throughput, price history).
  Sparklines are hand-written SVG — they are a seven-point polyline and a
  charting library is heavier than the thing it draws.
- **react-hook-form + zod** for the template editor, the one genuinely complex
  form.

## Consequences

- The mockups transfer directly: same tokens, same class names, same markup.
- Server state has one owner, so cache invalidation after a mutation is a
  single concern.
- **Cost:** Tailwind v3 is a deliberate step behind current. Migrating to v4
  later means re-expressing the token mapping in CSS — a contained change,
  but one someone will have to do. Recharts is heavier than the two charts
  strictly need; it earns its place only if the dashboards grow.
