"use client";

import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { TASK_TYPE_FA, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonCard } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconClock, IconHome, IconTasks } from "@/components/ui/icons";

type Task = {
  id: number;
  type: string;
  topic_id: number | null;
  for_date: string;
  priority: number;
  status: string;
  payload: Record<string, unknown>;
};

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ tasks: Task[] }>("/student/tasks")
      .then((d) => setTasks(d.tasks))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function complete(t: Task, minicheck: boolean) {
    setBusyId(t.id);
    try {
      await api(`/student/tasks/${t.id}/complete`, { method: "POST", json: { minicheck_passed: minicheck } });
      setTasks((prev) => prev.map((x) => (x.id === t.id ? { ...x, status: "done" } : x)));
      toast("کار انجام شد ✓", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ثبت کار", "error");
    } finally {
      setBusyId(null);
    }
  }

  const pending = tasks.filter((t) => t.status === "pending");
  const done = tasks.filter((t) => t.status === "done");
  const total = pending.length + done.length;
  const donePct = total > 0 ? (done.length / total) * 100 : 0;

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="برنامه امروز"
          description="کارهای امروز بر اساس اولویت و وضعیت یادگیری شما چیده شده‌اند."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "برنامه امروز" }]}
          actions={
            <>
              <ButtonLink href="/student/calendar" variant="soft" size="sm" icon={<IconClock size={15} />}>
                تقویم دوره
              </ButtonLink>
              <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
                خانه
              </ButtonLink>
            </>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت برنامه">{error}</Alert>}

        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard label="کارهای در صف" value={fa(pending.length)} tone="primary" icon={<IconClock size={20} />} hint="تا پایان امروز" />
          <StatCard label="انجام‌شده" value={fa(done.length)} tone="success" icon={<IconCheckCircle size={20} />} hint="از کل برنامه امروز" />
          <Card className="flex flex-col justify-center">
            <ProgressBar value={donePct} tone={donePct >= 66 ? "success" : "primary"} showValue label="پیشرفت روز" />
            <p className="mt-2 text-[11px] leading-5 text-ink-faint">
              {donePct >= 100 ? "عالی! برنامه امروز کامل شد 🎉" : "هر کار را که تمام کردی، ثبتش کن تا تحلیل به‌روز شود."}
            </p>
          </Card>
        </section>

        {/* pending */}
        <section className="space-y-3">
          <h2 className="text-sm font-bold text-ink">در صف اجرا</h2>

          {loading && (
            <div className="space-y-3">
              <SkeletonCard />
              <SkeletonCard />
            </div>
          )}

          {!loading && pending.length === 0 && !error && (
            <EmptyState
              icon={<IconTasks size={26} />}
              title="کار در صفی نیست 🎉"
              description="برنامه امروز تمام شده است. می‌توانی سراغ مرور مباحث یا دفترچه خطا بروی."
              action={
                <div className="flex gap-2">
                  <ButtonLink href="/student/errors" variant="soft" size="sm">
                    دفترچه خطا
                  </ButtonLink>
                  <ButtonLink href="/student/books" variant="ghost" size="sm">
                    کتاب‌های من
                  </ButtonLink>
                </div>
              }
            />
          )}

          {!loading &&
            pending.map((t, i) => (
              <Card key={t.id} className="flex animate-fade-in-up items-center justify-between gap-4" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="flex min-w-0 items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                    <IconTasks size={18} />
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-bold text-ink">{TASK_TYPE_FA[t.type] ?? t.type}</p>
                      <Badge tone={t.type === "lesson" ? "primary" : "neutral"}>اولویت {fa(t.priority, 2)}</Badge>
                    </div>
                    <p className="mt-0.5 text-[11px] text-ink-faint">
                      {t.type === "lesson" ? "بعد از مطالعه، آزمونک کوتاه بده." : "پس از انجام، وضعیت را ثبت کن."}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    loading={busyId === t.id}
                    onClick={() => complete(t, t.type === "lesson")}
                    icon={t.type === "lesson" ? <IconCheckCircle size={14} /> : undefined}
                  >
                    {t.type === "lesson" ? "آزمونک دادم ✓" : "انجام شد"}
                  </Button>
                </div>
              </Card>
            ))}
        </section>

        {/* done */}
        {done.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-bold text-ink-muted">انجام‌شده‌ها ({fa(done.length)})</h2>
            <div className="rounded-2xl border border-line bg-surface divide-y divide-line-soft shadow-soft">
              {done.map((t) => (
                <div key={t.id} className="flex items-center justify-between px-5 py-3">
                  <span className="flex items-center gap-3 text-sm text-ink-muted">
                    <span className="grid h-7 w-7 place-items-center rounded-lg bg-success-50 text-success-600">
                      <IconCheckCircle size={15} />
                    </span>
                    <span className="line-through decoration-ink-faint">{TASK_TYPE_FA[t.type] ?? t.type}</span>
                  </span>
                  <Badge tone="success">✓ انجام شد</Badge>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
