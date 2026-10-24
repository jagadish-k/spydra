// Variant-matrix coverage for the fourteen §3a atoms (UI_STATES §3a; the
// coded-library table in DESIGN_SYSTEM is the prop reference). Assertions
// come from the matrix: every axis value renders, and renders markup the
// other values do not — a component shipping only its populated path is the
// failure mode this suite exists to catch (ADR-0025).
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Banner } from "../src/components/Banner";
import { Button } from "../src/components/Button";
import { Card } from "../src/components/Card";
import { Confidence } from "../src/components/Confidence";
import { Input } from "../src/components/Input";
import { MetricTile } from "../src/components/MetricTile";
import { ProgressBar } from "../src/components/ProgressBar";
import { SampleCell } from "../src/components/SampleCell";
import { SelectorField } from "../src/components/SelectorField";
import { Sparkline } from "../src/components/Sparkline";
import { StatePill } from "../src/components/StatePill";
import { Tabs } from "../src/components/Tabs";
import { Tag } from "../src/components/Tag";
import { ValidationBadge } from "../src/components/ValidationBadge";
import { click, findAll, findOne, prop } from "./helpers/element-tree";

type Component<P> = (props: P) => ReactNode;

/** Render one arm of a variant axis to markup. */
function arm<P extends object>(component: Component<P>, props: P): string {
  return renderToStaticMarkup(createElement(component, props));
}

/** Every axis value must produce pairwise-distinct markup. */
function expectDistinct(arms: ReadonlyArray<readonly [string, string]>): void {
  const byMarkup = new Map<string, string[]>();
  for (const [name, markup] of arms) {
    byMarkup.set(markup, [...(byMarkup.get(markup) ?? []), name]);
  }
  const duplicates = [...byMarkup.values()].filter((names) => names.length > 1);
  expect(
    duplicates,
    `axis values rendered identical markup: ${duplicates.map((n) => n.join(" ≡ ")).join("; ")}`,
  ).toEqual([]);
}

const noop = (): void => undefined;
// Controlled inputs without onChange render read-only warnings in SSR noise;
// every arm that sets a value carries a no-op onChange to keep output clean.
const typing = { value: "x", onChange: noop } as const;

// ---------------------------------------------------------------------------
// Button — 4 styles × 2 sizes; State=loading holds the label; disabled
// ---------------------------------------------------------------------------

test("Button: every variant renders distinct markup", () => {
  const variants = (["primary", "secondary", "ghost", "danger"] as const).map(
    (variant) => [variant, arm(Button, { variant, children: "Go" })] as const,
  );
  expectDistinct(variants);
  expect(variants[0]![1]).toContain("bg-brand");
  expect(variants[3]![1]).toContain("text-state-broken");
});

test("Button: sm and md sizes are distinguishable", () => {
  expect(arm(Button, { size: "sm", children: "Go" })).not.toBe(
    arm(Button, { size: "md", children: "Go" }),
  );
});

test("Button: loading keeps the label and joins a spinner", () => {
  const markup = arm(Button, { loading: true, children: "Approve" });
  expect(markup).toContain("Approve");
  expect(markup).toContain('role="status"');
  expect(markup).toContain('aria-busy="true"');
  // loading disables, so the click cannot double-fire
  expect(markup).toContain("disabled");
});

test("Button: disabled renders the disabled arm", () => {
  expect(arm(Button, { disabled: true, children: "Go" })).toContain("disabled");
});

// ---------------------------------------------------------------------------
// Input — error · disabled · readonly · with-prefix · with-clear; focus ring
// ---------------------------------------------------------------------------

test("Input: error is the invalid arm, distinct from the default field", () => {
  const error = arm(Input, { error: true, ...typing });
  expect(error).toContain('aria-invalid="true"');
  expect(error).toContain("border-state-broken");
  expectDistinct([
    ["default", arm(Input, { ...typing })],
    ["error", error],
  ]);
});

test("Input: disabled and readonly are distinct reductions", () => {
  const disabled = arm(Input, { disabled: true, ...typing });
  const readOnly = arm(Input, { readOnly: true, ...typing });
  expectDistinct([
    ["default", arm(Input, { ...typing })],
    ["disabled", disabled],
    ["readonly", readOnly],
  ]);
  expect(disabled).toContain("disabled");
  expect(readOnly).toContain("bg-inset");
});

test("Input: prefix renders inside the field", () => {
  expect(arm(Input, { prefix: "https://", ...typing })).toContain("https://");
});

