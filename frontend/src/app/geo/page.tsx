"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa, subjectFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/ui/table";
import { BarChart } from "@/components/ui/charts";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconChart, IconCheck, IconLayers, IconMap, IconRefresh, IconSchool, IconSparkles, IconTarget, IconUsers } from "@/components/ui/icons";

type Overview = {
  scope: string;
  province_id: number | null;
  schools_count: number;
  students_count: number;
  avg_mastery: number | null;
  suppressed: boolean;
  min_group: number;
  worst_topics: { topic_id: number; subject: string | null; students_count: number; avg_mastery: number | null; weak_ratio: number | null }[];
  note_fa: string;
};

type TopicRow = {
  topic_id: number;
  subject: string | null;
  students_count: number;
  avg_mastery: number | null;
  avg_retention: number | null;
  weak_ratio: number | null;
  suppressed: boolean;
};

type Tab = "province" | "national";

/** روایت تحلیلی نقاط ضعف (insights service) — برای استان و سطح ملی. */
type Insights = {
  scope: string;
  province_id: number | null;
  generated_at: string;
  headline_fa: string;
  weakest_subjects: { subject: string; avg_mastery: number; weak_ratio: number; students_count: number }[];
  weakest_topics: { topic_id: number; title: string; subject: string | null; avg_mastery: number; weak_ratio: number | null }[];
  province_ranking: { province_id: number; name: string; avg_mastery: number | null; students_count: number; suppressed: boolean }[];
  suppressed_provinces: { province_id: number; name: string; note_fa: string }[];
  strengths_fa: string[];
  recommendations: { priority: number; title_fa: string; detail_fa: string }[];
};

const PRIORITY_SKIN: Record<number, { dot: string; bar: string }> = {
  1: { dot: "bg-danger-600 text-white", bar: "bg-danger-500" },
  2: { dot: "bg-warning-500 text-white", bar: "bg-warning-500" },
  3: { dot: "bg-sky-500 text-white", bar: "bg-sky-500" },
};

