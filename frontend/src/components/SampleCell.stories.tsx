// Stories for <SampleCell> — Figma: Sample cell 10:83, 🧩 Components. Four
// results; pending is a neutral dash, not an error (UI_STATES §3a; arms
// mirror tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SampleCell } from "./SampleCell";

const meta = {
  title: "Components/SampleCell",
  component: SampleCell,
} satisfies Meta<typeof SampleCell>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Pass: Story = { args: { result: "pass" } };

export const Fail: Story = { args: { result: "fail" } };

export const Partial: Story = { args: { result: "partial" } };

export const Pending: Story = { args: { result: "pending" } };
