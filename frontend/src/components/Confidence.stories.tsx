// Stories for <Confidence> — Figma: Confidence, 🧩 Components. Four levels;
// the number of lit bars carries the signal as well as the colour (UI_STATES
// §3a; arms mirror tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Confidence } from "./Confidence";

const meta = {
  title: "Components/Confidence",
  component: Confidence,
} satisfies Meta<typeof Confidence>;

export default meta;
type Story = StoryObj<typeof meta>;

export const High: Story = { args: { level: "high" } };

export const Good: Story = { args: { level: "good" } };

export const Medium: Story = { args: { level: "medium" } };

export const Low: Story = { args: { level: "low" } };
