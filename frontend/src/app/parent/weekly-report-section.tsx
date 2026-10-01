"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { STATUS_FA, STATUS_ORDER, fa, subjectFa } from "@/lib/labels";
import { Section, Card, CardHeader } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { ProgressBar } from "@/components/ui/progress";
import { StatCard } from "@/components/ui/stat";
import { SkeletonStats } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconCheckCircle, IconClock, IconExam, IconRefresh, IconTarget, IconTasks, IconTrend } from "@/components/ui/icons";

/** گزارش هفتگی — GET /parent/children/{id}/weekly-report (سند §14) */
type WeekAlert = {
  code: string;
  severity: "info" | "warning" | "danger";
  title: string;
  message: string;
  action: string;
  topic_id: number | null;
};

type WeeklyReport = {
  student_id: number;
  week_start: string;
  week_end: string;
  generated_at: string;
  cached: boolean;
  plan: { progress_pct: number; total: number; done: number; week_total: number; week_done: number; week_done_pct: number; overdue: number };
  mastery: {
    mastery_pct: number;
    avg_retention: number | null;
    status_counts: Record<string, number>;
    weak_topics: { topic_id: number; title: string | null; effective_mastery: number; retention: number }[];
  };
  exams: { count: number; avg_percent: number | null; list: { attempt_id: number; title: string; subject: string | null; percent: number | null; delta: number | null; submitted_at: string | null }[] };
  activity: { evidence_count: number; questions_answered: number; minutes_spent: number; tasks_done: number };
  errors: { total: number; open: number; repeated_open: number; by_cause: { cause: string; cause_fa: string; count: number }[] };
  alerts: WeekAlert[];
  actions: string[];
  note_fa: string;
};

const SEV_TONE: Record<WeekAlert["severity"], Tone> = { info: "info", warning: "warning", danger: "danger" };
const SEV_FA: Record<WeekAlert["severity"], string> = { info: "اطلاع", warning: "توجه", danger: "فوری" };

const STATUS_COLOR: Record<string, string> = {
  mastered: "#10b981",
  consolidating: "#0ea5e9",
  weak: "#f59e0b",
  critical: "#f43f5e",
  unknown: "#cbd5e1",
};

function fmtDate(v: string): string {
  try {
    return new Date(v).toLocaleDateString("fa-IR", { dateStyle: "medium" });
  } catch {
    return v;
  }
}

function fmtDateTime(v: string | null): string {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return v;
  }
}

