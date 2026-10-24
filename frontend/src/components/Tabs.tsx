// Figma: Tab 10:100 — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  disabled?: boolean;
}

export interface TabsProps {
  items: readonly TabItem[];
  /** The selected tab id; absent = nothing selected (per-tab loading). */
  value?: string;
  onChange?: (id: string) => void;
}

// Within-screen navigation only, never route navigation (spec 006 §2).
export function Tabs({ items, value, onChange }: TabsProps) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {items.map((item) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-disabled={item.disabled || undefined}
            disabled={item.disabled}
            onClick={() => onChange?.(item.id)}
            className={`-mb-px cursor-pointer border-b-2 px-3 pt-[7px] pb-[7px] text-md transition-colors duration-[var(--sp-duration-fast)] focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
              selected
                ? "border-brand font-medium text-ink-brand"
                : item.disabled
                  ? "cursor-not-allowed border-transparent text-ink-subtle"
                  : "border-transparent text-ink-muted hover:text-ink"
            }`}
          >
            {item.label}
            {item.count != null && (
              <span
                className={`ml-1.5 rounded-full px-1.5 text-2xs tabular-nums ${
                  selected
                    ? "bg-brand-subtle text-ink-brand"
                    : "bg-subtle text-ink-muted"
                }`}
              >
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