export default function GeoPage() {
  const [tab, setTab] = useState<Tab>("province");
  const [ov, setOv] = useState<Overview | null>(null);
  const [rows, setRows] = useState<TopicRow[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (t: Tab) => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setOv(null);
    setInsights(null);
    setLoading(true);
    setError("");
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);
      const base = t === "province" ? "/geo/province/1" : "/geo/national";
      const [o, s] = await Promise.all([
        api<Overview>(`${base}/overview`),
        api<{ rows: TopicRow[] }>(`${base}/topics`),
      ]);
      setOv(o);
      setRows(s.rows);

      // روایت تحلیلی — فقط نقش‌های دارای حوزه؛ 403 بی‌صدا نادیده گرفته می‌شود
      if (me.role === "ministry") {
        try {
          setInsights(await api<Insights>("/geo/national/insights"));
        } catch {
          setInsights(null);
        }
      } else if (me.role === "province_admin") {
        try {
          setInsights(await api<Insights>(`/geo/province/${o.province_id ?? 1}/insights`));
        } catch {
          setInsights(null);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  async function refresh() {
    setRefreshing(true);
    try {
      const res = await api<{ national: { written: number; suppressed: number } }>("/geo/national/refresh", { method: "POST" });
      await load(tab);
      toast(`بازمحاسبه شد: ${fa(res.national.written)} مبحث (${fa(res.national.suppressed)} سرکوب‌شده)`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در بازمحاسبه", "error");
    } finally {
      setRefreshing(false);
    }
  }

  const title = tab === "province" ? "مدیر کل استان" : "وزارت / سطح ملی";

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

  const chartData = (ov?.worst_topics ?? [])
    .filter((t) => t.avg_mastery !== null)
    .slice(0, 7)
    .map((t) => ({
      label: t.subject ? `${subjectFa(t.subject)} #${t.topic_id}` : `#${t.topic_id}`,
      value: Math.round(t.avg_mastery as number),
      color: (t.avg_mastery as number) < 50 ? "#f43f5e" : "#f59e0b",
    }));

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title={title}
          description="تجمیع‌های province / national_topic_stats — عددها تابع حداقل جمعیت ۱۰ هستند."
          crumbs={[{ label: "دانشیار" }, { label: "مدیریت" }, { label: title }]}
          badge={role ? <Badge tone="accent" dot>{role === "ministry" ? "وزارت" : "مدیر کل استان"}</Badge> : undefined}
          actions={
            (role === "ministry" || role === "province_admin") && (
              <Button variant="soft" size="sm" loading={refreshing} icon={<IconRefresh size={15} />} onClick={refresh}>
                بازمحاسبه تجمیع‌ها
              </Button>
            )
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت داده">{error}</Alert>}

        <Tabs
          items={[
            { key: "province", label: "دید استان" },
            { key: "national", label: "دید کشور" },
          ]}
          value={tab}
          onChange={(k) => setTab(k as Tab)}
        />

        {loading && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <SkeletonTable rows={6} cols={6} />
          </div>
        )}

        {ov && !loading && (
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
                  <BarChart data={chartData} height={230} id="geo-worst" format={(v) => `${fa(v)}٪`} />
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
                    <span className="font-bold text-ink">{tab === "province" ? "استانی" : "ملی"}</span>
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

            <Section title="مباحث با کمترین تسط (تجمیع ملی/استانی)">
              <DataTable columns={columns} rows={rows} keyOf={(r) => r.topic_id} empty={<EmptyState compact title="موردی ثبت نشده" />} />
            </Section>
          </>
        )}

        {/* ---------------- روایت تحلیلی نقاط ضعف (نقش‌های استان/وزارت) ---------------- */}
        {insights && !loading && (
          <Section
            title="روایت تحلیلی نقاط ضعف"
            subtitle={`تولیدشده در ${new Date(insights.generated_at).toLocaleString("fa-IR")} — تحلیل قاعده‌محور؛ هیچ عدد سرکوب‌شده‌ای وارد روایت نمی‌شود.`}
            action={
              <Badge tone="accent" dot>
                {insights.scope === "national" ? "سطح ملی" : "سطح استان"}
              </Badge>
            }
          >
            {/* تیتر روایت */}
            <Card variant="brand" className="space-y-2">
              <p className="flex items-center gap-2 text-xs font-extrabold text-primary-700">
                <IconSparkles size={16} /> خلاصه تحلیل
              </p>
              <p className="text-base font-bold leading-8 text-primary-900 sm:text-lg">{insights.headline_fa}</p>
            </Card>

            {/* شاخص‌ها */}
            <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard
                label="ضعیف‌ترین درس"
                value={insights.weakest_subjects[0] ? subjectFa(insights.weakest_subjects[0].subject) : "—"}
                tone="danger"
                icon={<IconLayers size={20} />}
                hint={insights.weakest_subjects[0] ? `${fa(insights.weakest_subjects[0].avg_mastery)}٪ میانگین تسط` : "داده‌ای زیر حد نصاب نیست"}
              />
              <StatCard
                label="سهم ضعیف‌ترین درس"
                value={insights.weakest_subjects[0] ? `${fa(insights.weakest_subjects[0].weak_ratio * 100)}٪` : "—"}
                tone="warning"
                icon={<IconTarget size={20} />}
                hint="دانش‌آموزان زیر آستانه تثبیت"
              />
              <StatCard
                label="دانش‌آموز دارای داده"
                value={fa(insights.weakest_subjects[0]?.students_count ?? 0)}
                tone="primary"
                icon={<IconUsers size={20} />}
                hint="در درس ضعیف‌ترین"
              />
              <StatCard
                label={insights.scope === "national" ? "استان‌های زیر حد نصاب" : "نقاط قوت"}
                value={fa(insights.scope === "national" ? insights.suppressed_provinces.length : insights.strengths_fa.length)}
                tone="accent"
                icon={insights.scope === "national" ? <IconMap size={20} /> : <IconCheck size={20} />}
                hint={insights.scope === "national" ? "بدون عدد گزارش می‌شوند" : "مباحث بالای آستانه تسط"}
              />
            </section>

            <section className="grid gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader title="ضعیف‌ترین درس‌ها" subtitle="میانگین تسط وزنی هر درس بر اساس دانش‌آموزان دارای داده" icon={<IconChart size={17} />} />
                {insights.weakest_subjects.length > 0 ? (
                  <BarChart
                    id="insights-subjects"
                    height={230}
                    format={(v) => `${fa(v)}٪`}
                    data={insights.weakest_subjects.map((s) => ({
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
                  {insights.strengths_fa.map((s, i) => (
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
                columns={[
                  {
                    key: "topic",
                    header: "مبحث",
                    render: (row: Insights["weakest_topics"][number]) => (
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
                    render: (row: Insights["weakest_topics"][number]) => <Badge tone="neutral">{subjectFa(row.subject)}</Badge>,
                  },
                  {
                    key: "mastery",
                    header: "تسط",
                    align: "center",
                    render: (row: Insights["weakest_topics"][number]) => (
                      <span className="num font-bold text-ink">{fa(row.avg_mastery)}٪</span>
                    ),
                  },
                  {
                    key: "weak",
                    header: "سهم ضعیف",
                    align: "center",
                    render: (row: Insights["weakest_topics"][number]) => (
                      <span className={`num font-semibold ${(row.weak_ratio ?? 0) >= 0.4 ? "text-danger-600" : "text-ink-muted"}`}>
                        {row.weak_ratio !== null ? `${fa(row.weak_ratio * 100)}٪` : "—"}
                      </span>
                    ),
                  },
                ]}
                rows={insights.weakest_topics}
                keyOf={(r) => r.topic_id}
                empty={<EmptyState compact title="موردی قابل نمایش نیست" />}
              />
            </div>

            {/* رتب‌بندی استان‌ها — فقط سطح ملی */}
            {insights.scope === "national" && insights.province_ranking.length > 0 && (
              <div className="space-y-3">
                <div>
                  <h3 className="text-sm font-bold text-ink">رتب‌بندی استان‌ها</h3>
                  <p className="mt-0.5 text-xs text-ink-muted">بهترین استان اول؛ استان‌های زیر حداقل جمعیت بدون عدد و کم‌رنگ نمایش داده می‌شوند.</p>
                </div>
                <DataTable
                  columns={[
                    {
                      key: "rank",
                      header: "رتبه",
                      align: "center",
                      width: "72px",
                      render: (row: Insights["province_ranking"][number]) => (
                        <span className="num font-bold text-ink">{row.suppressed ? "—" : fa(rankingRank(insights, row.province_id))}</span>
                      ),
                    },
                    {
                      key: "name",
                      header: "استان",
                      render: (row: Insights["province_ranking"][number]) => <span className="font-semibold text-ink">{row.name}</span>,
                    },
                    {
                      key: "mastery",
                      header: "میانگین تسط",
                      align: "center",
                      render: (row: Insights["province_ranking"][number]) =>
                        row.suppressed ? (
                          <span className="text-[11px] text-ink-faint">
                            {insights.suppressed_provinces.find((p) => p.province_id === row.province_id)?.note_fa ?? "داده‌کافی ندارد"}
                          </span>
                        ) : (
                          <span className="num font-bold text-ink">{row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}</span>
                        ),
                    },
                    {
                      key: "students",
                      header: "دانش‌آموز دارای داده",
                      align: "center",
                      render: (row: Insights["province_ranking"][number]) => (
                        <span className="num">{row.suppressed ? "—" : fa(row.students_count)}</span>
                      ),
                    },
                    {
                      key: "state",
                      header: "وضعیت داده",
                      align: "center",
                      render: (row: Insights["province_ranking"][number]) => (
                        <Badge tone={row.suppressed ? "danger" : "success"} dot>
                          {row.suppressed ? "زیر حد نصاب" : "قابل نمایش"}
                        </Badge>
                      ),
                    },
                  ]}
                  rows={insights.province_ranking}
                  keyOf={(r) => r.province_id}
                  rowClass={(r) => (r.suppressed ? "opacity-60" : undefined)}
                  empty={<EmptyState compact title="استانی ثبت نشده" />}
                />
              </div>
            )}

            {/* پیشنهادها */}
            <div className="space-y-3">
              <div>
                <h3 className="text-sm font-bold text-ink">پیشنهادهای اولویت‌دار</h3>
                <p className="mt-0.5 text-xs text-ink-muted">اولویت ۱ فوری، ۲ هفتگی، ۳ برنامه‌ریزی‌شده.</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {insights.recommendations.map((rec, i) => {
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
        )}
      </div>
    </AppShell>
  );
}

/** رتبه استان در فهرست (استان‌های سرکوب‌شده رتبه نمی‌گیرند). */
function rankingRank(data: Insights, provinceId: number): number {
  const visible = data.province_ranking.filter((p) => !p.suppressed);
  const idx = visible.findIndex((p) => p.province_id === provinceId);
  return idx >= 0 ? idx + 1 : 0;
}
