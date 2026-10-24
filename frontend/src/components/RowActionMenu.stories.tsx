// Stories for <RowActionMenu> — Figma: Row action menu 199:1306, 🧩
// Components. Open/closed, with the per-item danger and disabled arms in the
// open menu (UI_STATES §3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { RowActionMenu } from "./RowActionMenu";

const meta = {
  title: "Components/RowActionMenu",
  component: RowActionMenu,
} satisfies Meta<typeof RowActionMenu>;

export default meta;
type Story = StoryObj<typeof meta>;

const ACTIONS = [
  { id: "view", label: "View" },
  { id: "pause", label: "Pause" },
  { id: "delete", label: "Delete", danger: true },
  { id: "gone", label: "Unavailable", disabled: true },
] as const;

export const Closed: Story = {
  args: { actions: ACTIONS, open: false },
};

export const Open: Story = {
  args: { actions: ACTIONS, open: true },
  render: (args) => (
    <div className="flex justify-end p-6">
      <RowActionMenu {...args} />
    </div>
  ),
};
