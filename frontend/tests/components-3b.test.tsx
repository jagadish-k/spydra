// Variant-matrix coverage for the seventeen §3b shared sets (UI_STATES §3b,
// prop reference in DESIGN_SYSTEM's coded-library table). Same rule as the
// §3a file: every axis value renders, distinctly — closed/open, hidden/
// visible, first/last/single-page, the arms a populated screenshot never
// shows.
import { createElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { BulkActionBar } from "../src/components/BulkActionBar";
import { Checkbox } from "../src/components/Checkbox";
import { EmptyState } from "../src/components/EmptyState";
import { ErrorState } from "../src/components/ErrorState";
import { FilterChip } from "../src/components/FilterChip";
import { LineChart } from "../src/components/LineChart";
import { Modal } from "../src/components/Modal";
import { Pagination } from "../src/components/Pagination";
import { RowActionMenu } from "../src/components/RowActionMenu";
import { SearchField } from "../src/components/SearchField";
import { Select } from "../src/components/Select";
import { Skeleton } from "../src/components/Skeleton";
import { Spinner } from "../src/components/Spinner";
import { TableHeaderCell } from "../src/components/TableHeaderCell";
import { Toast } from "../src/components/Toast";
import { Toggle } from "../src/components/Toggle";
import { Tooltip } from "../src/components/Tooltip";
import { click, findOne, prop } from "./helpers/element-tree";

type Component<P> = (props: P) => ReactNode;

function arm<P extends object>(component: Component<P>, props: P): string {
  return renderToStaticMarkup(createElement(component, props));
}

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

// Pagination's chevron buttons, reached by aria-label so assertions do not
// depend on React's attribute serialization order.
function prevButton(tree: ReactNode): ReactElement {
  return findOne(tree, (el) => prop(el, "aria-label") === "Previous page");
}
function nextButton(tree: ReactNode): ReactElement {
  return findOne(tree, (el) => prop(el, "aria-label") === "Next page");
}

// ---------------------------------------------------------------------------
// TableHeaderCell — Sort= none · asc · desc, sortable or not
// ---------------------------------------------------------------------------

test("TableHeaderCell: none/asc/desc render distinct sort arms", () => {
  const sortable = (sort: "none" | "asc" | "desc"): string =>
    arm(TableHeaderCell, { children: "Domain", sort, onSort: noop });
  expectDistinct([
    ["none", sortable("none")],
    ["asc", sortable("asc")],
    ["desc", sortable("desc")],
  ]);
  expect(sortable("none")).not.toContain("aria-sort");
  expect(sortable("asc")).toContain('aria-sort="ascending"');
  expect(sortable("desc")).toContain('aria-sort="descending"');
});

test("TableHeaderCell: the sort control is a button only when sortable", () => {
  const sortable = arm(TableHeaderCell, { children: "Domain", onSort: noop });
  const plain = arm(TableHeaderCell, { children: "Domain" });
  expect(sortable).toContain("hover:text-ink"); // the State=hover arm
  expect(plain).not.toContain("<button");
});

test("TableHeaderCell: onSort fires from the control", () => {
  let sorted = 0;
  const tree = TableHeaderCell({
    children: "Domain",
    onSort: () => (sorted += 1),
  });
  click(findOne(tree, (el) => el.type === "button"));
  expect(sorted).toBe(1);
});

// ---------------------------------------------------------------------------
// RowActionMenu — closed · open · item-hover · item-danger
// ---------------------------------------------------------------------------

const MENU_ACTIONS = [
  { id: "view", label: "View" },
  { id: "pause", label: "Pause" },
  { id: "delete", label: "Delete", danger: true },
  { id: "gone", label: "Unavailable", disabled: true },
] as const;

test("RowActionMenu: closed renders no menu; open renders the menuitems", () => {
  const closed = arm(RowActionMenu, { actions: MENU_ACTIONS, open: false });
  const open = arm(RowActionMenu, { actions: MENU_ACTIONS, open: true });
  expect(closed).not.toContain('role="menu"');
  expect(open).toContain('role="menu"');
  expect(open).toContain('aria-expanded="true"');
  expect(closed).toContain('aria-expanded="false"');
  expect(open.match(/role="menuitem"/g)?.length).toBe(4);
});

test("RowActionMenu: item-danger is the broken arm; item-hover is drawn", () => {
  const open = arm(RowActionMenu, { actions: MENU_ACTIONS, open: true });
  expect(open).toContain("text-state-broken"); // Delete
  expect(open).toContain("hover:bg-subtle"); // the item-hover arm
  expect(open).toContain("disabled"); // the unavailable item
});

test("RowActionMenu: onToggle and per-item onSelect fire", () => {
  let toggled = 0;
  let selected = "";
  const tree = RowActionMenu({
    actions: MENU_ACTIONS,
    open: true,
    onToggle: () => (toggled += 1),
    onSelect: (id) => (selected = id),
  });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Row actions"));
  expect(toggled).toBe(1);
  click(findOne(tree, (el) => prop(el, "children") === "Delete"));
  expect(selected).toBe("delete");
});

// ---------------------------------------------------------------------------
// FilterChip — default · hover · removable · active
// ---------------------------------------------------------------------------

test("FilterChip: active is the selected arm, default is a surface", () => {
  const active = arm(FilterChip, { active: true, children: "broken" });
  const idle = arm(FilterChip, { children: "broken" });
  expectDistinct([
    ["default", idle],
    ["active", active],
  ]);
  expect(active).toContain("bg-selected");
  expect(idle).toContain("hover:bg-subtle"); // the hover arm
});

test("FilterChip: removable shows the remove control only when asked", () => {
  expect(arm(FilterChip, { removable: true, children: "f" })).toContain(
    'aria-label="Remove filter"',
  );
  expect(arm(FilterChip, { children: "f" })).not.toContain(
    'aria-label="Remove filter"',
  );
});

test("FilterChip: onClick and onRemove both fire", () => {
  let clicked = 0;
  let removed = 0;
  const tree = FilterChip({
    children: "f",
    removable: true,
    onClick: () => (clicked += 1),
    onRemove: () => (removed += 1),
  });
  click(findOne(tree, (el) => prop(el, "children") === "f"));
  click(findOne(tree, (el) => prop(el, "aria-label") === "Remove filter"));
  expect(clicked).toBe(1);
  expect(removed).toBe(1);
});

// ---------------------------------------------------------------------------
// SearchField — empty · typing · with-clear · no-results
// ---------------------------------------------------------------------------

test("SearchField: empty shows no clear; typing shows it", () => {
  const empty = arm(SearchField, { value: "" });
  const typing = arm(SearchField, { value: "denim" });
  expect(empty).not.toContain('aria-label="Clear search"');
  expect(typing).toContain('aria-label="Clear search"');
  expectDistinct([
    ["empty", empty],
    ["typing", typing],
  ]);
});

test("SearchField: no-results appears only for a query that ran", () => {
  expect(arm(SearchField, { value: "denim", noResults: true })).toContain(
    "no results",
  );
  expect(arm(SearchField, { value: "denim" })).not.toContain("no results");
  expect(arm(SearchField, { value: "", noResults: true })).not.toContain(
    "no results",
  );
});

test("SearchField: clear resets through onChange, typing passes through", () => {
  let last = "init";
  const tree = SearchField({ value: "denim", onChange: (v) => (last = v) });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Clear search"));
  expect(last).toBe("");
  const input = findOne(tree, (el) => el.type === "input");
  (prop(input, "onChange") as (event: { target: { value: string } }) => void)({
    target: { value: "next" },
  });
  expect(last).toBe("next");
});

// ---------------------------------------------------------------------------
// BulkActionBar — hidden · visible
// ---------------------------------------------------------------------------

test("BulkActionBar: count 0 is the hidden state — nothing renders", () => {
  expect(arm(BulkActionBar, { count: 0, actions: [] })).toBe("");
});

test("BulkActionBar: visible shows the count, actions and clear", () => {
  const markup = arm(BulkActionBar, {
    count: 3,
    actions: [
      { id: "pause", label: "Pause" },
      { id: "delete", label: "Delete", danger: true },
    ],
    onClear: noop,
  });
  expect(markup).toContain('role="toolbar"');
  expect(markup).toContain("3 selected");
  expect(markup).toContain("Pause");
  expect(markup).toContain("text-state-broken"); // the danger action
  expect(markup).toContain("Clear");
});

test("BulkActionBar: actions and clear fire with their ids", () => {
  let acted = "";
  let cleared = 0;
  const tree = BulkActionBar({
    count: 2,
    actions: [{ id: "pause", label: "Pause" }],
    onAction: (id) => (acted = id),
    onClear: () => (cleared += 1),
  });
  click(findOne(tree, (el) => prop(el, "children") === "Pause"));
  expect(acted).toBe("pause");
  click(findOne(tree, (el) => prop(el, "children") === "Clear"));
  expect(cleared).toBe(1);
});

// ---------------------------------------------------------------------------
// Checkbox — unchecked · checked · indeterminate · disabled × focus
// ---------------------------------------------------------------------------

test("Checkbox: the three check states are distinct and correctly labelled", () => {
  const unchecked = arm(Checkbox, { checked: false });
  const checked = arm(Checkbox, { checked: true });
  const mixed = arm(Checkbox, { checked: "indeterminate" });
  expectDistinct([
    ["unchecked", unchecked],
    ["checked", checked],
    ["indeterminate", mixed],
  ]);
  expect(unchecked).toContain('aria-checked="false"');
  expect(checked).toContain('aria-checked="true"');
  expect(mixed).toContain('aria-checked="mixed"');
});

test("Checkbox: disabled reduces the control; focus arm is drawn", () => {
  const markup = arm(Checkbox, { checked: false, disabled: true });
  expect(markup).toContain("disabled");
  expect(markup).toContain("focus-visible:ring-focus");
});

test("Checkbox: change inverts through the aria state", () => {
  let next: boolean | string | undefined;
  const off = Checkbox({ checked: false, onChange: (c) => (next = c) });
  click(findOne(off, (el) => prop(el, "role") === "checkbox"));
  expect(next).toBe(true);
  const on = Checkbox({ checked: true, onChange: (c) => (next = c) });
  click(findOne(on, (el) => prop(el, "role") === "checkbox"));
  expect(next).toBe(false);
});

// ---------------------------------------------------------------------------
// Pagination — default · first-page · last-page · single-page
// ---------------------------------------------------------------------------

test("Pagination: default (mid-range) keeps both chevrons live", () => {
  const markup = arm(Pagination, { page: 2, pageCount: 5 });
  expect(markup).toContain("Page 2 of 5");
  // `disabled:` variant classes always appear; the *attribute* is what arms
  const disarmed = markup.match(/disabled=""/g)?.length ?? 0;
  expect(disarmed).toBe(0);
});

test("Pagination: first page ghosts prev, last page ghosts next", () => {
  const first = Pagination({ page: 1, pageCount: 5 });
  expect(prop(prevButton(first), "disabled")).toBe(true);
  expect(prop(nextButton(first), "disabled")).toBeFalsy();
  expect(arm(Pagination, { page: 1, pageCount: 5 })).toContain("opacity-50");
  const last = Pagination({ page: 5, pageCount: 5 });
  expect(prop(nextButton(last), "disabled")).toBe(true);
  expect(prop(prevButton(last), "disabled")).toBeFalsy();
});

test("Pagination: a single page ghosts both and reports one page", () => {
  const single = Pagination({ page: 1, pageCount: 1 });
  expect(prop(prevButton(single), "disabled")).toBe(true);
  expect(prop(nextButton(single), "disabled")).toBe(true);
  expect(arm(Pagination, { page: 1, pageCount: 1 })).toContain("Page 1 of 1");
});

test("Pagination: onChange steps within bounds", () => {
  let landed = -1;
  const tree = Pagination({
    page: 2,
    pageCount: 5,
    onChange: (p) => (landed = p),
  });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Previous page"));
  expect(landed).toBe(1);
  click(findOne(tree, (el) => prop(el, "aria-label") === "Next page"));
  expect(landed).toBe(3);
});

// ---------------------------------------------------------------------------
// Select — closed · open · disabled · error × with-value · placeholder
// ---------------------------------------------------------------------------

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
] as const;

