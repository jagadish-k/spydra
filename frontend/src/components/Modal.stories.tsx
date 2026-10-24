// Stories for <Modal> — Figma: Modal 201:1381, 🧩 Components. Four kinds plus
// the submitting arm the matrix tests exercise on confirm (UI_STATES §3b;
// arms mirror tests/components-3b.test.tsx). The scrim is included.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Modal } from "./Modal";

const meta = {
  title: "Components/Modal",
  component: Modal,
} satisfies Meta<typeof Modal>;

export default meta;
type Story = StoryObj<typeof meta>;

const noop = (): void => undefined;

export const Confirm: Story = {
  args: {
    kind: "confirm",
    title: "Pause this domain?",
    children: "No new URLs will be claimed until you resume it.",
    confirmLabel: "Pause",
    onConfirm: noop,
    onCancel: noop,
  },
};

export const ConfirmDanger: Story = {
  args: {
    kind: "confirm-danger",
    title: "Delete domain?",
    children: "Observations are append-only and will remain queryable.",
    confirmLabel: "Delete",
    onConfirm: noop,
    onCancel: noop,
  },
};

// A form dialog with no actions renders no footer.
export const Form: Story = {
  args: {
    kind: "form",
    title: "Edit extraction field",
    children: "The screen supplies its own form body and actions.",
  },
};

export const Wide: Story = {
  args: {
    kind: "wide",
    title: "Compare template versions",
    children: "Side-by-side diff of v3 and v4.",
    confirmLabel: "Accept v4",
    onConfirm: noop,
    onCancel: noop,
  },
};

// Submitting: the confirm button goes loading, label held, cancel blocked.
export const Submitting: Story = {
  args: {
    kind: "confirm",
    title: "Pause this domain?",
    children: "No new URLs will be claimed until you resume it.",
    confirmLabel: "Pause",
    onConfirm: noop,
    onCancel: noop,
    submitting: true,
  },
};
