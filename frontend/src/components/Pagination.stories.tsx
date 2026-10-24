// Stories for <Pagination> — Figma: Pagination 196:1332, 🧩 Components.
// First/last/single-page are derived from page × pageCount (UI_STATES §3b;
// arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Pagination } from "./Pagination";

const meta = {
  title: "Components/Pagination",
  component: Pagination,
} satisfies Meta<typeof Pagination>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Middle: Story = { args: { page: 2, pageCount: 5 } };

export const FirstPage: Story = { args: { page: 1, pageCount: 5 } };

export const LastPage: Story = { args: { page: 5, pageCount: 5 } };

export const SinglePage: Story = { args: { page: 1, pageCount: 1 } };