test("Select: closed vs open", () => {
  const closed = arm(Select, { options: OPTIONS, value: "a" });
  const open = arm(Select, { options: OPTIONS, value: "a", open: true });
  expect(closed).toContain('aria-expanded="false"');
  expect(closed).not.toContain('role="listbox"');
  expect(open).toContain('aria-expanded="true"');
  expect(open).toContain('role="listbox"');
  expect(open).toContain('role="option"');
});

test("Select: open marks the chosen option", () => {
  const open = arm(Select, { options: OPTIONS, value: "b", open: true });
  expect(open).toContain('aria-selected="true"');
  expect(open).toContain("Beta");
});

test("Select: disabled disarms even when open", () => {
  const markup = arm(Select, {
    options: OPTIONS,
    value: "a",
    open: true,
    disabled: true,
  });
  expect(markup).toContain("disabled");
  expect(markup).not.toContain('role="listbox"');
});

test("Select: error is the invalid arm", () => {
  const error = arm(Select, { options: OPTIONS, error: true });
  expect(error).toContain('aria-invalid="true"');
  expect(error).toContain("border-state-broken");
});

test("Select: with-value shows the choice; placeholder shows the hint", () => {
  const withValue = arm(Select, { options: OPTIONS, value: "a" });
  expect(withValue).toContain("Alpha");
  const placeholder = arm(Select, {
    options: OPTIONS,
    placeholder: "Pick one",
  });
  expect(placeholder).toContain("Pick one");
  expect(placeholder).toContain("text-ink-subtle");
  expectDistinct([
    ["with-value", withValue],
    ["placeholder", placeholder],
  ]);
});

