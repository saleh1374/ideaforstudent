"use client";

import { fa, subjectFa } from "@/lib/labels";
import { Section, Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { DataTable, type Column } from "@/components/ui/table";
import { BarChart } from "@/components/ui/charts";
import { IconChart, IconCheck, IconLayers, IconMap, IconSparkles, IconTarget, IconUsers } from "@/components/ui/icons";
import { ProvinceRankingTable } from "./province-ranking";
import type { Insights } from "./types";

const PRIORITY_SKIN: Record<number, { dot: string; bar: string }> = {
  1: { dot: "bg-danger-600 text-white", bar: "bg-danger-500" },
  2: { dot: "bg-warning-500 text-white", bar: "bg-warning-500" },
  3: { dot: "bg-sky-500 text-white", bar: "bg-sky-500" },
};

type Topic = Insights["weakest_topics"][number];

const TOPIC_COLUMNS: Column<Topic>[] = [
  {
    key: "topic",
    header: "مبحث",
    render: (row) => (
      <div className="space-y-0.5">
        <span className="font-semibold text-ink">{row.title}</span>
        <span className="num block text-[11px] text-ink-faint">#{row.topic_id}</span>
      </div>
    ),
  },
  {
    key: "subject",
    header: "درس",
    align: "center",
    render: (row) => <Badge tone="neutral">{subjectFa(row.subject)}</Badge>,
  },
  {
    key: "mastery",
    header: "تسط",
    align: "center",
    render: (row) => <span className="num font-bold text-ink">{fa(row.avg_mastery)}٪</span>,
  },
  {
    key: "weak",
    header: "سهم ضعیف",
    align: "center",
    render: (row) => (
      <span className={`num font-semibold ${(row.weak_ratio ?? 0) >= 0.4 ? "text-danger-600" : "text-ink-muted"}`}>
        {row.weak_ratio !== null ? `${fa(row.weak_ratio * 100)}٪` : "—"}
      </span>
    ),
  },
];

/**
 * روایت تحلیلی نقاط ضعف (insights service) — همان چیدمان صفحهٔ /geo؛
 * بین /geo و پنل /province مشترک است.
 */
export function GeoInsightsPanel({ data, title = "روایت تحلیلی نقاط ضعف" }: { data: Insights; title?: string }) {
  return (
    <Section
      title={title}
      subtitle={`تولیدشده در ${new Date(data.generated_at).toLocaleString("fa-IR")} — تحلیل قاعده‌محور؛ هیچ عدد سرکوب‌شده‌ای وارد روایت نمی‌شود.`}
      action={
        <Badge tone="accent" dot>
          {data.scope === "national" ? "سطح ملی" : "سطح استان"}
        </Badge>
      }
    >
      {/* تیتر روایت */}
      <Card variant="brand" className="space-y-2">
        <p className="flex items-center gap-2 text-xs font-extrabold text-primary-700">
          <IconSparkles size={16} /> خلاصه تحلیل
        </p>
        <p className="text-base font-bold leading-8 text-primary-900 sm:text-lg">{data.headline_fa}</p>
      </Card>

      {/* شاخص‌ها */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="ضعیف‌ترین درس"
          value={data.weakest_subjects[0] ? subjectFa(data.weakest_subjects[0].subject) : "—"}
          tone="danger"
          icon={<IconLayers size={20} />}
          hint={data.weakest_subjects[0] ? `${fa(data.weakest_subjects[0].avg_mastery)}٪ میانگین تسط` : "داده‌ای زیر حد نصاب نیست"}
        />
        <StatCard
          label="سهم ضعیف‌ترین درس"
          value={data.weakest_subjects[0] ? `${fa(data.weakest_subjects[0].weak_ratio * 100)}٪` : "—"}
          tone="warning"
          icon={<IconTarget size={20} />}
          hint="دانش‌آموزان زیر آستانه تثبیت"
        />
        <StatCard
          label="دانش‌آموز دارای داده"
          value={fa(data.weakest_subjects[0]?.students_count ?? 0)}
          tone="primary"
          icon={<IconUsers size={20} />}
          hint="در درس ضعیف‌ترین"
        />
        <StatCard
          label={data.scope === "national" ? "استان‌های زیر حد نصاب" : "نقاط قوت"}
          value={fa(data.scope === "national" ? data.suppressed_provinces.length : data.strengths_fa.length)}
          tone="accent"
          icon={data.scope === "national" ? <IconMap size={20} /> : <IconCheck size={20} />}
          hint={data.scope === "national" ? "بدون عدد گزارش می‌شوند" : "مباحث بالای آستانه تسط"}
        />
      </section>

      <section className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="ضعیف‌ترین درس‌ها" subtitle="میانگین تسط وزنی هر درس بر اساس دانش‌آموزان دارای داده" icon={<IconChart size={17} />} />
          {data.weakest_subjects.length > 0 ? (
            <BarChart
              id="insights-subjects"
              height={230}
              format={(v) => `${fa(v)}٪`}
              data={data.weakest_subjects.map((s) => ({
                label: subjectFa(s.subject),
                value: Math.round(s.avg_mastery),
                color: s.avg_mastery < 50 ? "#f43f5e" : s.avg_mastery < 65 ? "#f59e0b" : "#6366f1",
              }))}
            />
          ) : (
            <EmptyState compact title="داده‌ای زیر حد نصاب نیست" description="برای این محدوده درس قابل نمایشی ثبت نشده است." />
          )}
        </Card>
        <Card>
          <CardHeader title="نقاط قوت" subtitle="مباحث بالای آستانه تسط" icon={<IconCheck size={17} />} />
          <ul className="space-y-2.5 text-xs leading-6">
            {data.strengths_fa.map((s, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-success-50 text-success-600">
                  <IconCheck size={11} />
                </span>
                <span className="text-ink-muted">{s}</span>
              </li>
            ))}
          </ul>
        </Card>
      </section>

      {/* مباحث ضعیف */}
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-bold text-ink">ضعیف‌ترین مباحث</h3>
          <p className="mt-0.5 text-xs text-ink-muted">فقط مباحث بالای حداقل جمعیت — پایه برنامه ترمیمی.</p>
        </div>
        <DataTable
          columns={TOPIC_COLUMNS}
          rows={data.weakest_topics}
          keyOf={(r) => r.topic_id}
          empty={<EmptyState compact title="موردی قابل نمایش نیست" />}
        />
      </div>

      {/* رتب‌بندی استان‌ها — فقط سطح ملی */}
      {data.scope === "national" && data.province_ranking.length > 0 && <ProvinceRankingTable data={data} />}

      {/* پیشنهادها */}
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-bold text-ink">پیشنهادهای اولویت‌دار</h3>
          <p className="mt-0.5 text-xs text-ink-muted">اولویت ۱ فوری، ۲ هفتگی، ۳ برنامه‌ریزی‌شده.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.recommendations.map((rec, i) => {
            const skin = PRIORITY_SKIN[rec.priority] ?? PRIORITY_SKIN[3];
            return (
              <Card key={i} className="relative space-y-2 overflow-hidden pt-6">
                <span className={`absolute inset-x-0 top-0 h-1 ${skin.bar}`} aria-hidden="true" />
                <div className="flex items-start gap-2.5">
                  <span className={`num grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-black ${skin.dot}`}>
                    {fa(rec.priority)}
                  </span>
                  <p className="text-sm font-bold text-ink">{rec.title_fa}</p>
                </div>
                <p className="text-xs leading-6 text-ink-muted">{rec.detail_fa}</p>
              </Card>
            );
          })}
        </div>
      </div>
    </Section>
  );
}