export function WeeklyReportSection({ childId }: { childId: number }) {
  const [data, setData] = useState<WeeklyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(
    async (refresh = false) => {
      setLoading(true);
      setError("");
      try {
        setData(await api<WeeklyReport>(`/parent/children/${childId}/weekly-report${refresh ? "?refresh=true" : ""}`));
        if (refresh) toast("گزارش هفتگی تازه‌سازی شد", "success");
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) toast(e.detail ?? "این فرزند به شما متصل نیست", "error");
        else setError(e instanceof Error ? e.message : "خطا در دریافت گزارش هفتگی");
      } finally {
        setLoading(false);
      }
    },
    [childId]
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  if (loading && !data) return <SkeletonStats count={4} />;

  return (
    <Section
      title="گزارش هفتگی"
      subtitle="جمع‌بندی هفتگی فرزندتان: پیشرفت برنامه، تسط و ماندگاری، آزمون‌های هفته، خطاهای باز و اقدام پیشنهادی."
      action={
        <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => void load(true)}>
          تازه‌سازی گزارش
        </Button>
      }
    >
      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-line bg-surface-sunken px-4 py-3 text-[11px] text-ink-muted">
            <span className="num">
              بازه: {fmtDate(data.week_start)} تا {fmtDate(data.week_end)}
            </span>
            <span className="flex items-center gap-2">
              <Badge tone={data.cached ? "neutral" : "success"} dot>
                {data.cached ? "از کش همین هفته" : "تازه ساخته شد"}
              </Badge>
              <span className="num">زمان تولید: {fmtDateTime(data.generated_at)}</span>
            </span>
          </div>

          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label="پیشرفت برنامه‌ی هفته"
              value={`${fa(data.plan.week_done_pct, 1)}٪`}
              tone="primary"
              icon={<IconTasks size={20} />}
              hint={`${fa(data.plan.week_done)} از ${fa(data.plan.week_total)} کار هفته`}
            />
            <StatCard
              label="تسط واقعی"
              value={`${fa(data.mastery.mastery_pct, 1)}٪`}
              tone="success"
              icon={<IconTarget size={20} />}
              hint={
                data.mastery.avg_retention === null
                  ? "ماندگاری: بدون داده کافی"
                  : `ماندگاری میانگین ${fa(data.mastery.avg_retention * 100)}٪`
              }
            />
            <StatCard
              label="آزمون‌های هفته"
              value={fa(data.exams.count)}
              tone="sky"
              icon={<IconExam size={20} />}
              hint={data.exams.avg_percent === null ? "بدون نمره" : `میانگین ${fa(data.exams.avg_percent, 1)}٪`}
            />
            <StatCard
              label="خطاهای باز"
              value={fa(data.errors.open)}
              tone={data.errors.open > 0 ? "danger" : "success"}
              icon={<IconAlert size={20} />}
              hint={data.errors.repeated_open > 0 ? `${fa(data.errors.repeated_open)} مورد تکراری` : "بدون تکرار"}
            />
          </section>

          <section className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="میزان پیشرفت برنامه" subtitle="کل برنامه در برابر کارهای همین هفته" icon={<IconTrend size={17} />} />
              <div className="space-y-3">
                <ProgressBar value={data.plan.progress_pct} label={`کل برنامه (${fa(data.plan.done)}/${fa(data.plan.total)})`} showValue />
                <ProgressBar value={data.plan.week_done_pct} tone="success" label={`هفته‌ی جاری (${fa(data.plan.week_done)}/${fa(data.plan.week_total)})`} showValue />
                <ProgressBar
                  value={data.plan.total > 0 ? (100 * (data.plan.total - data.plan.overdue)) / data.plan.total : 100}
                  tone={data.plan.overdue > 0 ? "warning" : "success"}
                  label="کارهای در موعد"
                  showValue
                />
              </div>
            </Card>

            <Card>
              <CardHeader title="تسط و ماندگاری" subtitle="وضعیت مباحث و مباحث نیازمند مرور" icon={<IconTarget size={17} />} />
              <ul className="space-y-2">
                {STATUS_ORDER.map((s) => (
                  <li key={s} className="flex items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2">
                    <span className="flex items-center gap-2 text-xs">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLOR[s] }} />
                      {STATUS_FA[s]}
                    </span>
                    <span className="num text-xs font-bold text-ink">{fa(data.mastery.status_counts[s] ?? 0)} مبحث</span>
                  </li>
                ))}
              </ul>
              {data.mastery.weak_topics.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {data.mastery.weak_topics.map((t) => (
                    <li key={t.topic_id} className="flex items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-2">
                      <span className="truncate text-xs font-semibold text-ink">{t.title ?? "مبحث نامشخص"}</span>
                      <span className="num shrink-0 text-[11px] text-ink-muted">
                        تسط {fa(t.effective_mastery, 1)}٪ · ماندگاری {fa(t.retention * 100)}٪
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <CardHeader title="آزمون‌های هفته" subtitle="نتایج ثبت‌شده در این بازه" icon={<IconExam size={17} />} />
              {data.exams.list.length === 0 ? (
                <EmptyState compact icon={<IconExam size={24} />} title="آزمونی در این هفته ثبت نشده" description="پس از شرکت در آزمون، نمره این‌جا می‌آید." />
              ) : (
                <ul className="space-y-2">
                  {data.exams.list.map((ex) => (
                    <li key={ex.attempt_id} className="flex items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-ink">{ex.title}</p>
                        <p className="text-[11px] text-ink-faint">
                          {subjectFa(ex.subject)} · {fmtDateTime(ex.submitted_at)}
                        </p>
                      </div>
                      <span className="flex shrink-0 items-center gap-2">
                        {ex.delta !== null && (
                          <Badge tone={ex.delta > 0 ? "success" : ex.delta < 0 ? "warning" : "neutral"}>
                            {ex.delta > 0 ? "↑" : ex.delta < 0 ? "↓" : "→"} {fa(Math.abs(ex.delta), 1)}
                          </Badge>
                        )}
                        <span className="num text-sm font-extrabold text-ink">{ex.percent === null ? "—" : `${fa(ex.percent, 1)}٪`}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <CardHeader title="فعالیت هفته" subtitle="کارهای انجام‌شده در برابر اثرشان" icon={<IconClock size={17} />} />
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-surface-sunken p-3 text-center">
                  <p className="num text-lg font-extrabold text-ink">{fa(data.activity.minutes_spent, 1)}</p>
                  <p className="text-[11px] text-ink-muted">دقیقه فعالیت آزمونی</p>
                </div>
                <div className="rounded-xl bg-surface-sunken p-3 text-center">
                  <p className="num text-lg font-extrabold text-ink">{fa(data.activity.questions_answered)}</p>
                  <p className="text-[11px] text-ink-muted">سؤال پاسخ‌داده‌شده</p>
                </div>
                <div className="rounded-xl bg-surface-sunken p-3 text-center">
                  <p className="num text-lg font-extrabold text-ink">{fa(data.activity.evidence_count)}</p>
                  <p className="text-[11px] text-ink-muted">شواهد یادگیری ثبت‌شده</p>
                </div>
                <div className="rounded-xl bg-surface-sunken p-3 text-center">
                  <p className="num text-lg font-extrabold text-ink">{fa(data.activity.tasks_done)}</p>
                  <p className="text-[11px] text-ink-muted">کار برنامه انجام‌شده</p>
                </div>
              </div>
              <div className="mt-4">
                <p className="mb-2 text-xs font-bold text-ink-muted">خطاهای باز به تفکیک علت</p>
                <div className="flex flex-wrap gap-2">
                  {data.errors.by_cause.length === 0 ? (
                    <Badge tone="success">خطای بازی نیست</Badge>
                  ) : (
                    data.errors.by_cause.map((c) => (
                      <Badge key={c.cause} tone="warning">
                        {c.cause_fa} · {fa(c.count)}
                      </Badge>
                    ))
                  )}
                </div>
              </div>
            </Card>
          </section>

          <Card>
            <CardHeader
              title="هشدارهای این هفته"
              subtitle={`${fa(data.alerts.length)} هشدار ثبت شده است`}
              icon={<IconAlert size={17} />}
              action={
                data.alerts.length > 0 ? (
                  <Badge tone={data.alerts.some((a) => a.severity === "danger") ? "danger" : "warning"} dot>
                    {data.alerts.filter((a) => a.severity === "danger").length} فوری
                  </Badge>
                ) : undefined
              }
            />
            {data.alerts.length === 0 ? (
              <EmptyState compact icon={<IconCheckCircle size={24} />} title="هشداری این هفته ثبت نشده" description="سیگنال نگران‌کننده‌ای دیده نمی‌شود." />
            ) : (
              <ul className="space-y-2">
                {data.alerts.map((a, i) => (
                  <li key={`${a.code}-${i}`} className="flex items-start justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-ink">{a.title}</span>
                      <span className="block text-[11px] leading-5 text-ink-muted">{a.message}</span>
                    </span>
                    <Badge tone={SEV_TONE[a.severity]} dot>
                      {SEV_FA[a.severity]}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card variant="brand">
            <CardHeader title="اقدام پیشنهادی والد برای هفته‌ی آینده" icon={<IconCheckCircle size={17} />} />
            <ol className="space-y-2">
              {data.actions.map((a, i) => (
                <li key={i} className="flex items-start gap-2.5 rounded-xl bg-white/70 px-3.5 py-2.5 text-xs leading-6 text-ink">
                  <span className="num grid h-5 w-5 shrink-0 place-items-center rounded-full bg-primary-100 text-[10px] font-bold text-primary-700">
                    {fa(i + 1)}
                  </span>
                  {a}
                </li>
              ))}
            </ol>
            <p className="mt-3 text-[11px] leading-6 text-ink-muted">
              این پیشنهادها فقط از برنامه، آزمون‌ها و مباحث فرزند شما ساخته می‌شوند و جایگزین نظر معلم نیستند.
            </p>
          </Card>

          {data.note_fa && <Alert variant="info" title="حریم خصوصی">{data.note_fa}</Alert>}
        </>
      )}
    </Section>
  );
}
