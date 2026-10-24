// Stories for <Sparkline> — Figma: Sparkline 10:93, 🧩 Components. Four
// trends plus the empty-values pending line (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Sparkline } from "./Sparkline";

const meta = {
  title: "Components/Sparkline",
  component: Sparkline,
} satisfies Meta<typeof Sparkline>;

export default meta;
type Story = StoryObj<typeof meta>;

const VALUES = [1, 2, 1.5, 3, 2.5];

export const Healthy: Story = { args: { values: VALUES, trend: "healthy" } };

export const Slipping: Story = { args: { values: VALUES, trend: "slipping" } };

export const Failing: Story = { args: { values: VALUES, trend: "failing" } };

export const Pending: Story = { args: { values: VALUES, trend: "pending" } };

// Empty values draw the flat pending line — no slope segments.
export const PendingNoData: Story = {
  args: { values: [], trend: "pending" },
};
