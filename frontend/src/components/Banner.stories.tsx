// Stories for <Banner> — Figma: Banner 11:84, 🧩 Components. One named story
// per persistent prop-axis value (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Banner } from "./Banner";

const meta = {
  title: "Components/Banner",
  component: Banner,
} satisfies Meta<typeof Banner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Info: Story = {
  args: { tone: "info", children: "Template v4 is now the active version." },
};

export const Warning: Story = {
  args: {
    tone: "warning",
    children: "This template has not matched anything for 7 days.",
  },
};

export const Danger: Story = {
  args: {
    tone: "danger",
    children: "The domain returned 403 and has been paused.",
  },
};

export const WithAction: Story = {
  args: {
    tone: "info",
    action: { label: "Undo", onAction: () => undefined },
    children: "Template v4 is now the active version.",
  },
};

export const Dismissible: Story = {
  args: {
    tone: "info",
    dismissible: true,
    onDismiss: () => undefined,
    children: "Template v4 is now the active version.",
  },
};
