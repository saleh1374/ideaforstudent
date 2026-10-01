"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { SkeletonCard } from "@/components/ui/skeleton";
import {
  IconAlert,
  IconChevronLeft,
  IconClock,
  IconExam,
  IconHome,
  IconLayers,
  IconRefresh,
  IconTarget,
  IconTasks,
} from "@/components/ui/icons";

/* ——— تقویم / برنامه دوره‌ای (student spec §4 + §13) ——— */

type Kind = "task" | "exam" | "period" | "retest" | "mission";

type CalTask = { id: number; type: string; title: string; priority: number; topic_id: number | null };

type CalItem = {
  kind: Kind;
  title: string;
  detail: string;
  due: string;
  status: string;
  highlight: "today" | "overdue" | "soon" | null;
  ref: { type: string; id: number | null };
  tasks?: CalTask[];
  free_day?: boolean;
};

type CalDay = {
  date: string;
  weekday: string;
  is_today: boolean;
  is_free_day: boolean;
  items: CalItem[];
  counts: Record<string, number>;
};

type CalendarData = {
  from: string;
  to: string;
  today: string;
  days: CalDay[];
  mission: CalItem | null;
  summary: {
    pending_tasks: number;
    overdue: number;
    exams_soon: number;
    open_errors: number;
    retest_pending: boolean;
    free_today: boolean;
    suggested_minutes: number;
  };
  note_fa: string;
};

const KIND_META: Record<Kind, { label: string; icon: typeof IconTasks; tone: Tone }> = {
  task: { label: "کار برنامه", icon: IconTasks, tone: "primary" },
  exam: { label: "آزمون", icon: IconExam, tone: "accent" },
  period: { label: "دوره آموزشی", icon: IconLayers, tone: "info" },
  retest: { label: "بازآزمون", icon: IconRefresh, tone: "warning" },
  mission: { label: "مأموریت روزانه", icon: IconTarget, tone: "success" },
};

const STATUS_FA: Record<string, string> = {
  pending: "در صف",
  done: "انجام‌شده",
  overdue: "جا‌مانده",
  open: "باز",
  upcoming: "پیش رو",
  active: "در جریان",
  needs_build: "نیازمند ساخت",
  scheduled: "زمان‌بندی‌شده",
  light: "سبک",
  missed: "جا‌مانده",
  moved: "جابه‌جا شده",
};

const HL_CLASS: Record<string, string> = {
  overdue: "border-danger-100 bg-danger-50/60",
  soon: "border-warning-100 bg-warning-50/50",
  today: "border-primary-300 bg-primary-50/50",
};

const HL_LABEL: Record<string, string> = {
  overdue: "سررسید گذشته",
  soon: "تا ۴۸ ساعت آینده",
  today: "امروز",
};

/** «۲۰۲۶-۱۰-۰۱» → Date محلی (بدون جابه‌جایی منطقهٔ زمانی). */
function parseISO(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

function addDays(base: Date, n: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + n);
  return d;
}

