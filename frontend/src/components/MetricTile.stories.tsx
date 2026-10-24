// Stories for <MetricTile> — Figma: Metric tile 11:71, 🧩 Components. One
// named story per persistent prop-axis value (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx). null is the unavailable tile — an em dash,
// not an error (the partial-counter contract).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { MetricTile } from "./MetricTile";

const meta = {
  title: "Components/MetricTile",
  component: MetricTile,
} satisfies Meta<typeof MetricTile>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { label: "Domains", value: 3 },
};

export const Attention: Story = {
  args: { label: "Broken pages", value: 12, tone: "attention" },
};

export const Danger: Story = {
  args: { label: "Blocked domains", value: 1, tone: "danger" },
};

// Loading swaps the value for a skeleton, label held.
export const Loading: Story = {
  args: { label: "Domains", value: 3, loading: true },
};

// The unavailable tile: one failed counter never blanks the strip.
export const Unavailable: Story = {
  args: { label: "Domains", value: null },
};
