// Stories for <Skeleton> — Figma: Skeleton 33:120, 🧩 Components. All five
// shapes (UI_STATES §3b; arms mirror tests/components-3b.test.tsx). Row is
// exactly --sp-row-comfortable; card/chart/pane place children at fractional
// offsets so resizing never overflows.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Skeleton } from "./Skeleton";

const meta = {
  title: "Components/Skeleton",
  component: Skeleton,
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Row: Story = {
  args: { shape: "row" },
  render: (args) => (
    <div className="w-72">
      <Skeleton {...args} />
    </div>
  ),
};

export const TextLine: Story = {
  args: { shape: "text-line" },
  render: (args) => (
    <div className="w-72">
      <Skeleton {...args} />
    </div>
  ),
};

export const Card: Story = {
  args: { shape: "card" },
  render: (args) => (
    <div className="w-72">
      <Skeleton {...args} />
    </div>
  ),
};

export const Chart: Story = {
  args: { shape: "chart" },
  render: (args) => (
    <div className="w-72">
      <Skeleton {...args} />
    </div>
  ),
};

export const Pane: Story = {
  args: { shape: "pane" },
  render: (args) => (
    <div className="w-72">
      <Skeleton {...args} />
    </div>
  ),
};
