// Stories for <Button> — Figma: Button, 🧩 Components. One named story per
// persistent prop-axis value (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx) so Chromatic captures each variant (ADR-0043).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "./Button";

const meta = {
  title: "Components/Button",
  component: Button,
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Primary: Story = { args: { variant: "primary", children: "Go" } };

export const Secondary: Story = {
  args: { variant: "secondary", children: "Go" },
};

export const Ghost: Story = { args: { variant: "ghost", children: "Go" } };

export const Danger: Story = { args: { variant: "danger", children: "Go" } };

export const Small: Story = {
  args: { variant: "primary", size: "sm", children: "Go" },
};

export const Medium: Story = {
  args: { variant: "primary", size: "md", children: "Go" },
};

// loading holds the label and joins a spinner — the width never moves.
export const Loading: Story = {
  args: { variant: "primary", loading: true, children: "Approve" },
};

export const Disabled: Story = {
  args: { variant: "primary", disabled: true, children: "Go" },
};
