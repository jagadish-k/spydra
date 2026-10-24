// Stories for <SearchField> — Figma: Search field 199:1339, 🧩 Components.
// Empty/typing are derived from value; no-results is the prop arm (UI_STATES
// §3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SearchField } from "./SearchField";

const meta = {
  title: "Components/SearchField",
  component: SearchField,
} satisfies Meta<typeof SearchField>;

export default meta;
type Story = StoryObj<typeof meta>;

const noop = (): void => undefined;

export const Empty: Story = {
  args: { value: "", onChange: noop },
  render: (args) => (
    <div className="w-72">
      <SearchField {...args} />
    </div>
  ),
};

export const Typing: Story = {
  args: { value: "denim", onChange: noop },
  render: (args) => (
    <div className="w-72">
      <SearchField {...args} />
    </div>
  ),
};

// A query that ran and found nothing.
export const NoResults: Story = {
  args: { value: "denim", onChange: noop, noResults: true },
  render: (args) => (
    <div className="w-72">
      <SearchField {...args} />
    </div>
  ),
};
