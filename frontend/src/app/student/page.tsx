"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, getToken, HomeData } from "@/lib/api";
import { STATUS_FA, STATUS_ORDER, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonCard, SkeletonStats, SkeletonText } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { DonutChart, RadialProgress } from "@/components/ui/charts";
import {
  IconAlert,
  IconArrowLeft,
  IconBook,
  IconCheckCircle,
  IconChart,
  IconClock,
  IconExam,
  IconSparkles,
  IconTarget,
  IconTasks,
  IconTrend,
} from "@/components/ui/icons";
import { StudentScheduleSection } from "./schedule-section";

const STATUS_SEG_COLOR: Record<string, string> = {
  mastered: "#10b981",
  consolidating: "#0ea5e9",
  weak: "#f59e0b",
  critical: "#f43f5e",
  unknown: "#cbd5e1",
};

const QUICK_LINKS = [
  { href: "/student/tasks", label: "برنامه امروز", icon: IconTasks },
  { href: "/student/calendar", label: "تقویم دوره", icon: IconClock },
  { href: "/student/books", label: "کتاب‌های من", icon: IconBook },
  { href: "/student/errors", label: "دفترچه خطا", icon: IconAlert },
  { href: "/student/exams", label: "آزمون‌ها", icon: IconExam },
  { href: "/assistant", label: "دستیار هوشمند", icon: IconSparkles },
  { href: "/boards", label: "بردها", icon: IconChart },
];

/** خروجی GET /student/plan/status — کنترل بار و توقف موقت برنامه (§4.3). */
type PlanStatus = {
  paused: boolean;
  pause: { id?: number; start_date: string; end_date: string; reason_fa?: string | null; days_left: number } | null;
  message_fa: string | null;
  load: {
    date: string;
    cap_minutes: number;
    used_minutes: number;
    remaining_minutes: number;
    paused: boolean;
    cap_message_fa?: string | null;
  };
  note_fa?: string;
};

/** خروجی GET /student/xp — فقط عدد واقعی امتیاز/زنجیره (§8). */
type XpSummary = {
  total_xp: number;
  today_xp: number;
  streak: number;
  active_days: number;
};