test("Input: clear appears only with a value and fires onClear", () => {
  expect(
    arm(Input, { onClear: noop, value: "", onChange: noop }),
  ).not.toContain('aria-label="Clear"');
  let cleared = 0;
  const tree = Input({ onClear: () => (cleared += 1), value: "abc" });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Clear"));
  expect(cleared).toBe(1);
});

test("Input: the focus arm is drawn (focus-within ring on the wrapper)", () => {
  expect(arm(Input, { ...typing })).toContain("focus-within:ring-focus");
});

// ---------------------------------------------------------------------------
// Card — hover · selected · as-skeleton
// ---------------------------------------------------------------------------

test("Card: interactive carries the hover arm", () => {
  expect(arm(Card, { interactive: true, children: "c" })).toContain(
    "hover:border-line-strong",
  );
});

test("Card: selected is the focus-bordered selected surface", () => {
  const selected = arm(Card, { selected: true, children: "c" });
  expect(selected).toContain("border-focus");
  expect(selected).toContain("bg-selected");
});

test("Card: loading swaps content for a skeleton, holding the layout", () => {
  const loading = arm(Card, { loading: true, children: "real content" });
  expect(loading).not.toContain("real content");
  expect(loading).toContain("animate-pulse");
});

// ---------------------------------------------------------------------------
// Tag — tones × removable × disabled
// ---------------------------------------------------------------------------

test("Tag: all five tones render distinct feedback pairs", () => {
  const tones = (
    ["neutral", "info", "success", "warning", "danger"] as const
  ).map((tone) => [tone, arm(Tag, { tone, children: "t" })] as const);
  expectDistinct(tones);
  expect(tones[2]![1]).toContain("text-state-active");
  expect(tones[4]![1]).toContain("text-state-broken");
});

test("Tag: removable adds the remove control, absent when not removable", () => {
  expect(arm(Tag, { removable: true, children: "t" })).toContain(
    'aria-label="Remove tag"',
  );
  expect(arm(Tag, { children: "t" })).not.toContain('aria-label="Remove tag"');
});

test("Tag: onRemove fires when removable, and is unreachable otherwise", () => {
  let removed = 0;
  const tree = Tag({
    removable: true,
    onRemove: () => (removed += 1),
    children: "t",
  });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Remove tag"));
  expect(removed).toBe(1);
});

test("Tag: disabled disables the remove control too", () => {
  const markup = arm(Tag, {
    removable: true,
    disabled: true,
    children: "t",
  });
  expect(markup).toContain('aria-label="Remove tag"');
  expect(markup).toContain("disabled");
  expect(markup).toContain("opacity-50");
});

// ---------------------------------------------------------------------------
// ProgressBar — stacked · determinate · indeterminate · complete · failed
// ---------------------------------------------------------------------------

test("ProgressBar: the stacked bar shows all four run states, never a percentage", () => {
  const markup = arm(ProgressBar, {
    segments: { queued: 10, inFlight: 5, done: 4, failed: 1 },
    legend: true,
  });
  expect(markup).toContain("bg-line-strong"); // queued
  expect(markup).toContain("bg-viz-1"); // in flight
  expect(markup).toContain("bg-state-active"); // done
  expect(markup).toContain("bg-state-broken"); // failed
  expect(markup).toContain("in flight (5)");
  expect(markup).toContain("queued (10)");
  // "never a percentage" (UI_STATES §3a): the *displayed* legend counts
  // segments — inline width styles are geometry, not a user-visible %.
  const textContent = markup.replace(/<[^>]*>/g, "");
  expect(textContent).not.toContain("%");
});

test("ProgressBar: a zero-count segment renders nothing", () => {
  const markup = arm(ProgressBar, {
    segments: { queued: 0, inFlight: 0, done: 3, failed: 0 },
  });
  expect(markup).not.toContain("bg-state-broken");
});

test("ProgressBar: single-state axis renders five distinct arms", () => {
  expectDistinct(
    (["running", "paused", "complete", "failed", "empty"] as const).map(
      (state) => [state, arm(ProgressBar, { state })] as const,
    ),
  );
});

test("ProgressBar: complete is full, empty is zero, failed carries broken", () => {
  expect(arm(ProgressBar, { state: "complete" })).toContain("width:100%");
  expect(arm(ProgressBar, { state: "empty" })).toContain("width:0%");
  expect(arm(ProgressBar, { state: "failed" })).toContain("bg-state-broken");
});

test("ProgressBar: determinate honours fraction, indeterminate pulses", () => {
  expect(arm(ProgressBar, { fraction: 0.5 })).toContain("width:50%");
  const indeterminate = arm(ProgressBar, {});
  expect(indeterminate).toContain("animate-pulse");
});

