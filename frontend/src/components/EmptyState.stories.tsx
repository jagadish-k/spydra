// Stories for <EmptyState> — Figma: Empty state, 🧩 Components. Three kinds;
// first-run's action is primary, filtered never offers to create (UI_STATES
// §1/§3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { EmptyState } from "./EmptyState";

const meta = {
  title: "Components/EmptyState",
  component: EmptyState,
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FirstRun: Story = {
  args: {
    kind: "first-run",
    title: "No domains yet",
    body: "Add a supplier domain to propose extraction rules for it.",
    actionLabel: "Add a domain",
  },
};

export const Filtered: Story = {
  args: {
    kind: "filtered",
    title: "Nothing matches",
    body: "The data exists — the filter is hiding it.",
    actionLabel: "Clear filters",
  },
};

export const NoResults: Story = {
  args: {
    kind: "no-results",
    title: "No results",
    body: "Try a different search.",
  },
};
