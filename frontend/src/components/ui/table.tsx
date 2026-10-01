import type { ReactNode } from "react";
import { EmptyState } from "./empty";
import { SkeletonTable } from "./skeleton";

export type Column<T> = {
  key: string;
  header: ReactNode;
  render: (row: T, index: number) => ReactNode;
  align?: "start" | "center" | "end";
  width?: string;
  className?: string;
};

const ALIGN = { start: "text-right", center: "text-center", end: "text-left" };

export function DataTable<T>({
  columns,
  rows,
  keyOf,
  loading = false,
  empty,
  onRowClick,
  rowClass,
  stickyHeader = true,
  dense = false,
  className = "",
}: {
  columns: Column<T>[];
  rows: T[];
  keyOf: (row: T, index: number) => string | number;
  loading?: boolean;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  rowClass?: (row: T) => string | undefined;
  stickyHeader?: boolean;
  dense?: boolean;
  className?: string;
}) {
  if (loading) return <SkeletonTable rows={4} cols={Math.min(columns.length, 5)} />;

  return (
    <div className={`overflow-x-auto rounded-2xl border border-line bg-surface shadow-soft ${className}`}>
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead className={stickyHeader ? "sticky top-0 z-10" : ""}>
          <tr className="bg-surface-sunken text-[11px] font-bold text-ink-muted">
            {columns.map((c) => (
              <th
                key={c.key}
                style={c.width ? { width: c.width } : undefined}
                className={`border-b border-line px-4 py-3 ${ALIGN[c.align ?? "start"]} ${c.className ?? ""}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={keyOf(row, i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={[
                "border-b border-line-soft transition last:border-0",
                i % 2 === 1 ? "bg-surface-sunken/70" : "bg-surface",
                onRowClick ? "cursor-pointer hover:bg-primary-50/60" : "hover:bg-primary-50/40",
                rowClass?.(row) ?? "",
              ].join(" ")}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-4 ${dense ? "py-2" : "py-3.5"} align-middle text-ink-muted ${ALIGN[c.align ?? "start"]} ${c.className ?? ""}`}
                >
                  {c.render(row, i)}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="p-0">
                {empty ?? <EmptyState compact title="موردی برای نمایش نیست" description="هنوز داده‌ای ثبت نشده است." />}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
