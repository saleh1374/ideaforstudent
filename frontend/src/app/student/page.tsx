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
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { SkeletonCard, SkeletonStats } from "@/components/ui/skeleton";
import { DonutChart, RadialProgress } from "@/components/ui/charts";
import {
  IconAlert,
  IconArrowLeft,
  IconBook,
  IconCheckCircle,
  IconChart,
  IconExam,
  IconSparkles,
  IconTarget,
  IconTasks,
  IconTrend,
} from "@/components/ui/icons";

const STATUS_SEG_COLOR: Record<string, string> = {
  mastered: "#10b981",
  consolidating: "#0ea5e9",
  weak: "#f59e0b",
  critical: "#f43f5e",
  unknown: "#cbd5e1",
};

const QUICK_LINKS = [
  { href: "/student/tasks", label: "برنامه امروز", icon: IconTasks },
  { href: "/student/books", label: "کتاب‌های من", icon: IconBook },
  { href: "/student/errors", label: "دفترچه خطا", icon: IconAlert },
  { href: "/student/exams", label: "آزمون‌ها", icon: IconExam },
  { href: "/assistant", label: "دستیار هوشمند", icon: IconSparkles },
  { href: "/boards", label: "بردها", icon: IconChart },
];

export default function StudentHome() {
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<HomeData>("/student/home").then(setData).catch((e) => setError(e.message));
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
