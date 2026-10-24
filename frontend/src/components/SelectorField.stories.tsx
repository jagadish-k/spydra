// Stories for <SelectorField> — Figma: Selector field 11:142, 🧩 Components.
// The whole state axis is derived from `matches` (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx): null resolving, 0 no-match (muted, not an
// error), 1 default, >1 warning — plus invalid and disabled.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SelectorField } from "./SelectorField";

const meta = {
  title: "Components/SelectorField",
  component: SelectorField,
} satisfies Meta<typeof SelectorField>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Resolving: Story = {
  args: { selector: "h1.product-title", matches: null, label: "Title" },
};

export const NoMatch: Story = {
  args: { selector: "h1.product-title", matches: 0, label: "Title" },
};

export const Matched: Story = {
  args: { selector: "h1.product-title", matches: 1, label: "Title" },
};

export const MultiMatchWarning: Story = {
  args: { selector: "div.price", matches: 6, label: "Price" },
};

// Invalid is the red arm, distinct from no-match.
export const Invalid: Story = {
  args: { selector: "h1[", matches: 1, invalid: true, label: "Title" },
};

export const Disabled: Story = {
  args: {
    selector: "h1.product-title",
    matches: 1,
    disabled: true,
    label: "Title",
  },
};

export const WithResolvedSample: Story = {
  args: {
    selector: "h1.product-title",
    matches: 1,
    resolved: "£4.50",
    label: "Title",
  },
};
