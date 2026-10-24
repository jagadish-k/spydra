// Stories for <StatePill> — Figma: State pill, 🧩 Components. All six
// lifecycle states, no seventh (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { StatePill } from "./StatePill";

const meta = {
  title: "Components/StatePill",
  component: StatePill,
} satisfies Meta<typeof StatePill>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Discovered: Story = { args: { state: "discovered" } };

export const Pending: Story = { args: { state: "pending" } };

export const Active: Story = { args: { state: "active" } };

export const Broken: Story = { args: { state: "broken" } };

export const Paused: Story = { args: { state: "paused" } };

export const Archived: Story = { args: { state: "archived" } };

// The why surfaces as the tooltip.
export const WithWhy: Story = {
  args: {
    state: "broken",
    why: "5 consecutive extractions came back empty",
  },
};
