// Figma: Row action menu 199:1306 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface RowAction {
  id: string;
  label: string;
  danger?: boolean;
  disabled?: boolean;
}

export interface RowActionMenuProps {
  actions: readonly RowAction[];
  open: boolean;
  onToggle?: () => void;
  onSelect?: (id: string) => void;
}

// Presentational: the screen owns open/closed and outside-click dismissal.
// Item hover is a hover: utility, the item-danger arm is a per-item flag.
export function RowActionMenu({
  actions,
  open,
  onToggle,
  onSelect,
}: RowActionMenuProps) {
  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={onToggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Row actions"
        className="flex h-6 w-6 items-center justify-center rounded-md text-ink-muted hover:bg-hover hover:text-ink focus-visible:ring-2 focus-visible:ring-focus"
      >
        <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
          <circle cx="3.5" cy="8" r="1.4" fill="currentColor" />
          <circle cx="8" cy="8" r="1.4" fill="currentColor" />
          <circle cx="12.5" cy="8" r="1.4" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute top-full right-0 z-10 mt-1 min-w-40 overflow-hidden rounded-md border border-line bg-surface py-1 shadow-md"
        >
          {actions.map((action) => (
            <button
              key={action.id}
              type="button"
              role="menuitem"
              disabled={action.disabled}
              onClick={() => onSelect?.(action.id)}
              className={`block w-full cursor-pointer px-3 py-1.5 text-left text-sm focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus disabled:cursor-not-allowed ${
                action.danger
                  ? "text-state-broken hover:bg-state-broken-tint"
                  : "text-ink hover:bg-hover"
              } disabled:text-ink-subtle disabled:hover:bg-transparent`}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
