"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { STATUS_FA, STATUS_ORDER, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { ProgressBar } from "@/components/ui/progress";
import { DonutChart, RadialProgress } from "@/components/ui/charts";
import { SkeletonCard, SkeletonStats } from "@/components/ui/skeleton";
import { IconAlert, IconFamily, IconTarget, IconTrend } from "@/components/ui/icons";
import { ExamResultsSection } from "./exam-results-section";
import { PlanSection } from "./plan-section";
import { AlertsSection } from "./alerts-section";
import { WeeklyReportSection } from "./weekly-report-section";
import { LinksSection } from "./links-section";

type Child = { id: number; full_name: string; grade: string | null; class_id: number | null };

const SECTION_KEYS = ["overview", "exams", "plan", "alerts", "weekly", "links"] as const;
type SectionKey = (typeof SECTION_KEYS)[number];

type Overview = {
  student_id: number;
  progress_pct: number;
  mastery_pct: number;
  gap: number;
  gap_message: string | null;
  errors_total: number;
  errors_open: number;
  status_counts: Record<string, number>;
  weak_topics: { topic_id: number; title: string; status: string }[];
  note_fa: string;
};

const STATUS_SEG_COLOR: Record<string, string> = {
  mastered: "#10b981",
  consolidating: "#0ea5e9",
  weak: "#f59e0b",
  critical: "#f43f5e",
  unknown: "#cbd5e1",
};

