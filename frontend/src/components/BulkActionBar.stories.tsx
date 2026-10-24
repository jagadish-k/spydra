// Stories for <BulkActionBar> — Figma: Bulk action bar 199:1294, 🧩
// Components. Count 0 is the hidden state: the bar unmounts, so that story
// renders nothing by design (UI_STATES §3b; arms mirror
// tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { BulkActionBar } from "./BulkActionBar";

const meta = {
  title: "Components/BulkActionBar",
  component: BulkActionBar,
} satisfies Meta<typeof BulkActionBar>;

export default meta;
type Story = StoryObj<typeof meta>;

const noop = (): void => undefined;

const ACTIONS = [
  { id: "pause", label: "Pause" },
  { id: "delete", label: "Delete", danger: true },
] as const;

export const Visible: Story = {
  args: { count: 3, actions: ACTIONS, onAction: noop, onClear: noop },
  render: (args) => (
    <div className="w-96">
      <BulkActionBar {...args} />
    </div>
  ),
};

// 0 selected = the bar is gone (blank canvas is the correct capture).
export const Hidden: Story = {
  args: { count: 0, actions: ACTIONS, onClear: noop },
};