export default function StudentHome() {
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState("");

  const [plan, setPlan] = useState<PlanStatus | null>(null);
  const [planError, setPlanError] = useState("");
  const [planLoading, setPlanLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  const [xp, setXp] = useState<XpSummary | null>(null);
  const [xpError, setXpError] = useState("");

  async function loadPlan(silent = false) {
    if (!silent) setPlanLoading(true);
    try {
      setPlan(await api<PlanStatus>("/student/plan/status"));
      setPlanError("");
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "خطا");
    } finally {
      if (!silent) setPlanLoading(false);
    }
  }

  function loadXp() {
    api<XpSummary>("/student/xp")
      .then((d) => {
        setXp(d);
        setXpError("");
      })
      .catch((e) => setXpError(e.message));
  }

  /** توقف/ادامهٔ برنامه با رابط خوش‌بینانه + همگام‌سازی نهایی با سرور. */
  async function togglePlan() {
    if (!plan || toggling) return;
    const pausing = !plan.paused;
    setPlan({ ...plan, paused: pausing, pause: pausing ? plan.pause : null }); // خوش‌بینانه
    setToggling(true);
    try {
      const res = pausing
        ? await api<{ message_fa: string }>("/student/plan/pause", { method: "POST", json: {} })
        : await api<{ message_fa: string }>("/student/plan/resume", { method: "POST" });
      toast(res.message_fa, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در تغییر وضعیت برنامه", "error");
    } finally {
      setToggling(false);
      await loadPlan(true);
    }
  }

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<HomeData>("/student/home").then(setData).catch((e) => setError(e.message));
    loadPlan();
    loadXp();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="خانه — وضعیت امروز"
          description="پیشرفت برنامه و تسط واقعی دو شاخص جدا هستند؛ شکافشان اولویت امروز را تعیین می‌کند."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز" }, { label: "خانه" }]}
          actions={
            <>
              <Button variant="ghost" size="sm" icon={<IconSparkles size={15} />} onClick={() => (window.location.href = "/assistant")}>
                دستیار
              </Button>
              <Button size="sm" icon={<IconTasks size={15} />} onClick={() => (window.location.href = "/student/tasks")}>
                برنامه امروز
              </Button>
            </>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت اطلاعات">{error}</Alert>}

        {!data && !error && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <div className="grid gap-5 lg:grid-cols-3">
              <SkeletonCard className="lg:col-span-1" />
              <SkeletonCard />
              <SkeletonCard />
            </div>
          </div>
        )}

        {data && (
          <>
            {/* ——— KPI row ——— */}
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                gradient
                label="پیشرفت در برنامه"
                value={`${fa(data.progress_pct, 1)}٪`}
                icon={<IconTrend size={20} />}
                hint="از کل برنامه درسی سال"
              />
              <StatCard
                label="تسط واقعی"
                value={`${fa(data.mastery_pct, 1)}٪`}
                tone="success"
                icon={<IconTarget size={20} />}
                delta={
                  Math.abs(data.gap) >= 15
                    ? { value: `${fa(Math.abs(data.gap), 1)} واحد`, direction: data.gap > 0 ? "down" : "up", label: "شکاف" }
                    : undefined
                }
                hint="یادگیری تثبیت‌شده"
              />
              <StatCard
                label="خطاهای رفع‌شده"
                value={
                  <span>
                    {fa(data.errors_resolved)}{" "}
                    <span className="text-base font-bold text-ink-faint">از {fa(data.errors_total)}</span>
                  </span>
                }
                tone="accent"
                icon={<IconCheckCircle size={20} />}
                hint={`نرخ رفع خطا: ${fa(data.resolved_pct, 1)}٪`}
              />
              <StatCard
                label="مباحث نیازمند تمرکز"
                value={fa((data.status_counts.critical ?? 0) + (data.status_counts.weak ?? 0))}
                tone="danger"
                icon={<IconAlert size={20} />}
                hint="بحرانی + ضعیف"
              />
            </section>

            {/* ——— gap warning ——— */}
            {Math.abs(data.gap) >= 15 && (
              <Alert variant="warning" title="شکاف پیشرفت و تسط">
                شکاف {fa(Math.abs(data.gap), 1)} واحدی بین پیشرفت و تسط —{" "}
                {data.gap > 0
                  ? "«خوانده اما جا نیفتاده»؛ مرور و ترمیم اولویت دارد."
                  : "«تسط بالا، عقبی در برنامه»؛ سرعت درس جدید را بررسی کن."}
              </Alert>
            )}

            {/* ——— کنترل برنامه (§4.3) + امتیاز یادگیری (§8) ——— */}
            <section className="grid gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader
                  title="کنترل برنامه"
                  subtitle="توقف موقت و سقف بار روزانه — «برنامهٔ اصلی تغییر نمی‌کند»"
                  icon={<IconClock size={17} />}
                  action={
                    plan && !planError ? (
                      <Button size="sm" variant={plan.paused ? "success" : "ghost"} loading={toggling} onClick={togglePlan}>
                        {plan.paused ? "ادامه برنامه" : "توقف موقت"}
                      </Button>
                    ) : undefined
                  }
                />

                {planLoading && !plan && <SkeletonText lines={3} />}

                {!planLoading && planError && (
                  <div className="space-y-3">
                    <Alert variant="warning" title="خطا در دریافت وضعیت برنامه">
                      {planError}
                    </Alert>
                    <Button size="sm" variant="soft" onClick={() => loadPlan()}>
                      تلاش دوباره
                    </Button>
                  </div>
                )}

                {plan && !planError && (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={plan.paused ? "warning" : "success"} dot>
                        {plan.paused ? "برنامه متوقف" : "برنامه فعال"}
                      </Badge>
                      {plan.paused && plan.pause && (
                        <Badge tone="neutral">تا {fa(plan.pause.days_left)} روز دیگر</Badge>
                      )}
                      <Badge tone="info">
                        بار امروز {fa(plan.load.used_minutes)} از {fa(plan.load.cap_minutes)} دقیقه
                      </Badge>
                    </div>
                    <ProgressBar
                      value={plan.load.used_minutes}
                      max={Math.max(plan.load.cap_minutes, 1)}
                      tone={plan.load.remaining_minutes > 0 ? "primary" : "warning"}
                      label={`${fa(plan.load.used_minutes)} از ${fa(plan.load.cap_minutes)} دقیقه مجاز امروز`}
                      showValue
                    />
                    <p className="text-xs leading-6 text-ink-muted">
                      {plan.message_fa ?? plan.load.cap_message_fa ?? plan.note_fa ?? plan.pause?.reason_fa ?? ""}
                    </p>
                  </div>
                )}
              </Card>

              {xpError ? (
                <Card className="space-y-3">
                  <CardHeader title="امتیاز یادگیری (XP)" icon={<IconSparkles size={17} />} />
                  <Alert variant="warning">خطا در دریافت امتیاز: {xpError}</Alert>
                  <Button size="sm" variant="soft" onClick={loadXp}>
                    تلاش دوباره
                  </Button>
                </Card>
              ) : (
                <StatCard
                  label="امتیاز یادگیری (XP)"
                  value={xp ? fa(xp.total_xp) : "…"}
                  tone="accent"
                  icon={<IconSparkles size={20} />}
                  hint={xp ? `امروز ${fa(xp.today_xp)} XP · زنجیره ${fa(xp.streak)} روز فعال` : "در حال دریافت…"}
                />
              )}
            </section>

            {/* ——— charts & quick access ——— */}
            <section className="grid gap-5 lg:grid-cols-3">
              <Card>
                <CardHeader title="وضعیت مباحث" subtitle="توزیع مباحث بر اساس سطح تسط" icon={<IconChart size={17} />} />
                <DonutChart
                  data={STATUS_ORDER.map((s) => ({
                    label: STATUS_FA[s],
                    value: data.status_counts[s] ?? 0,
                    color: STATUS_SEG_COLOR[s],
                  }))}
                  size={150}
                  centerSubtitle="مبحث"
                  format={(v) => fa(v)}
                />
              </Card>

              <Card>
                <CardHeader title="چرخه رفع خطا" subtitle="از ثبت خطا تا رفع‌شدن" icon={<IconCheckCircle size={17} />} />
                <div className="grid place-items-center py-2">
                  <RadialProgress value={data.resolved_pct} label="خطاهای رفع‌شده" format={(v) => `${fa(v, 1)}٪`} />
                </div>
                <div className="mt-3 flex items-center justify-between rounded-xl bg-surface-sunken px-3.5 py-2.5 text-xs">
                  <span className="text-ink-muted">خطای باز</span>
                  <span className="num font-bold text-ink">{fa(data.errors_total - data.errors_resolved)}</span>
                </div>
              </Card>

              <Card>
                <CardHeader title="دسترسی سریع" icon={<IconSparkles size={17} />} />
                <div className="grid grid-cols-2 gap-2.5">
                  {QUICK_LINKS.map((l) => {
                    const Icon = l.icon;
                    return (
                      <Link
                        key={l.href}
                        href={l.href}
                        className="group flex items-center gap-2.5 rounded-xl border border-line bg-surface-sunken px-3 py-3 text-xs font-semibold text-ink-muted transition hover:border-primary-300 hover:bg-primary-50 hover:text-primary-700"
                      >
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface text-ink-faint shadow-soft transition group-hover:text-primary-600">
                          <Icon size={16} />
                        </span>
                        <span className="truncate">{l.label}</span>
                      </Link>
                    );
                  })}
                </div>

                {data.next_exam && (
                  <div className="mt-3 rounded-xl bg-brand-gradient p-4 text-white shadow-lift">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <span className="inline-flex items-center rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-semibold text-white">
                          آزمون بعدی
                        </span>
                        <p className="mt-2 truncate text-sm font-bold">{data.next_exam.title}</p>
                      </div>
                      <Link
                        href={`/student/exams/${data.next_exam.id}`}
                        className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/20 text-white transition hover:bg-white/30"
                        aria-label="رفتن به آزمون"
                      >
                        <IconArrowLeft size={16} />
                      </Link>
                    </div>
                  </div>
                )}
              </Card>
            </section>

            {/* ——— برنامه هفتگی کلاس (همان داده‌ای که مدیر مدرسه ثبت می‌کند) ——— */}
            <StudentScheduleSection />

            {/* ——— empty safeguard ——— */}
            {STATUS_ORDER.every((s) => (data.status_counts[s] ?? 0) === 0) && (
              <Section>
                <EmptyState
                  title="هنوز مبحثی ثبت نشده"
                  description="با شروع آزمون‌ها و تمرین‌ها، وضعیت مباحث اینجا نمایش داده می‌شود."
                  action={
                    <Button size="sm" onClick={() => (window.location.href = "/student/exams")}>
                      رفتن به آزمون‌ها
                    </Button>
                  }
                />
              </Section>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
