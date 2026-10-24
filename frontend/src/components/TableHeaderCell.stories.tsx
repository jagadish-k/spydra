// Stories for <TableHeaderCell> — Figma: Table header cell, 🧩 Components.
// Sort=none/asc/desc on the sortable cell, plus the not-sortable arm
// (UI_STATES §3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { TableHeaderCell } from "./TableHeaderCell";

const meta = {
  title: "Components/TableHeaderCell",
  component: TableHeaderCell,
} satisfies Meta<typeof TableHeaderCell>;

export default meta;
type Story = StoryObj<typeof meta>;

const noop = (): void => undefined;

export const SortableUnsorted: Story = {
  args: { children: "Domain", sort: "none", onSort: noop },
};

export const SortAscending: Story = {
  args: { children: "Domain", sort: "asc", onSort: noop },
};

export const SortDescending: Story = {
  args: { children: "Domain", sort: "desc", onSort: noop },
};

// No onSort = not sortable: plain text, no button.
export const NotSortable: Story = {
  args: { children: "Domain" },
};
