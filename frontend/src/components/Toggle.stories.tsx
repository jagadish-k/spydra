// Stories for <Toggle> — Figma: Toggle 51:303, 🧩 Components. Off/on/disabled
// (UI_STATES §3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Toggle } from "./Toggle";

const meta = {
  title: "Components/Toggle",
  component: Toggle,
} satisfies Meta<typeof Toggle>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Off: Story = { args: { checked: false, label: "Politeness" } };

export const On: Story = { args: { checked: true, label: "Politeness" } };

export const Disabled: Story = {
  args: { checked: false, disabled: true, label: "Politeness" },
};
