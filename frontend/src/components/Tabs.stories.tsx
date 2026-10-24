// Stories for <Tabs> — Figma: Tab 10:100, 🧩 Components. The item set carries
// the axes the matrix tests exercise: a count badge and a disabled tab
// (UI_STATES §3a; arms mirror tests/components-3a.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tabs } from "./Tabs";

const meta = {
  title: "Components/Tabs",
  component: Tabs,
} satisfies Meta<typeof Tabs>;

export default meta;
type Story = StoryObj<typeof meta>;

const ITEMS = [
  { id: "all", label: "All", count: 7 },
  { id: "failing", label: "Failing" },
  { id: "archived", label: "Archived", disabled: true },
] as const;

// No value = nothing selected (per-tab loading; UI_STATES §3a).
export const NothingSelected: Story = { args: { items: ITEMS } };

export const FirstSelected: Story = {
  args: { items: ITEMS, value: "all" },
};

export const SecondSelected: Story = {
  args: { items: ITEMS, value: "failing" },
};