// ---------------------------------------------------------------------------
// Toggle — off · on · disabled × focus
// ---------------------------------------------------------------------------

test("Toggle: off and on are distinct arms", () => {
  const off = arm(Toggle, { checked: false });
  const on = arm(Toggle, { checked: true });
  expectDistinct([
    ["off", off],
    ["on", on],
  ]);
  expect(off).toContain('aria-checked="false"');
  expect(on).toContain('aria-checked="true"');
  expect(on).toContain("bg-brand");
});

test("Toggle: disabled reduces the switch; focus arm is drawn", () => {
  const markup = arm(Toggle, { checked: false, disabled: true });
  expect(markup).toContain("disabled");
  expect(markup).toContain("bg-disabled");
  expect(markup).toContain("focus-visible:ring-focus");
});

test("Toggle: change inverts", () => {
  let next: boolean | undefined;
  const tree = Toggle({ checked: false, onChange: (c) => (next = c) });
  click(findOne(tree, (el) => prop(el, "role") === "switch"));
  expect(next).toBe(true);
});

// ---------------------------------------------------------------------------
// Skeleton — row · card · chart · pane · text-line (one component)
// (The mandated row-height assertion lives in design-system.test.tsx.)
// ---------------------------------------------------------------------------

test("Skeleton: all five shapes render distinct geometry", () => {
  const shapes = (["row", "card", "chart", "pane", "text-line"] as const).map(
    (shape) => [shape, arm(Skeleton, { shape })] as const,
  );
  expectDistinct(shapes);
  expect(shapes[1]![1]).toContain("bg-skeleton-sheen"); // card has inner bars
  expect(shapes[2]![1]).toContain("bg-skeleton-sheen");
  expect(shapes[3]![1]).toContain("bg-skeleton-sheen");
});

