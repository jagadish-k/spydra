// Figma: Modal 201:1381 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";
import { Button } from "./Button";

export type ModalKind = "confirm" | "confirm-danger" | "form" | "wide";

// Widths per Kind; everything else about a kind is its buttons.
const KIND_WIDTHS: Record<ModalKind, string> = {
  confirm: "max-w-sm",
  "confirm-danger": "max-w-sm",
  form: "max-w-lg",
  wide: "max-w-3xl",
};

export interface ModalProps {
  kind: ModalKind;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  onConfirm?: () => void;
  cancelLabel?: string;
  onCancel?: () => void;
  /** State=Submitting: the confirm button goes loading, label held. */
  submitting?: boolean;
}

// The scrim is the mapped --sp-scrim token (a translucent-ink alias over the
// backdrop, human decision 2026-10-25) — Figma's Modal frame still draws the
// card only; the screens dim their own surface per that frame.
export function Modal({
  kind,
  title,
  children,
  confirmLabel,
  onConfirm,
  cancelLabel = "Cancel",
  onCancel,
  submitting = false,
}: ModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${KIND_WIDTHS[kind]} overflow-hidden rounded-xl border border-line bg-surface shadow-lg`}
      >
        <div className="border-b border-line px-5 py-4 text-lg font-semibold text-ink">
          {title}
        </div>
        <div className="px-5 py-4 text-md text-ink-muted">{children}</div>
        {(confirmLabel != null || onCancel != null) && (
          <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
            {onCancel != null && (
              <Button
                variant="secondary"
                onClick={onCancel}
                disabled={submitting}
              >
                {cancelLabel}
              </Button>
            )}
            {confirmLabel != null && onConfirm != null && (
              <Button
                variant={kind === "confirm-danger" ? "danger" : "primary"}
                onClick={onConfirm}
                loading={submitting}
              >
                {confirmLabel}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
