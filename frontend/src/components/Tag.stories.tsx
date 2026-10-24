// Stories for <Tag> — Figma: Tag 43:146, 🧩 Components. One named story per
// persistent prop-axis value plus the removable×disabled combination the
// matrix tests exercise (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tag } from "./Tag";

const meta = {
  title: "Components/Tag",
  component: Tag,
} satisfies Meta<typeof Tag>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Neutral: Story = { args: { tone: "neutral", children: "draft" } };

export const Info: Story = { args: { tone: "info", children: "proposed" } };

export const Success: Story = { args: { tone: "success", children: "live" } };

export const Warning: Story = { args: { tone: "warning", children: "stale" } };

export const Danger: Story = { args: { tone: "danger", children: "blocked" } };

export const Removable: Story = {
  args: { tone: "info", removable: true, children: "filter" },
};

// Disabled disables the remove control too.
export const RemovableDisabled: Story = {
  args: { tone: "info", removable: true, disabled: true, children: "filter" },
};
