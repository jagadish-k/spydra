// Stories for <Select> — Figma: Select 51:293, 🧩 Components. Closed/open,
// disabled, error, placeholder (UI_STATES §3b; arms mirror
// tests/components-3b.test.tsx). The screen owns open state.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Select } from "./Select";

const meta = {
  title: "Components/Select",
  component: Select,
} satisfies Meta<typeof Select>;

export default meta;
type Story = StoryObj<typeof meta>;

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
] as const;

export const ClosedWithValue: Story = {
  args: { options: OPTIONS, value: "a" },
};

export const OpenWithSelection: Story = {
  args: { options: OPTIONS, value: "b", open: true },
};

// Disabled disarms even when open — no listbox.
export const Disabled: Story = {
  args: { options: OPTIONS, value: "a", open: true, disabled: true },
};

export const Error: Story = {
  args: { options: OPTIONS, value: "a", error: true },
};

export const Placeholder: Story = {
  args: { options: OPTIONS, placeholder: "Pick one" },
};
