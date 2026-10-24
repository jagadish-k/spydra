// Stories for <Input> — Figma: Input 42:156, 🧩 Components. One named story
// per persistent prop-axis value (UI_STATES §3a; arms mirror
// tests/components-3a.test.tsx). Every valued arm carries a no-op onChange,
// like the tests, so the controlled field renders clean.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Input } from "./Input";

const meta = {
  title: "Components/Input",
  component: Input,
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

const noop = (): void => undefined;

export const Default: Story = {
  args: { value: "denim jacket", onChange: noop },
};

export const Error: Story = {
  args: { value: "denim jacket", onChange: noop, error: true },
};

export const Disabled: Story = {
  args: { value: "denim jacket", onChange: noop, disabled: true },
};

export const ReadOnly: Story = {
  args: { value: "denim jacket", onChange: noop, readOnly: true },
};

export const WithPrefix: Story = {
  args: { value: "example.com", onChange: noop, prefix: "https://" },
};

// The clear affordance appears only when a value exists.
export const WithClear: Story = {
  args: { value: "denim jacket", onChange: noop, onClear: noop },
};