// ---------------------------------------------------------------------------
// Tabs — selected/default · disabled · with-count-badge · onChange
// ---------------------------------------------------------------------------

const TAB_ITEMS = [
  { id: "one", label: "One" },
  { id: "two", label: "Two", count: 7 },
  { id: "three", label: "Three", disabled: true },
] as const;

test("Tabs: selection marks exactly the chosen tab", () => {
  const markup = arm(Tabs, { items: TAB_ITEMS, value: "two" });
  expect(markup).toContain('aria-selected="true"');
  expect(markup).toContain("border-brand");
  const unselected = arm(Tabs, { items: TAB_ITEMS, value: "one" });
  expect(unselected).toContain('aria-selected="false"');
});

test("Tabs: a disabled tab is disabled, with the count badge on the other", () => {
  const markup = arm(Tabs, { items: TAB_ITEMS, value: "one" });
  expect(markup).toContain("disabled");
  expect(markup).toContain("tabular-nums");
  expect(markup).toContain("7");
});

test("Tabs: onChange receives the clicked tab's id", () => {
  let selected = "";
  const tree = Tabs({
    items: TAB_ITEMS,
    value: "one",
    onChange: (id) => (selected = id),
  });
  const clickable = findAll(
    tree,
    (el) =>
      prop(el, "role") === "tab" &&
      prop(el, "aria-selected") === false && // not the current tab
      prop(el, "disabled") !== true, // not the disabled arm
  );
  expect(clickable.length).toBe(1);
  click(clickable[0]!);
  expect(selected).toBe("two");
});

// ---------------------------------------------------------------------------
// StatePill — the six lifecycle states
// ---------------------------------------------------------------------------

test("StatePill: six distinct lifecycle pills; why surfaces as tooltip", () => {
  const states = (
    ["discovered", "pending", "active", "broken", "paused", "archived"] as const
  ).map((state) => [state, arm(StatePill, { state })] as const);
  expectDistinct(states);
  expect(states[3]![1]).toContain("text-state-broken");
  expect(arm(StatePill, { state: "active", why: "threshold" })).toContain(
    'title="threshold"',
  );
});

// ---------------------------------------------------------------------------
// MetricTile — loaded · loading · unavailable; three tones
// ---------------------------------------------------------------------------

test("MetricTile: the three tones read as ink · attention · danger", () => {
  const tones = (["default", "attention", "danger"] as const).map(
    (tone) =>
      [tone, arm(MetricTile, { label: "Domains", value: 3, tone })] as const,
  );
  expectDistinct(tones);
  expect(tones[1]![1]).toContain("text-state-pending");
  expect(tones[2]![1]).toContain("text-state-broken");
});

test("MetricTile: loading swaps the value for a skeleton, label held", () => {
  const markup = arm(MetricTile, { label: "Domains", value: 3, loading: true });
  expect(markup).toContain("Domains");
  expect(markup).toContain("animate-pulse");
  expect(markup).not.toContain(">3<");
});

// ---------------------------------------------------------------------------
// Banner — 3 tones × dismissible × with-action
// ---------------------------------------------------------------------------

test("Banner: three tones render distinct feedback styling", () => {
  const tones = (["info", "warning", "danger"] as const).map(
    (tone) => [tone, arm(Banner, { tone, children: "note" })] as const,
  );
  expectDistinct(tones);
  expect(tones[2]![1]).toContain("border-state-broken");
});

test("Banner: the action renders and fires", () => {
  let acted = 0;
  const tree = Banner({
    action: { label: "Undo", onAction: () => (acted += 1) },
    children: "note",
  });
  click(findOne(tree, (el) => prop(el, "children") === "Undo"));
  expect(acted).toBe(1);
});

test("Banner: dismiss appears only when dismissible, and fires", () => {
  expect(arm(Banner, { children: "note" })).not.toContain(
    'aria-label="Dismiss"',
  );
  let dismissed = 0;
  const tree = Banner({
    dismissible: true,
    onDismiss: () => (dismissed += 1),
    children: "note",
  });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Dismiss"));
  expect(dismissed).toBe(1);
});

// ---------------------------------------------------------------------------
// SelectorField — default · resolving · no-match · warning · invalid · disabled
// ---------------------------------------------------------------------------

