// Stories for <ValidationBadge> — Figma: Validation badge, 🧩 Components.
// Three verdicts plus the count and rule arms (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ValidationBadge } from "./ValidationBadge";

const meta = {
  title: "Components/ValidationBadge",
  component: ValidationBadge,
} satisfies Meta<typeof ValidationBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Pass: Story = { args: { kind: "pass" } };

export const Partial: Story = { args: { kind: "partial" } };

export const Fail: Story = { args: { kind: "fail" } };

export const FailWithCount: Story = { args: { kind: "fail", count: 2 } };

// The failing rule's name surfaces as the tooltip.
export const FailWithRule: Story = {
  args: { kind: "fail", rule: "required" },
};
