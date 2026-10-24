// Figma: Table header cell — 🧩 Components 3:138, file GeJPFXY4CicHBdzLMyXG2E
import type { ReactNode } from "react";

export type SortDirection = "none" | "asc" | "desc";

export interface TableHeaderCellProps {
  children: ReactNode;
  /** Current sort; "none" only means unsorted when the cell is sortable. */
  sort?: SortDirection;
  /** Present = sortable. The control is a button in <th> (spec 006 §6). */
  onSort?: () => void;
  className?: string;
}

export function TableHeaderCell({
  children,
  sort = "none",
  onSort,
  className = "",
}: TableHeaderCellProps) {
  const ariaSort =
    sort === "asc" ? "ascending" : sort === "desc" ? "descending" : undefined;
  return (
    <th
      aria-sort={ariaSort}
      scope="col"
      className={`h-[30px] border-b border-line bg-subtle px-3 text-left text-xs font-medium whitespace-nowrap text-ink-muted ${className}`}
    >
      {onSort ? (
        <button
          type="button"
          onClick={onSort}
          className={`inline-flex items-center gap-[3px] hover:text-ink focus-visible:ring-2 focus-visible:ring-focus ${
            sort !== "none" ? "text-ink" : ""
          }`}
        >
          {children}
          {sort !== "none" && (
            <span aria-hidden="true" className="opacity-55">
              {sort === "asc" ? "▲" : "▼"}
            </span>
          )}
        </button>
      ) : (
        children
      )}
    </th>
  );
}
