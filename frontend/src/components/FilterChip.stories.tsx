// Stories for <FilterChip> — Figma: Filter chip 199:1316, 🧩 Components. One
// named story per persistent prop-axis value (UI_STATES §3b; arms mirror
// tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { FilterChip } from "./FilterChip";

const meta = {
  title: "Components/FilterChip",
  component: FilterChip,
} satisfies Meta<typeof FilterChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { children: "broken" } };

export const Active: Story = { args: { active: true, children: "broken" } };

export const Removable: Story = {
  args: { removable: true, children: "broken" },
};
