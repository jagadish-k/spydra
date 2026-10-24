// Figma: Bulk action bar 199:1294 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import { Button } from "./Button";

export interface BulkAction {
  id: string;
  label: string;
  danger?: boolean;
}

export interface BulkActionBarProps {
  /** 0 = the hidden state: the bar unmounts rather than empties. */
  count: number;
  actions: readonly BulkAction[];
  onAction?: (id: string) => void;
  onClear?: () => void;
}

export function BulkActionBar({
  count,
  actions,
  onAction,
  onClear,
}: BulkActionBarProps) {
  if (count === 0) return null;
  return (
    <div
      role="toolbar"
      aria-label="Bulk actions"
      className="flex items-center gap-3 rounded-md border border-line bg-selected px-4 py-2"
    >
      <span className="text-sm font-medium tabular-nums text-ink-brand">
        {count} selected
      </span>
      <div className="flex gap-2">
        {actions.map((action) => (
          <Button
            key={action.id}
            size="sm"
            variant={action.danger ? "danger" : "secondary"}
            onClick={() => onAction?.(action.id)}
          >
            {action.label}
          </Button>
        ))}
      </div>
      {onClear && (
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear}>
          Clear
        </Button>
      )}
    </div>
  );
}
