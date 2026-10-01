"use client";

import { fa } from "@/lib/labels";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { DataTable, type Column } from "@/components/ui/table";
import type { Insights } from "./types";

type RankRow = Insights["province_ranking"][number];

/** رتبهٔ استان در فهرست (استان‌های سرکوب‌شده رتبه نمی‌گیرند). */
function rankingRank(data: Insights, provinceId: number): number {
  const visible = data.province_ranking.filter((p) => !p.suppressed);
  const idx = visible.findIndex((p) => p.province_id === provinceId);
  return idx >= 0 ? idx + 1 : 0;
}

/**
 * جدول «رتبه‌بندی استان‌ها» — بین صفحهٔ /geo و پنل /province مشترک.
 * ردیف استانِ خودی برجسته می‌شود؛ ردیف‌های زیر حد نصاب کم‌رنگ و بدون عدد می‌مانند.
 */
export function ProvinceRankingTable({
  data,
  highlightProvinceId = null,
  title = "رتب‌بندی استان‌ها",
  description = "بهترین استان اول؛ استان‌های زیر حداقل جمعیت بدون عدد و کم‌رنگ نمایش داده می‌شوند.",
}: {
  data: Insights;
  highlightProvinceId?: number | null;
  /** عنوان/توضیح اختیاری؛ null برای حذف سربرگ (مثلاً وقتی در Section کنار گذاشته شده) */
  title?: string | null;
  description?: string | null;
}) {
  const columns: Column<RankRow>[] = [
    {
      key: "rank",
      header: "رتبه",
      align: "center",
      width: "72px",
      render: (row) => <span className="num font-bold text-ink">{row.suppressed ? "—" : fa(rankingRank(data, row.province_id))}</span>,
    },
    {
      key: "name",
      header: "استان",
      render: (row) => (
        <span className="flex items-center gap-2">
          <span className="font-semibold text-ink">{row.name}</span>
          {highlightProvinceId !== null && row.province_id === highlightProvinceId && (
            <Badge tone="primary" dot>
              استان شما
            </Badge>
          )}
        </span>
      ),
    },
    {
      key: "mastery",
      header: "میانگین تسط",
      align: "center",
      render: (row) =>
        row.suppressed ? (
          <span className="text-[11px] text-ink-faint">
            {data.suppressed_provinces.find((p) => p.province_id === row.province_id)?.note_fa ?? "داده‌کافی ندارد"}
          </span>
        ) : (
          <span className="num font-bold text-ink">{row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}</span>
        ),
    },
    {
      key: "students",
      header: "دانش‌آموز دارای داده",
      align: "center",
      render: (row) => <span className="num">{row.suppressed ? "—" : fa(row.students_count)}</span>,
    },
    {
      key: "state",
      header: "وضعیت داده",
      align: "center",
      render: (row) => (
        <Badge tone={row.suppressed ? "danger" : "success"} dot>
          {row.suppressed ? "زیر حد نصاب" : "قابل نمایش"}
        </Badge>
      ),
    },
  ];

  const table = (
    <DataTable
      columns={columns}
      rows={data.province_ranking}
      keyOf={(r) => r.province_id}
      rowClass={(r) => {
        const classes: string[] = [];
        if (r.suppressed) classes.push("opacity-60");
        if (highlightProvinceId !== null && r.province_id === highlightProvinceId) {
          classes.push("bg-primary-50/70 ring-2 ring-inset ring-primary-200");
        }
        return classes.length > 0 ? classes.join(" ") : undefined;
      }}
      empty={<EmptyState compact title="استانی ثبت نشده" />}
    />
  );

  if (title === null) return table;

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-bold text-ink">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-ink-muted">{description}</p>}
      </div>
      {table}
    </div>
  );
}