test("Skeleton: card/chart/pane place children at absolute offsets", () => {
  for (const shape of ["card", "chart", "pane"] as const) {
    expect(arm(Skeleton, { shape })).toContain("absolute"); // size-tolerant (§1)
  }
});

// ---------------------------------------------------------------------------
// Spinner — sm · md × on-surface · on-brand
// ---------------------------------------------------------------------------

test("Spinner: sizes and contexts are distinct arms", () => {
  expectDistinct([
    ["sm/on-surface", arm(Spinner, { size: "sm" })],
    ["md/on-surface", arm(Spinner, {})],
    ["md/on-brand", arm(Spinner, { onBrand: true })],
  ]);
  expect(arm(Spinner, { onBrand: true })).toContain("text-brand-subtle");
  expect(arm(Spinner, {})).toContain("text-ink-subtle");
  expect(arm(Spinner, {})).toContain('role="status"');
});

// ---------------------------------------------------------------------------
// EmptyState — first-run · filtered · no-results
// ---------------------------------------------------------------------------

test("EmptyState: the three kinds render distinct icons and copy", () => {
  const kinds = (
    [
      ["first-run", "No domains yet"],
      ["filtered", "Nothing matches"],
      ["no-results", "No results"],
    ] as const
  ).map(([kind, title]) => [kind, arm(EmptyState, { kind, title })] as const);
  expectDistinct(kinds);
});

