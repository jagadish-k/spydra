// Stories for <ProgressBar> — Figma: Progress bar 43:270, 🧩 Components. One
// named story per persistent prop-axis value (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx). Never a percentage — the legend counts
// segments.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ProgressBar } from "./ProgressBar";

const meta = {
  title: "Components/ProgressBar",
  component: ProgressBar,
} satisfies Meta<typeof ProgressBar>;

export default meta;
type Story = StoryObj<typeof meta>;

// The stacked bar: all four run states in one track, with the legend.
export const Stacked: Story = {
  args: {
    segments: { queued: 10, inFlight: 5, done: 4, failed: 1 },
    legend: true,
  },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};

export const RunningDeterminate: Story = {
  args: { state: "running", fraction: 0.5 },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};

// No fraction = indeterminate: a fixed-width pulse, nothing slides.
export const RunningIndeterminate: Story = {
  args: { state: "running" },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};

export const Paused: Story = {
  args: { state: "paused" },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};

export const Complete: Story = {
  args: { state: "complete" },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};

export const Failed: Story = {
  args: { state: "failed" },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};

export const Empty: Story = {
  args: { state: "empty" },
  render: (args) => (
    <div className="w-72">
      <ProgressBar {...args} />
    </div>
  ),
};
