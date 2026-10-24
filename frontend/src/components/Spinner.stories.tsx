// Stories for <Spinner> — Figma: Spinner, 🧩 Components. Sizes plus the
// on-brand arm, shown on a filled brand surface so the ink is legible
// (UI_STATES §3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Spinner } from "./Spinner";

const meta = {
  title: "Components/Spinner",
  component: Spinner,
} satisfies Meta<typeof Spinner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Small: Story = { args: { size: "sm" } };

export const Medium: Story = { args: { size: "md" } };

// onBrand = the theme-constant ink for filled brand surfaces.
export const OnBrand: Story = {
  args: { size: "md", onBrand: true },
  render: (args) => (
    <div className="inline-flex rounded-md bg-brand p-3">
      <Spinner {...args} />
    </div>
  ),
};