test("EmptyState: first-run's action is primary; filtered never offers create", () => {
  const firstRun = arm(EmptyState, {
    kind: "first-run",
    title: "t",
    actionLabel: "Add a domain",
  });
  expect(firstRun).toContain("bg-brand");
  const filtered = arm(EmptyState, {
    kind: "filtered",
    title: "t",
    actionLabel: "Clear filters",
  });
  expect(filtered).not.toContain("bg-brand"); // never the create action (§1)
});

// ---------------------------------------------------------------------------
// ErrorState — fetch · permission · timeout · partial, each with retry
// ---------------------------------------------------------------------------

test("ErrorState: four kinds, distinct icons and default titles", () => {
  const kinds = (["fetch", "permission", "timeout", "partial"] as const).map(
    (kind) => [kind, arm(ErrorState, { kind })] as const,
  );
  expectDistinct(kinds);
  expect(kinds[1]![1]).toContain("Permission denied");
});

test("ErrorState: carries a retry and never strands the user", () => {
  let retried = 0;
  const tree = ErrorState({ kind: "fetch", onRetry: () => (retried += 1) });
  click(findOne(tree, (el) => prop(el, "children") === "Retry"));
  expect(retried).toBe(1);
  expect(arm(ErrorState, { kind: "fetch" })).not.toContain("Retry");
});

// ---------------------------------------------------------------------------
// Toast — info · success · warning · danger × with-action · dismissible
// ---------------------------------------------------------------------------

test("Toast: four tones render distinct icons; danger interrupts", () => {
  const info = arm(Toast, { tone: "info", children: "msg" });
  const success = arm(Toast, { tone: "success", children: "msg" });
  const warning = arm(Toast, { tone: "warning", children: "msg" });
  const danger = arm(Toast, { tone: "danger", children: "msg" });
  expectDistinct([
    ["info", info],
    ["success", success],
    ["warning", warning],
    ["danger", danger],
  ]);
  expect(danger).toContain('role="alert"');
  expect(info).toContain('role="status"');
  expect(success).toContain("text-state-active");
});

test("Toast: the action renders and fires", () => {
  let acted = 0;
  const tree = Toast({
    tone: "info",
    action: { label: "View", onAction: () => (acted += 1) },
    children: "msg",
  });
  click(findOne(tree, (el) => prop(el, "children") === "View"));
  expect(acted).toBe(1);
});

test("Toast: dismissible shows the control only when asked, and it fires", () => {
  expect(arm(Toast, { tone: "info", children: "msg" })).not.toContain(
    'aria-label="Dismiss"',
  );
  let dismissed = 0;
  const tree = Toast({
    tone: "warning",
    dismissible: true,
    onDismiss: () => (dismissed += 1),
    children: "msg",
  });
  click(findOne(tree, (el) => prop(el, "aria-label") === "Dismiss"));
  expect(dismissed).toBe(1);
});

// ---------------------------------------------------------------------------
// Modal — confirm · confirm-danger · form · wide × default · submitting
// ---------------------------------------------------------------------------

