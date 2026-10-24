// Stories for <Toast> — Figma: Toast 34:201, 🧩 Components. Four tones plus
// the action and dismissible arms (UI_STATES §3b; arms mirror
// tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Toast } from "./Toast";

const meta = {
  title: "Components/Toast",
  component: Toast,
} satisfies Meta<typeof Toast>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Info: Story = {
  args: { tone: "info", children: "Template saved as v4." },
};

export const Success: Story = {
  args: { tone: "success", children: "Domain approved and scheduled." },
};

export const Warning: Story = {
  args: { tone: "warning", children: "Selector matched 6 nodes." },
};

// danger interrupts (role="alert"); the rest are polite status.
export const Danger: Story = {
  args: { tone: "danger", children: "Run halted: daily URL cap reached." },
};

export const WithAction: Story = {
  args: {
    tone: "info",
    action: { label: "View", onAction: () => undefined },
    children: "Template saved as v4.",
  },
};

export const Dismissible: Story = {
  args: {
    tone: "warning",
    dismissible: true,
    onDismiss: () => undefined,
    children: "Selector matched 6 nodes.",
  },
};
