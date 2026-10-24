// Stories for <Checkbox> — Figma: Checkbox, 🧩 Components. The three check
// states plus disabled (UI_STATES §3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Checkbox } from "./Checkbox";

const meta = {
  title: "Components/Checkbox",
  component: Checkbox,
} satisfies Meta<typeof Checkbox>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Unchecked: Story = {
  args: { checked: false, label: "Follow redirects" },
};

export const Checked: Story = {
  args: { checked: true, label: "Follow redirects" },
};

export const Indeterminate: Story = {
  args: { checked: "indeterminate", label: "Follow redirects" },
};

export const Disabled: Story = {
  args: { checked: false, disabled: true, label: "Follow redirects" },
};