test("Modal: the four kinds render distinct widths", () => {
  expectDistinct(
    (["confirm", "confirm-danger", "form", "wide"] as const).map(
      (kind) =>
        [
          kind,
          arm(Modal, {
            kind,
            title: "T",
            children: "body",
            confirmLabel: "OK",
            onConfirm: noop,
            onCancel: noop,
          }),
        ] as const,
    ),
  );
  expect(arm(Modal, { kind: "wide", title: "T", children: "b" })).toContain(
    "max-w-3xl",
  );
});

test("Modal: confirm-danger confirms with the danger button", () => {
  const markup = arm(Modal, {
    kind: "confirm-danger",
    title: "Delete domain?",
    children: "b",
    confirmLabel: "Delete",
    onConfirm: noop,
  });
  expect(markup).toContain("text-state-broken");
  expect(markup).not.toContain("bg-brand");
});

test("Modal: submitting holds the confirm label and blocks cancel", () => {
  const submitting = Modal({
    kind: "confirm",
    title: "T",
    children: "b",
    confirmLabel: "Approve",
    onConfirm: noop,
    onCancel: noop,
    submitting: true,
  });
  const confirm = findOne(submitting, (el) => prop(el, "loading") === true);
  expect(prop(confirm, "children")).toBe("Approve"); // label held, width frozen
  const cancel = findOne(submitting, (el) => prop(el, "children") === "Cancel");
  expect(prop(cancel, "disabled")).toBe(true);
});

test("Modal: confirm and cancel fire their callbacks", () => {
  let confirmed = 0;
  let cancelled = 0;
  const tree = Modal({
    kind: "confirm",
    title: "T",
    children: "b",
    confirmLabel: "OK",
    onConfirm: () => (confirmed += 1),
    onCancel: () => (cancelled += 1),
  });
  click(findOne(tree, (el) => prop(el, "children") === "OK"));
  expect(confirmed).toBe(1);
  click(findOne(tree, (el) => prop(el, "children") === "Cancel"));
  expect(cancelled).toBe(1);
});

test("Modal: a dialog with no actions renders no footer", () => {
  expect(arm(Modal, { kind: "form", title: "T", children: "b" })).not.toContain(
    "Cancel",
  );
});

// ---------------------------------------------------------------------------
// Tooltip — top · bottom · left · right
// ---------------------------------------------------------------------------

test("Tooltip: the four sides place the bubble on distinct edges", () => {
  const bySide = {
    top: "bottom-full",
    bottom: "top-full",
    left: "right-full",
    right: "left-full",
  } as const;
  for (const [side, edge] of Object.entries(bySide)) {
    const markup = arm(Tooltip, {
      label: "hint",
      side: side as keyof typeof bySide,
      children: <b>x</b>,
    });
    expect(markup, `${side} places the bubble at ${edge}`).toContain(edge);
    expect(markup).toContain('role="tooltip"');
  }
});

// ---------------------------------------------------------------------------
// LineChart — 1 series · 2 series × live · static · no-data
// ---------------------------------------------------------------------------

const ONE = [{ points: [1, 2, 1.5, 3] }] as const;
const TWO = [...ONE, { points: [3, 2, 2.5, 1] }] as const;

test("LineChart: one series draws viz-1; two draw viz-1 and viz-2", () => {
  const one = arm(LineChart, { series: ONE });
  expect(one).toContain("stroke-viz-1");
  expect(one).not.toContain("stroke-viz-2");
  const two = arm(LineChart, { series: TWO });
  expect(two).toContain("stroke-viz-1");
  expect(two).toContain("stroke-viz-2");
});

test("LineChart: live pulses the last point; static does not", () => {
  expect(arm(LineChart, { series: ONE, live: true })).toContain("animate-ping");
  expect(arm(LineChart, { series: ONE })).not.toContain("animate-ping");
});

test("LineChart: no-data draws the grid and the label, never fake axes", () => {
  const empty = arm(LineChart, { series: [{ points: [] }] });
  expect(empty).toContain("no data");
  expect(empty).not.toContain("<path");
  expect(empty).toContain("stroke-viz-grid"); // grid still holds the layout
});
