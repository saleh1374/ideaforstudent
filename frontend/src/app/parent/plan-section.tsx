"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { EXAM_TYPE_FA, TASK_TYPE_FA, fa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty";
import { ProgressBar } from "@/components/ui/progress";
import { StatCard } from "@/components/ui/stat";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconClock, IconExam, IconRefresh, IconTarget, IconTasks } from "@/components/ui/icons";

/** برنامه/تکلیف فقط‌خواندنی — GET /parent/children/{id}/plan (سند §6، §8) */
type PlanTaskRow = {
  id: number;
  task_type: string;
  topic_id: number | null;
  topic: string | null;
  for_date: string;
  priority: number;
  status: string;
  minicheck_passed: boolean;
  due: boolean;
  overdue: boolean;
};

type UpcomingExam = {
  id: number;
  title: string;
  exam_type: string | null;
  subject: string | null;
  opens_at: string | null;
  closes_at: string | null;
  days_left: number | null;
  is_open: boolean;
};

type PlanData = {
  student_id: number;
  summary: {
    total: number;
    done: number;
    pending: number;
    missed: number;
    moved: number;
    due_today: number;
    overdue: number;
    progress_pct: number;
  };
  tasks: PlanTaskRow[];
  upcoming_exams: UpcomingExam[];
  next_exam: UpcomingExam | null;
  note_fa: string;
};

const TASK_STATUS_FA: Record<string, string> = {
  pending: "در انتظار انجام",
  done: "انجام شده",
  missed: "جا مانده",
  moved: "جابه‌جا شده",
};

function fmtDate(v: string): string {
  try {
    return new Date(v).toLocaleDateString("fa-IR", { dateStyle: "medium" });
  } catch {
    return v;
  }
}

export function PlanSection({ childId }: { childId: number }) {
  const [data, setData] = useState<PlanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api<PlanData>(`/parent/children/${childId}/plan`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) toast(e.detail ?? "این فرزند به شما متصل نیست", "error");
      else setError(e instanceof Error ? e.message : "خطا در دریافت برنامه");
    } finally {
      setLoading(false);
    }
  }, [childId]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: Column<PlanTaskRow>[] = [
    {
      key: "task",
      header: "فعالیت",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.topic ?? TASK_TYPE_FA[row.task_type] ?? row.task_type}</p>
          <span className="text-[11px] text-ink-faint">{TASK_TYPE_FA[row.task_type] ?? row.task_type}</span>
        </div>
      ),
    },
    { key: "date", header: "موعد", align: "center", render: (row) => <span className="num text-xs">{fmtDate(row.for_date)}</span> },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={statusTone(row.status)} dot>
          {TASK_STATUS_FA[row.status] ?? row.status}
        </Badge>
      ),
    },
    {
      key: "priority",
      header: "اولویت",
      align: "center",
      render: (row) => <span className="num text-xs">{fa(row.priority, 2)}</span>,
    },
    {
      key: "flag",
      header: "",
      align: "end",
      render: (row) =>
        row.overdue ? (
          <Badge tone="danger" dot>
            عقب‌افتاده
          </Badge>
        ) : row.due ? (
          <Badge tone="warning" dot>
            موعد امروز
          </Badge>
        ) : row.minicheck_passed ? (
          <Badge tone="success">آزمونک گذشته</Badge>
        ) : (
          <span className="text-[11px] text-ink-faint">—</span>
        ),
    },
  ];

  if (loading && !data) {
    return (
      <div className="space-y-5">
        <SkeletonStats count={4} />
        <SkeletonTable rows={4} cols={4} />
      </div>
    );
  }

  const s = data?.summary;

  return (
    <Section
      title="برنامه و تکالیف"
      subtitle="کارهای امروز و آینده، موعدها و وضعیت انجام — نمای فقط‌خواندنی؛ تغییر برنامه فقط از موتور برنامه‌ریز و معلم انجام می‌شود."
      action={
        <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => void load()}>
          تازه‌سازی
        </Button>
      }
    >
      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {data && s && (
        <>
          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="کل کارهای برنامه" value={fa(s.total)} tone="primary" icon={<IconTasks size={20} />} hint={`${fa(s.done)} انجام شده`} />
            <StatCard
              label="موعد امروز"
              value={fa(s.due_today)}
              tone={s.due_today > 0 ? "warning" : "success"}
              icon={<IconClock size={20} />}
              hint={s.due_today > 0 ? "کارهای امروز" : "چیزی برای امروز نمانده"}
            />
            <StatCard
              label="عقب‌افتاده"
              value={fa(s.overdue)}
              tone={s.overdue > 0 ? "danger" : "success"}
              icon={<IconAlert size={20} />}
              hint={s.overdue > 0 ? "نیازمند پیگیری" : "همه در موعد"}
            />
            <StatCard label="آزمون پیش رو" value={data.next_exam ? `${fa(data.next_exam.days_left ?? 0)} روز` : "—"} tone="sky" icon={<IconExam size={20} />} hint={data.next_exam?.title ?? "آزمون منتشرشده‌ای نیست"} />
          </section>

          <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
            <ProgressBar value={s.progress_pct} label="پیشرفت کل برنامه" showValue />
          </div>

          {data.upcoming_exams.length > 0 && (
            <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
              <p className="mb-3 text-xs font-bold text-ink-muted">بازه آزمون‌های پیش رو</p>
              <ul className="space-y-2">
                {data.upcoming_exams.map((ex) => (
                  <li key={ex.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                    <span className="truncate text-xs font-semibold text-ink">{ex.title}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Badge tone="neutral">{ex.exam_type ? EXAM_TYPE_FA[ex.exam_type] ?? ex.exam_type : "—"}</Badge>
                      <Badge tone={ex.is_open ? "success" : "info"} dot>
                        {ex.is_open ? "باز شده" : "شروع نشده"}
                      </Badge>
                      <span className="num text-[11px] text-ink-muted">
                        {ex.days_left === null ? "بدون مهلت" : `${fa(ex.days_left)} روز تا پایان`}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.tasks.length === 0 ? (
            <EmptyState
              icon={<IconTarget size={26} />}
              title="برنامه‌ای برای این فرزند ثبت نشده است"
              description="پس از ساخت برنامه توسط موتور برنامه‌ریز، کارهای روزانه این‌جا دیده می‌شود."
            />
          ) : (
            <DataTable
              columns={columns}
              rows={data.tasks}
              keyOf={(row) => row.id}
              empty={<EmptyState compact title="موردی برای نمایش نیست" />}
            />
          )}

          {data.note_fa && <Alert variant="info" title="نکته">{data.note_fa}</Alert>}
        </>
      )}
    </Section>
  );
}
