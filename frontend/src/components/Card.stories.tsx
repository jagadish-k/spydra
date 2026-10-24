// Stories for <Card> — Figma: Card, 🧩 Components. One named story per
// persistent prop-axis value (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Card } from "./Card";

const meta = {
  title: "Components/Card",
  component: Card,
} satisfies Meta<typeof Card>;

export default meta;
type Story = StoryObj<typeof meta>;

const content = (
  <div className="p-4">
    <div className="mb-1 font-medium">acme-supply.example</div>
    <div className="text-sm">Last crawled 4 minutes ago · 1,204 pages</div>
  </div>
);

export const Default: Story = {
  render: () => (
    <div className="w-72">
      <Card>{content}</Card>
    </div>
  ),
};

export const Interactive: Story = {
  render: () => (
    <div className="w-72">
      <Card interactive>{content}</Card>
    </div>
  ),
};

export const Selected: Story = {
  render: () => (
    <div className="w-72">
      <Card selected>{content}</Card>
    </div>
  ),
};

// Loading swaps the content for a skeleton that holds the layout.
export const Loading: Story = {
  render: () => (
    <div className="w-72">
      <Card loading>{content}</Card>
    </div>
  ),
};
