"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonCard, SkeletonStats } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconAlert,
  IconChart,
  IconCheckCircle,
  IconExam,
  IconLayers,
  IconTarget,
  IconUsers,
} from "@/components/ui/icons";

type AlertRow = {
  severity: "high" | "medium" | "low";
  class_id: number;
  class_name: string;
  topic_id: number;
  title_fa: string;
  evidence_fa: string;
  action_fa: string;
  action_view: string;
};

type Task = {
  title: string;
  detail: string;
  priority: string;
  class_id: number | null;
  topic_id: number | null;
  view?: string;
};

type Home = {
  classes: number;
  kpis: {
    avg_mastery: number | null;
    plan_progress_pct: number | null;
    exam_pct: number | null;
    weak_topics: number;
    prereq_flagged: number;
  } | null;
  alerts: AlertRow[];
  tasks: Task[];
  note_fa: string;
};

const SEVERITY: Record<string, { dot: string; label: string; tone: "danger" | "warning" | "neutral" }> = {
  high: { dot: "🔴", label: "بحرانی", tone: "danger" },
  medium: { dot: "🟠", label: "نیازمند بررسی", tone: "warning" },
  low: { dot: "🟡", label: "در حال شکل‌گیری", tone: "neutral" },
};

const PRIORITY_LABEL: Record<string, string> = { high: "امروز", medium: "این هفته", low: "پایش" };

/**
 * خانهٔ معلم (سند معلم §2): به چهار سؤال جواب می‌دهد — چه کنم؟ چه چیزی
 * نیازمند توجه است؟ KPIهای کلان؟ و کارت‌های اقدام با دکمه رفتن به بخش مربوط.
 */
export function TeacherHomeSection({
  onGoClass,
  onGoBuilder,
}: {
  onGoClass: (classId: number) => void;
  onGoBuilder: () => void;
}) {
  const [home, setHome] = useState<Home | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    api<Home>("/teacher/home")
      .then((d) => alive && setHome(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : "خطا در دریافت خانه"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="space-y-5">
        <SkeletonStats count={3} />
        <SkeletonCard />
      </div>
    );
  }

  if (error) {
    return <Alert variant="danger" title="خطا در دریافت اطلاعات">{error}</Alert>;
  }

  if (!home || home.classes === 0) {
    return (
      <EmptyState
        icon={<IconUsers size={26} />}
        title="کلاسی به شما تخصیص نیافته است"
        description="پس از تخصیص کلاس توسط مدیر مدرسه، خانهٔ معلم پر می‌شود."
      />
    );
  }

  const k = home.kpis;
  const go = (a: AlertRow) => onGoClass(a.class_id);

  return (
    <div className="space-y-6">
      {/* ——— KPIهای کلان ——— */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="میانگین تسط مؤثر"
          value={k?.avg_mastery !== null && k?.avg_mastery !== undefined ? `${fa(k.avg_mastery, 1)}٪` : "—"}
          tone="primary"
          icon={<IconTarget size={20} />}
          hint="همه کلاس‌های شما"
        />
        <div>
          <StatCard
            label="پیشرفت برنامه"
            value={k?.plan_progress_pct !== null && k?.plan_progress_pct !== undefined ? `${fa(k.plan_progress_pct)}٪` : "—"}
            tone="accent"
            icon={<IconCheckCircle size={20} />}
            hint="کارهای انجام‌شده دانش‌آموزان"
          />
        </div>
        <StatCard
          label="میانگین آزمون دوره"
          value={k?.exam_pct !== null && k?.exam_pct !== undefined ? `${fa(k.exam_pct, 1)}٪` : "—"}
          tone="success"
          icon={<IconExam size={20} />}
          hint="فقط آزمون‌های تصحیح‌شده"
        />
        <StatCard
          label="مباحث نیازمند کار"
          value={fa((k?.weak_topics ?? 0) + (k?.prereq_flagged ?? 0))}
          tone="warning"
          icon={<IconLayers size={20} />}
          hint={`${fa(k?.weak_topics ?? 0)} ضعیف · ${fa(k?.prereq_flagged ?? 0)} پیش‌نیاز`}
        />
      </section>

      {k?.plan_progress_pct !== null && k?.plan_progress_pct !== undefined && (
        <Card>
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-bold text-ink">پیشرفت برنامهٔ دانش‌آموزان شما</p>
            <span className="num text-xs font-bold text-ink">{fa(k.plan_progress_pct)}٪</span>
          </div>
          <ProgressBar value={k.plan_progress_pct} size="md" tone={k.plan_progress_pct < 50 ? "danger" : k.plan_progress_pct < 75 ? "warning" : "success"} />
        </Card>
      )}

      {/* ——— کارهای پیشنهادی امروز ——— */}
      <Section
        title="امروز چه کاری می‌توانم انجام دهم؟"
        subtitle="کارهای استخراج‌شده از دادهٔ واقعی کلاس‌ها — هر کدام دکمه اقدام دارد."
      >
        {home.tasks.length === 0 ? (
          <EmptyState
            compact
            icon={<IconCheckCircle size={24} />}
            title="کار فوری‌ای پیدا نشد"
            description="با ثبت آزمون و تمرین، پیشنهادهای امروز اینجا ظاهر می‌شوند."
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {home.tasks.map((t, i) => (
              <Card key={i} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-ink">{t.title}</p>
                  <p className="mt-1 text-[11px] leading-6 text-ink-muted">{t.detail}</p>
                </div>
                <Button
                  size="sm"
                  variant="soft"
                  onClick={() => {
                    if (t.view === "builder") onGoBuilder();
                    else if (t.class_id !== null) onGoClass(t.class_id);
                    else toast("از سازندهٔ آزمون استفاده کنید.", "info");
                  }}
                >
                  {t.view === "builder" ? "ساخت آزمون" : "شروع"}
                </Button>
              </Card>
            ))}
          </div>
        )}
      </Section>

      {/* ——— هشدارها ——— */}
      <Section title="چه چیزی نیازمند توجه است؟" subtitle={home.note_fa}>
        {home.alerts.length === 0 ? (
          <EmptyState
            compact
            icon={<IconAlert size={24} />}
            title="هشداری ثبت نشده"
            description="همه شاخص‌ها در محدوده عادی هستند."
          />
        ) : (
          <div className="space-y-3">
            {home.alerts.map((a, i) => (
              <Card key={i} className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 text-base leading-6" aria-hidden="true">
                    {SEVERITY[a.severity]?.dot ?? "🟡"}
                  </span>
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-bold text-ink">
                      {a.title_fa}
                      <Badge tone={SEVERITY[a.severity]?.tone ?? "neutral"}>
                        {SEVERITY[a.severity]?.label ?? a.severity}
                      </Badge>
                    </p>
                    <p className="mt-1 text-[11px] leading-6 text-ink-muted">{a.evidence_fa}</p>
                    <p className="mt-1 text-[11px] font-semibold text-primary-700">
                      اقدام پیشنهادی: {a.action_fa}
                    </p>
                  </div>
                </div>
                <Button size="sm" variant="ghost" icon={<IconChart size={14} />} onClick={() => go(a)}>
                  مشاهده
                </Button>
              </Card>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