function isoOf(d: Date): string {
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function fmtDayLabel(iso: string): string {
  try {
    return parseISO(iso).toLocaleDateString("fa-IR", { weekday: "long", day: "numeric", month: "long" });
  } catch {
    return iso;
  }
}

function fmtDue(due: string): string {
  if (!due) return "—";
  if (due.length <= 10) return parseISO(due).toLocaleDateString("fa-IR", { dateStyle: "medium" });
  try {
    return new Date(due.replace(" ", "T")).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return due;
  }
}

export default function StudentCalendarPage() {
  const [data, setData] = useState<CalendarData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [rangeStart, setRangeStart] = useState<Date | null>(null);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setRangeStart(new Date());
  }, []);

  const load = useCallback(async (start: Date) => {
    setLoading(true);
    setError("");
    try {
      const from = isoOf(start);
      const to = isoOf(addDays(start, 6));
      setData(await api<CalendarData>(`/student/calendar?from=${from}&to=${to}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت تقویم");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (rangeStart) load(rangeStart);
  }, [rangeStart, load]);

  const totals = useMemo(() => {
    const kinds = new Set<string>();
    (data?.days ?? []).forEach((d) => d.items.forEach((i) => kinds.add(i.kind)));
    return kinds.size;
  }, [data]);

  const summary = data?.summary;

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="تقویم و برنامه دوره‌ای"
          description="کارها، پنجره آزمون‌ها، دوره ۱۴ روزه، چرخه ترمیم و مأموریت روزانه در یک نما؛ روزهای آزاد و سررسیدهای نزدیک مشخص شده‌اند."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "تقویم" }]}
          actions={
            <>
              <ButtonLink href="/student/tasks" variant="soft" size="sm" icon={<IconTasks size={15} />}>
                برنامه امروز
              </ButtonLink>
              <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
                خانه
              </ButtonLink>
            </>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت تقویم">{error}</Alert>}

        {/* ——— نمای کلیدی ——— */}
        {summary && !error && (
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="کارهای امروز"
              value={fa(summary.pending_tasks)}
              tone="primary"
              icon={<IconClock size={20} />}
              hint={summary.free_today ? `روز آزاد — تا ${fa(summary.suggested_minutes)} دقیقه` : `روز مدرسه — تا ${fa(summary.suggested_minutes)} دقیقه`}
            />
            <StatCard
              label="کارهای جا‌مانده"
              value={fa(summary.overdue)}
              tone={summary.overdue > 0 ? "danger" : "success"}
              icon={<IconAlert size={20} />}
              hint="اولویت اول امروز"
            />
            <StatCard
              label="آزمون تا ۴۸ ساعت"
              value={fa(summary.exams_soon)}
              tone={summary.exams_soon > 0 ? "warning" : "sky"}
              icon={<IconExam size={20} />}
              hint={summary.retest_pending ? "بازآزمون ترمیمی در جریان" : "مهلت‌های نزدیک"}
            />
            <StatCard
              label="خطاهای باز"
              value={fa(summary.open_errors)}
              tone="accent"
              icon={<IconRefresh size={20} />}
              hint="برای چرخه ترمیم/بازآزمون"
            />
          </section>
        )}

        {/* ——— مأموریت روزانه ——— */}
        {data?.mission && (
          <Card variant="gradient" className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/20">
                  <IconTarget size={19} />
                </span>
                <div>
                  <h2 className="text-sm font-extrabold">{data.mission.title}</h2>
                  <p className="mt-1 text-xs leading-6 text-white/80">{data.mission.detail}</p>
                </div>
              </div>
              <Badge tone="neutral" className="bg-white/20 text-white ring-white/30">
                {STATUS_FA[data.mission.status] ?? data.mission.status}
              </Badge>
            </div>
            {(data.mission.tasks?.length ?? 0) > 0 && (
              <ul className="flex flex-wrap gap-2">
                {data.mission.tasks!.map((t) => (
                  <li key={t.id} className="num rounded-xl bg-white/15 px-3 py-2 text-[11px] font-semibold">
                    {t.title}
                    <span className="mr-2 font-normal text-white/70">اولویت {fa(t.priority, 2)}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap gap-2">
              <ButtonLink
                href="/student/tasks"
                size="sm"
                className="border-white/30 bg-white/15 text-white hover:bg-white/25"
                icon={<IconTasks size={14} />}
              >
                شروع کارها
              </ButtonLink>
              <ButtonLink
                href="/student/errors"
                size="sm"
                variant="ghost"
                className="border-white/30 bg-white/10 text-white hover:bg-white/20"
                icon={<IconAlert size={14} />}
              >
                دفترچه خطا
              </ButtonLink>
            </div>
          </Card>
        )}

        {/* ——— کنترل بازه ——— */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => setRangeStart((p) => (p ? addDays(p, -7) : p))}>
              ۷ روز قبل
            </Button>
            <Button size="sm" variant="soft" onClick={() => setRangeStart(new Date())}>
              امروز
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<IconChevronLeft size={14} />}
              onClick={() => setRangeStart((p) => (p ? addDays(p, 7) : p))}
            >
              ۷ روز بعد
            </Button>
          </div>
          {data && (
            <p className="num text-xs text-ink-muted">
              {fmtDayLabel(data.from)} تا {fmtDayLabel(data.to)} · {fa(data.days.length)} روز · {fa(totals)} نوع رویداد
            </p>
          )}
        </div>

        {data && <p className="rounded-xl bg-surface-sunken px-4 py-3 text-[11px] leading-6 text-ink-muted">{data.note_fa}</p>}

        {loading && !data && (
          <div className="space-y-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {/* ——— روزها ——— */}
        <div className="space-y-4">
          {data?.days.map((day) => {
            const others = day.items.filter((i) => i.kind !== "mission");
            return (
              <Card
                key={day.date}
                className={`overflow-hidden p-0 ${day.is_today ? "ring-2 ring-primary-300" : ""}`}
              >
                <div
                  className={`flex flex-wrap items-center justify-between gap-3 px-5 py-4 ${
                    day.is_today ? "bg-brand-gradient text-white" : "border-b border-line bg-surface-sunken"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className={`text-sm font-extrabold ${day.is_today ? "text-white" : "text-ink"}`}>
                      {fmtDayLabel(day.date)}
                    </span>
                    {day.is_today && (
                      <Badge tone="neutral" className="bg-white/25 text-white ring-white/40">
                        امروز
                      </Badge>
                    )}
                    {!day.is_today && (
                      <Badge tone={day.is_free_day ? "success" : "neutral"} dot={day.is_free_day}>
                        {day.is_free_day ? "روز آزاد" : "روز مدرسه"}
                      </Badge>
                    )}
                    {day.is_today && (
                      <span className="rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-semibold text-white">
                        {day.is_free_day ? "روز آزاد" : "روز مدرسه"}
                      </span>
                    )}
                  </div>
                  <div className={`flex flex-wrap items-center gap-1.5 text-[11px] ${day.is_today ? "text-white/85" : "text-ink-faint"}`}>
                    {Object.entries(day.counts).map(([k, n]) => (
                      <span key={k} className="rounded-lg bg-surface px-2 py-0.5 font-semibold text-ink-muted">
                        {KIND_META[k as Kind]?.label ?? k}: {fa(n)}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="space-y-2.5 p-4">
                  {others.length === 0 && (
                    <EmptyState
                      compact
                      title="رویدادی برای این روز نیست"
                      description="کارها، آزمون‌ها و دورهٔ جاری به‌محض ثبت، اینجا نمایش داده می‌شوند."
                    />
                  )}
                  {others.map((item, idx) => {
                    const meta = KIND_META[item.kind] ?? KIND_META.task;
                    const Icon = meta.icon;
                    const hl = item.highlight ? HL_CLASS[item.highlight] : "";
                    return (
                      <div
                        key={`${item.kind}-${idx}`}
                        className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border p-3.5 ${
                          hl || "border-line bg-surface"
                        }`}
                      >
                        <div className="flex min-w-0 items-start gap-3">
                          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                            <Icon size={16} />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-sm font-bold text-ink">{item.title}</p>
                              <Badge tone={meta.tone}>{meta.label}</Badge>
                              <Badge tone={item.status === "done" ? "success" : item.status === "overdue" ? "danger" : "neutral"}>
                                {STATUS_FA[item.status] ?? item.status}
                              </Badge>
                              {item.highlight && (
                                <Badge tone={item.highlight === "overdue" ? "danger" : item.highlight === "soon" ? "warning" : "primary"} dot>
                                  {HL_LABEL[item.highlight]}
                                </Badge>
                              )}
                            </div>
                            <p className="mt-1 text-[11px] leading-6 text-ink-muted">{item.detail}</p>
                          </div>
                        </div>
                        <span className="num shrink-0 text-[11px] font-semibold text-ink-faint">{fmtDue(item.due)}</span>
                      </div>
                    );
                  })}
                </div>
              </Card>
            );
          })}
        </div>

        {data && data.days.every((d) => d.items.filter((i) => i.kind !== "mission").length === 0) && (
          <EmptyState
            icon={<IconLayers size={26} />}
            title="در این بازه رویدادی نیست"
            description="بازهٔ دیگری را ببین یا صبر کن تا برنامه و آزمون‌ها ثبت شوند."
            action={
              <Button size="sm" variant="soft" onClick={() => setRangeStart(new Date())}>
                بازگشت به امروز
              </Button>
            }
          />
        )}
      </div>
    </AppShell>
  );
}
