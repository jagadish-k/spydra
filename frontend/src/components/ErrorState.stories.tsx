// Stories for <ErrorState> — Figma: Error state, 🧩 Components. Four kinds
// plus the with-retry arm; an error state never strands the user (UI_STATES
// §1/§3b; arms mirror tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ErrorState } from "./ErrorState";

const meta = {
  title: "Components/ErrorState",
  component: ErrorState,
} satisfies Meta<typeof ErrorState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Fetch: Story = { args: { kind: "fetch" } };

export const Permission: Story = { args: { kind: "permission" } };

export const Timeout: Story = { args: { kind: "timeout" } };

export const Partial: Story = { args: { kind: "partial" } };

export const WithRetry: Story = {
  args: {
    kind: "fetch",
    reason: "The supplier site closed the connection.",
    onRetry: () => undefined,
  },
};
