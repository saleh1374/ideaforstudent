"use client";

import { fa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { DataTable, type Column } from "@/components/ui/table";
import { BarChart } from "@/components/ui/charts";
import { IconChart, IconLayers, IconMap, IconSchool, IconUsers } from "@/components/ui/icons";
import type { Overview, TopicRow } from "./types";

/**
 * بلوک «دید استان/کشور»: کارت‌های آماری + نمودار ضعیف‌ترین مباحث + جدول مباحث
 * — بین صفحهٔ /geo و پنل /province مشترک است.
 */
export function GeoOverviewPanel({
  ov,
  rows,
  scopeLabel,
  chartId,
  topicsTitle = "مباحث با کمترین تسط (تجمیع ملی/استانی)",
}: {
  ov: Overview;
  rows: TopicRow[];
  /** «استانی» یا «ملی» — فقط برای نمایش دامنهٔ داده */
  scopeLabel: string;
  /** شناسه یکتای SVG نمودار در هر صفحه */
  chartId: string;
  topicsTitle?: string;
}) {
  const columns: Column<TopicRow>[] = [
    { key: "topic", header: "مبحث", render: (row) => <span className="num font-semibold text-ink">#{row.topic_id}</span> },
    { key: "subject", header: "درس", align: "center", render: (row) => <Badge tone="neutral">{row.subject ?? "—"}</Badge> },
    { key: "students", header: "دانش‌آموز", align: "center", render: (row) => <span className="num">{fa(row.students_count)}</span> },
    {
      key: "mastery",
      header: "تسط",
      align: "center",
      render: (row) =>
        row.suppressed ? (
          <span className="text-[11px] text-ink-faint">زیر حد نصاب</span>
        ) : (
          <span className="num font-bold text-ink">{row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}</span>
        ),
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num">{row.suppressed || row.avg_retention === null ? "—" : `${fa(row.avg_retention * 100)}٪`}</span>,
    },
    {
      key: "weak",
      header: "سهم ضعیف",
      align: "center",
      render: (row) => (
        <span className={`num font-semibold ${!row.suppressed && (row.weak_ratio ?? 0) >= 0.4 ? "text-danger-600" : "text-ink-muted"}`}>
          {row.suppressed || row.weak_ratio === null ? "—" : `${fa(row.weak_ratio * 100)}٪`}
        </span>
      ),
    },
  ];

  const chartData = (ov.worst_topics ?? [])
    .filter((t) => t.avg_mastery !== null)
    .slice(0, 7)
    .map((t) => ({
      label: t.subject ? `${subjectFa(t.subject)} #${t.topic_id}` : `#${t.topic_id}`,
      value: Math.round(t.avg_mastery as number),
      color: (t.avg_mastery as number) < 50 ? "#f43f5e" : "#f59e0b",
    }));

  return (
    <>
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="مدارس" value={fa(ov.schools_count)} tone="primary" icon={<IconSchool size={20} />} />
        <StatCard label="دانش‌آموزان دارای داده" value={fa(ov.students_count)} tone="accent" icon={<IconUsers size={20} />} />
        <StatCard
          label="میانگین تسط"
          value={ov.suppressed ? "زیر حد نصاب" : ov.avg_mastery !== null ? `${fa(ov.avg_mastery)}٪` : "—"}
          tone="success"
          icon={<IconChart size={20} />}
          hint={ov.suppressed ? `کمتر از ${fa(ov.min_group)} نفر` : "همه مباحث"}
        />
        <StatCard label="مباحث نیازمند برنامه" value={fa(ov.worst_topics.length)} tone="danger" icon={<IconLayers size={20} />} hint="ضعیف‌ترین‌ها" />
      </section>

      <Alert variant="info">{ov.note_fa}</Alert>

      <section className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="ضعیف‌ترین مباحث (تجمیع)"
            subtitle="بر اساس میانگین تسط — پایه برنامه استانی/ملی"
            icon={<IconChart size={17} />}
          />
          {chartData.length > 0 ? (
            <BarChart data={chartData} height={230} id={chartId} format={(v) => `${fa(v)}٪`} />
          ) : (
            <EmptyState compact title="داده‌ای زیر حد نصاب نیست" description="برای این محدوده، مبحثی قابل نمایش نیست." />
          )}
        </Card>
        <Card>
          <CardHeader title="دامنه داده" icon={<IconMap size={17} />} />
          <ul className="space-y-3 text-xs">
            <li className="flex items-center justify-between rounded-xl bg-surface-sunken px-3.5 py-3">
              <span className="text-ink-muted">حداقل جمعیت</span>
              <span className="num font-bold text-ink">{fa(ov.min_group)} نفر</span>
            </li>
            <li className="flex items-center justify-between rounded-xl bg-surface-sunken px-3.5 py-3">
              <span className="text-ink-muted">محدوده</span>
              <span className="font-bold text-ink">{scopeLabel}</span>
            </li>
            <li className="flex items-center justify-between rounded-xl bg-surface-sunken px-3.5 py-3">
              <span className="text-ink-muted">تعداد ردیف‌های قابل نمایش</span>
              <span className="num font-bold text-ink">{fa(rows.filter((r) => !r.suppressed).length)}</span>
            </li>
          </ul>
          <p className="mt-3 text-[11px] leading-6 text-ink-faint">
            اعداد زیر حد نصاب نمایش داده نمی‌شوند — نه تخمین، نه رنگ (حریم خصوصی).
          </p>
        </Card>
      </section>

      <Section title={topicsTitle}>
        <DataTable columns={columns} rows={rows} keyOf={(r) => r.topic_id} empty={<EmptyState compact title="موردی ثبت نشده" />} />
      </Section>
    </>
  );
}