export default function ParentPage() {
  const [children, setChildren] = useState<Child[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [section, setSection] = useState<SectionKey>("overview");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadChildren = useCallback(async () => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    try {
      const d = await api<{ children: Child[] }>("/parent/children");
      setChildren(d.children);
      if (d.children.length > 0 && selected === null) setSelected(d.children[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    loadChildren();
  }, [loadChildren]);

  useEffect(() => {
    if (selected === null) return;
    setOv(null);
    api<Overview>(`/parent/children/${selected}/overview`)
      .then(setOv)
      .catch((e) => setError(e.message));
  }, [selected]);

  const current = children.find((c) => c.id === selected);

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="پنل والدین"
          description="وضعیت یادگیری فرزندتان را بدون نمره‌محوری ببینید: پیشرفت برنامه، تسط واقعی و مباحث نیازمند توجه."
          crumbs={[{ label: "دانشیار" }, { label: "عمومی" }, { label: "پنل والدین" }]}
          badge={current ? <Badge tone="primary" dot>{current.full_name}</Badge> : undefined}
        />

        {error && <Alert variant="danger" title="خطا">{error}</Alert>}

        {/* child switcher */}
        {loading && children.length === 0 && !error && <SkeletonStats count={3} />}

        {!loading && children.length === 0 && !error && (
          <EmptyState
            icon={<IconFamily size={26} />}
            title="فرزندی به حساب شما متصل نیست"
            description="برای اتصال فرزند، با مدیر مدرسه هماهنگ کنید تا حساب شما لینک شود."
          />
        )}

        {children.length > 0 && (
          <Tabs
            items={children.map((c) => ({ key: String(c.id), label: c.full_name }))}
            value={String(selected ?? "")}
            onChange={(k) => setSelected(Number(k))}
          />
        )}

        {/* report sections — سند پنل والدین §3/§6/§8/§13/§14 */}
        {selected !== null && (
          <Tabs
            items={[
              { key: "overview", label: "نمای کلی" },
              { key: "exams", label: "نمرات آزمون‌ها" },
              { key: "plan", label: "برنامه و تکالیف" },
              { key: "alerts", label: "هشدارها" },
              { key: "weekly", label: "گزارش هفتگی" },
              { key: "links", label: "فرزندان و دسترسی‌ها" },
            ]}
            value={section}
            onChange={(k) => setSection(k as SectionKey)}
          />
        )}

        {selected !== null && section === "exams" && <ExamResultsSection childId={selected} />}
        {selected !== null && section === "plan" && <PlanSection childId={selected} />}
        {selected !== null && section === "alerts" && <AlertsSection childId={selected} />}
        {selected !== null && section === "weekly" && <WeeklyReportSection childId={selected} />}
        {selected !== null && section === "links" && <LinksSection childId={selected} />}

        {section === "overview" && !ov && selected !== null && (
          <div className="space-y-5">
            <SkeletonStats count={3} />
            <div className="grid gap-5 lg:grid-cols-2">
              <SkeletonCard />
              <SkeletonCard />
            </div>
          </div>
        )}

        {section === "overview" && ov && (
          <>
            {/* KPIs */}
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <StatCard
                label="پیشرفت در برنامه"
                value={`${fa(ov.progress_pct, 1)}٪`}
                tone="primary"
                icon={<IconTrend size={20} />}
                hint="از کل برنامه سال"
              />
              <StatCard
                label="تسط واقعی"
                value={`${fa(ov.mastery_pct, 1)}٪`}
                tone="success"
                icon={<IconTarget size={20} />}
                hint="یادگیری تثبیت‌شده"
              />
              <StatCard
                label="خطاهای باز"
                value={
                  <span>
                    {fa(ov.errors_open)} <span className="text-base font-bold text-ink-faint">از {fa(ov.errors_total)}</span>
                  </span>
                }
                tone={ov.errors_open > 0 ? "danger" : "success"}
                icon={<IconAlert size={20} />}
                hint={ov.errors_open > 0 ? "نیازمند مرور و ترمیم" : "همه رفع شده"}
              />
            </section>

            {(ov.gap_message || Math.abs(ov.gap) >= 15) && (
              <Alert variant="warning" title="نکته مهم">
                {Math.abs(ov.gap) >= 15 && <>شکاف {fa(Math.abs(ov.gap), 1)} واحدی بین پیشرفت و تسط — </>}
                {ov.gap_message}
              </Alert>
            )}

            <section className="grid gap-5 lg:grid-cols-3">
              <Card>
                <CardHeader title="وضعیت مباحث" subtitle="توزیع مباحث بر اساس تسط" icon={<IconTarget size={17} />} />
                <DonutChart
                  data={STATUS_ORDER.map((s) => ({
                    label: STATUS_FA[s],
                    value: ov.status_counts[s] ?? 0,
                    color: STATUS_SEG_COLOR[s],
                  }))}
                  size={140}
                  thickness={20}
                  legend={false}
                  centerSubtitle="مبحث"
                />
                <ul className="mt-4 space-y-2">
                  {STATUS_ORDER.map((s) => (
                    <li key={s} className="flex items-center justify-between text-xs">
                      <Badge tone={statusTone(s)}>{STATUS_FA[s]}</Badge>
                      <span className="num font-bold text-ink">{fa(ov.status_counts[s] ?? 0)} مبحث</span>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card>
                <CardHeader title="مباحث نیازمند توجه" subtitle="اولویت مرور در خانه" icon={<IconAlert size={17} />} />
                {ov.weak_topics.length === 0 ? (
                  <EmptyState compact icon={<IconTarget size={24} />} title="مبحث ضعیفی دیده نمی‌شود" description="وضعیت یادگیری پایدار است." />
                ) : (
                  <ul className="space-y-2">
                    {ov.weak_topics.map((t) => (
                      <li key={t.topic_id} className="flex items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                        <span className="truncate text-xs font-semibold text-ink">{t.title}</span>
                        <Badge tone={statusTone(t.status)}>{STATUS_FA[t.status] ?? t.status}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card>
                <CardHeader title="جمع‌بندی وضعیت" icon={<IconTrend size={17} />} />
                <div className="grid place-items-center py-2">
                  <RadialProgress
                    value={ov.mastery_pct}
                    label="تسط واقعی"
                    color="#039855"
                    format={(v) => `${fa(v, 1)}٪`}
                  />
                </div>
                <div className="mt-3 space-y-2">
                  <ProgressBar value={ov.progress_pct} label="پیشرفت برنامه" showValue />
                  <ProgressBar
                    value={
                      ov.errors_total > 0 ? ((ov.errors_total - ov.errors_open) / ov.errors_total) * 100 : 100
                    }
                    tone={ov.errors_open === 0 ? "success" : "warning"}
                    label="رفع خطاها"
                    showValue
                  />
                </div>
              </Card>
            </section>

            {ov.note_fa && <Alert variant="info" title="جمع‌بندی سامانه">{ov.note_fa}</Alert>}
          </>
        )}
      </div>
    </AppShell>
  );
}
