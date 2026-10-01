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
import { IconChart, IconLayers, IconMap, IconRefresh, IconSchool, IconUsers } from "@/components/ui/icons";

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

export default function GeoPage() {
  const [tab, setTab] = useState<Tab>("province");
  const [ov, setOv] = useState<Overview | null>(null);
  const [rows, setRows] = useState<TopicRow[]>([]);
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
      </div>
    </AppShell>
  );
}
