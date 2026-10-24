// Stories for <Tooltip> — Figma: Tooltip 201:1406, 🧩 Components. The four
// sides (UI_STATES §3b; arms mirror tests/components-3b.test.tsx). The bubble
// is opacity-0 until hover/focus-within by design — a static capture shows
// the trigger; the side classes are visible in the Code Panel.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "./Button";
import { Tooltip } from "./Tooltip";

const meta = {
  title: "Components/Tooltip",
  component: Tooltip,
} satisfies Meta<typeof Tooltip>;

export default meta;
type Story = StoryObj<typeof meta>;

const trigger = <Button variant="ghost">Hover me</Button>;

export const Top: Story = {
  args: { label: "Runs in the last 24 hours", side: "top", children: trigger },
};

export const Bottom: Story = {
  args: {
    label: "Runs in the last 24 hours",
    side: "bottom",
    children: trigger,
  },
};

export const Left: Story = {
  args: { label: "Runs in the last 24 hours", side: "left", children: trigger },
};

export const Right: Story = {
  args: {
    label: "Runs in the last 24 hours",
    side: "right",
    children: trigger,
  },
};