test("SelectorField: the whole state axis renders distinctly from `matches`", () => {
  const armsByMatches: ReadonlyArray<[string, string]> = [
    ["resolving", arm(SelectorField, { selector: "a", matches: null })],
    ["no-match", arm(SelectorField, { selector: "a", matches: 0 })],
    ["default", arm(SelectorField, { selector: "a", matches: 1 })],
    ["warning", arm(SelectorField, { selector: "a", matches: 6 })],
  ];
  expectDistinct(armsByMatches);
  expect(armsByMatches[0]![1]).toContain("resolving");
  expect(armsByMatches[1]![1]).toContain("no matches");
  expect(armsByMatches[1]![1]).not.toContain("border-state-broken"); // muted, not an error
  expect(armsByMatches[3]![1]).toContain("border-state-pending");
});

test("SelectorField: invalid is the red arm, distinct from no-match", () => {
  const invalid = arm(SelectorField, {
    selector: "a[",
    matches: 1,
    invalid: true,
  });
  expect(invalid).toContain('aria-invalid="true"');
  expect(invalid).toContain("border-state-broken");
  expect(invalid).not.toContain("no matches");
});

test("SelectorField: disabled disables the input", () => {
  expect(
    arm(SelectorField, { selector: "a", matches: 1, disabled: true }),
  ).toContain("disabled");
});

test("SelectorField: a resolved sample shows; unresolved says so", () => {
  expect(
    arm(SelectorField, { selector: "a", matches: 1, resolved: "£4.50" }),
  ).toContain("£4.50");
  const unresolved = arm(SelectorField, { selector: "a", matches: 1 });
  expect(unresolved).toContain("unresolved");
});

// ---------------------------------------------------------------------------
// Confidence — high · good · medium · low (4→1 lit bars carry the signal)
// ---------------------------------------------------------------------------

test("Confidence: four levels, lit bars descending 4-3-2-1", () => {
  const expectedLit = { high: 4, good: 3, medium: 2, low: 1 } as const;
  for (const level of ["high", "good", "medium", "low"] as const) {
    const markup = arm(Confidence, { level });
    const unlit = markup.match(/bg-line-strong/g)?.length ?? 0;
    expect(unlit, `${level} leaves ${4 - expectedLit[level]} bars unlit`).toBe(
      4 - expectedLit[level],
    );
    expect(markup).toContain(`model confidence: ${level}`);
  }
  expect(arm(Confidence, { level: "low" })).toContain("bg-state-broken");
  expect(arm(Confidence, { level: "medium" })).toContain("bg-state-pending");
});

// ---------------------------------------------------------------------------
// ValidationBadge — pass · partial · fail × count · rule
// ---------------------------------------------------------------------------

test("ValidationBadge: three verdicts, counts and rule tooltip", () => {
  const kinds = (["pass", "partial", "fail"] as const).map(
    (kind) => [kind, arm(ValidationBadge, { kind })] as const,
  );
  expectDistinct(kinds);
  expect(kinds[0]![1]).toContain("pass");
  expect(kinds[2]![1]).toContain("fail");
  expect(arm(ValidationBadge, { kind: "fail", count: 2 })).toContain("2");
  expect(arm(ValidationBadge, { kind: "fail", rule: "required" })).toContain(
    'title="required"',
  );
});

// ---------------------------------------------------------------------------
// SampleCell — pass · fail · partial · pending (pending is neutral)
// ---------------------------------------------------------------------------

test("SampleCell: four results; pending is a neutral dash, not an error", () => {
  const results = (["pass", "fail", "partial", "pending"] as const).map(
    (result) => [result, arm(SampleCell, { result })] as const,
  );
  expectDistinct(results);
  expect(results[0]![1]).toContain("text-state-active");
  expect(results[1]![1]).toContain("text-state-broken");
  expect(results[3]![1]).toContain("—");
  expect(results[3]![1]).not.toContain("state-broken");
});

// ---------------------------------------------------------------------------
// Sparkline — healthy · slipping · failing · pending (flat line)
// ---------------------------------------------------------------------------

test("Sparkline: four trends paint distinct strokes", () => {
  const values = [1, 2, 1.5, 3, 2.5] as const;
  const trends = (["healthy", "slipping", "failing", "pending"] as const).map(
    (trend) => [trend, arm(Sparkline, { values, trend })] as const,
  );
  expectDistinct(trends);
  expect(trends[0]![1]).toContain("stroke-state-active");
  expect(trends[2]![1]).toContain("stroke-state-broken");
});

test("Sparkline: pending with no data draws the flat pending line", () => {
  const markup = arm(Sparkline, { values: [], trend: "pending" });
  expect(markup).toContain("stroke-line-strong");
  const path = markup.match(/ d="([^"]*)"/)?.[1] ?? "";
  expect(path.startsWith("M")).toBe(true);
  expect(path, "the pending line is flat — no slope segments").not.toContain(
    "L",
  );
});
