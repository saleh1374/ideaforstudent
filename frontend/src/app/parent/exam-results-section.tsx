"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { EXAM_TYPE_FA, fa, subjectFa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty";
import { Modal } from "@/components/ui/modal";
import { StatCard } from "@/components/ui/stat";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { LineChart } from "@/components/ui/charts";
import { IconAlert, IconExam, IconRefresh, IconTarget, IconTrend } from "@/components/ui/icons";

/** نمرات آزمون‌ها — GET /parent/children/{id}/exam-results (سند §3) */
type ExamRow = {
  attempt_id: number;
  exam_id: number;
  title: string;
  exam_type: string | null;
  subject: string | null;
  grade: string | null;
  attempt_status: string;
  score: number | null;
  percent: number | null;
  delta: number | null;
  correct: number;
  wrong: number;
  blank: number;
  total: number;
  negative_marking: { enabled: boolean; k: number; points_lost: number };
  time_spent_seconds: number;
  started_at: string | null;
  submitted_at: string | null;
};

type ExamResults = {
  student_id: number;
  exams: ExamRow[];
  trend: number[];
  summary: {
    count: number;
    avg_percent: number | null;
    best_percent: number | null;
    latest_percent: number | null;
    negative_marking_exams: number;
    total_time_seconds: number;
  };
  note_fa: string;
};

type ExamDetail = {
  attempt_id: number;
  exam: { id: number; title: string; exam_type: string | null; subject: string | null; grade: string | null };
  score: number | null;
  percent: number | null;
  correct: number;
  wrong: number;
  blank: number;
  total: number;
  negative_marking: { enabled: boolean; k: number; points_lost: number };
  time_spent_seconds: number;
  submitted_at: string | null;
  topics: { topic_id: number | null; topic: string | null; total: number; correct: number; wrong: number; blank: number; percent: number }[];
  error_causes: { cause: string; cause_fa: string; count: number }[];
  wrong_items: { position: number; topic: string | null; body: string | null; selected: string | null; correct: string | null; cause_fa: string }[];
  note_fa: string;
};

function fmtDateTime(v: string | null): string {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return v;
  }
}

function fmtSeconds(s: number): string {
  if (s <= 0) return "—";
  const m = Math.floor(s / 60);
  const rest = Math.round(s % 60);
  return m > 0 ? `${fa(m)} دقیقه ${fa(rest)} ثانیه` : `${fa(rest)} ثانیه`;
}

export function ExamResultsSection({ childId }: { childId: number }) {
  const [data, setData] = useState<ExamResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<ExamDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api<ExamResults>(`/parent/children/${childId}/exam-results`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) toast(e.detail ?? "این فرزند به شما متصل نیست", "error");
      else setError(e instanceof Error ? e.message : "خطا در دریافت نمرات آزمون‌ها");
    } finally {
      setLoading(false);
    }
  }, [childId]);

  useEffect(() => {
    void load();
  }, [load]);

  function closeDetail() {
    setDetail(null);
    setDetailError("");
    setDetailLoading(false);
  }

  async function openDetail(attemptId: number) {
    setDetail(null);
    setDetailError("");
    setDetailLoading(true);
    try {
      setDetail(await api<ExamDetail>(`/parent/children/${childId}/exam-results/${attemptId}`));
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "خطا در دریافت جزئیات");
    } finally {
      setDetailLoading(false);
    }
  }

  const columns: Column<ExamRow>[] = [
    {
      key: "title",
      header: "آزمون",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.title}</p>
          <span className="text-[11px] text-ink-faint">
            {subjectFa(row.subject)} · {fmtDateTime(row.submitted_at)}
          </span>
        </div>
      ),
    },
    {
      key: "type",
      header: "نوع",
      align: "center",
      render: (row) => <Badge tone="neutral">{row.exam_type ? EXAM_TYPE_FA[row.exam_type] ?? row.exam_type : "—"}</Badge>,
    },
    {
      key: "percent",
      header: "درصد",
      align: "center",
      render: (row) => <span className="num font-extrabold text-ink">{row.percent === null ? "—" : `${fa(row.percent, 1)}٪`}</span>,
    },
    {
      key: "delta",
      header: "روند",
      align: "center",
      render: (row) =>
        row.delta === null ? (
          <span className="text-[11px] text-ink-faint">اولین آزمون</span>
        ) : (
          <Badge tone={row.delta > 0 ? "success" : row.delta < 0 ? "warning" : "neutral"}>
            {row.delta > 0 ? "↑" : row.delta < 0 ? "↓" : "→"} {fa(Math.abs(row.delta), 1)} واحد
          </Badge>
        ),
    },
    {
      key: "counts",
      header: "صحیح/غلط/نزده",
      align: "center",
      render: (row) => (
        <span className="num text-xs">
          <span className="font-bold text-success-600">{fa(row.correct)}</span>
          <span className="text-ink-faint"> / </span>
          <span className="font-bold text-danger-600">{fa(row.wrong)}</span>
          <span className="text-ink-faint"> / </span>
          <span className="font-bold text-ink-muted">{fa(row.blank)}</span>
          <span className="text-ink-faint"> از {fa(row.total)}</span>
        </span>
      ),
    },
    {
      key: "neg",
      header: "نمره منفی",
      align: "center",
      render: (row) =>
        row.negative_marking.enabled ? (
          <span className="num text-[11px] text-warning-700">
            −{fa(row.negative_marking.points_lost, 2)} (k={fa(row.negative_marking.k, 2)})
          </span>
        ) : (
          <span className="text-[11px] text-ink-faint">غیرفعال</span>
        ),
    },
    {
      key: "time",
      header: "زمان",
      align: "center",
      render: (row) => <span className="num text-xs">{fmtSeconds(row.time_spent_seconds)}</span>,
    },
  ];

  if (loading && !data) {
    return (
      <div className="space-y-5">
        <SkeletonStats count={4} />
        <SkeletonTable rows={4} cols={5} />
      </div>
    );
  }

  return (
    <Section
      title="نمرات آزمون‌ها"
      subtitle="نمره، درصد، صحیح/غلط/نزده، نمره منفی (در صورت فعال‌بودن)، زمان صرف‌شده و روند نسبت به آزمون قبلی."
      action={
        <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => void load()}>
          تازه‌سازی
        </Button>
      }
    >
      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {data && data.exams.length === 0 && !error && (
        <EmptyState
          icon={<IconExam size={26} />}
          title="هنوز آزمونی ثبت نشده است"
          description="پس از شرکت فرزندتان در آزمون رسمی، نمره و تحلیل آن همین‌جا نمایش داده می‌شود."
        />
      )}

      {data && data.exams.length > 0 && (
        <>
          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label="میانگین درصد"
              value={data.summary.avg_percent === null ? "—" : `${fa(data.summary.avg_percent, 1)}٪`}
              tone="primary"
              icon={<IconTrend size={20} />}
              spark={data.trend.length > 1 ? data.trend : undefined}
            />
            <StatCard
              label="بهترین نمره"
              value={data.summary.best_percent === null ? "—" : `${fa(data.summary.best_percent, 1)}٪`}
              tone="success"
              icon={<IconTarget size={20} />}
            />
            <StatCard
              label="آخرین نمره"
              value={data.summary.latest_percent === null ? "—" : `${fa(data.summary.latest_percent, 1)}٪`}
              tone="sky"
              icon={<IconExam size={20} />}
              hint={`${fa(data.summary.count)} آزمون ثبت‌شده`}
            />
            <StatCard
              label="زمان کل پاسخ‌ها"
              value={fmtSeconds(data.summary.total_time_seconds)}
              tone="accent"
              icon={<IconAlert size={20} />}
              hint={
                data.summary.negative_marking_exams > 0
                  ? `${fa(data.summary.negative_marking_exams)} آزمون با نمره منفی`
                  : "بدون نمره منفی"
              }
            />
          </section>

          {data.trend.length > 1 && (
            <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
              <p className="mb-2 text-xs font-bold text-ink-muted">روند درصد آزمون‌ها (قدیمی → جدید)</p>
              <LineChart points={data.trend} height={180} format={(v) => `${fa(v, 1)}٪`} />
            </div>
          )}

          <DataTable
            columns={columns}
            rows={data.exams}
            keyOf={(row) => row.attempt_id}
            onRowClick={(row) => void openDetail(row.attempt_id)}
            empty={<EmptyState compact title="موردی برای نمایش نیست" />}
          />

          {data.note_fa && <Alert variant="info" title="حریم خصوصی">{data.note_fa}</Alert>}
        </>
      )}

      <Modal open={detail !== null || detailLoading || detailError !== ""} onClose={closeDetail} title={detail?.exam.title ?? "جزئیات نتیجه آزمون"} size="lg">
        {detailLoading && <SkeletonTable rows={4} cols={3} />}
        {!detailLoading && detailError && <Alert variant="danger" title="خطا">{detailError}</Alert>}
        {!detailLoading && detail && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl bg-surface-sunken p-3 text-center">
                <p className="num text-xl font-extrabold text-ink">{detail.percent === null ? "—" : `${fa(detail.percent, 1)}٪`}</p>
                <p className="text-[11px] text-ink-muted">درصد</p>
              </div>
              <div className="rounded-xl bg-surface-sunken p-3 text-center">
                <p className="num text-xl font-extrabold text-ink">{detail.score === null ? "—" : fa(detail.score, 2)}</p>
                <p className="text-[11px] text-ink-muted">نمره خام</p>
              </div>
              <div className="rounded-xl bg-surface-sunken p-3 text-center">
                <p className="num text-xl font-extrabold text-success-600">{fa(detail.correct)}</p>
                <p className="text-[11px] text-ink-muted">پاسخ درست</p>
              </div>
              <div className="rounded-xl bg-surface-sunken p-3 text-center">
                <p className="num text-xl font-extrabold text-danger-600">{fa(detail.wrong)}</p>
                <p className="text-[11px] text-ink-muted">پاسخ غلط</p>
              </div>
            </div>

            <div className="rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] leading-6 text-ink-muted">
              <p className="num">
                نزده: {fa(detail.blank)} · کل سؤال‌ها: {fa(detail.total)} · زمان: {fmtSeconds(detail.time_spent_seconds)} · ثبت:{" "}
                {fmtDateTime(detail.submitted_at)}
              </p>
              <p>
                نمره منفی:{" "}
                {detail.negative_marking.enabled
                  ? `فعال (k=${fa(detail.negative_marking.k, 2)}) — ${fa(detail.negative_marking.points_lost, 2)} امتیاز کسر شد`
                  : "غیرفعال"}
              </p>
            </div>

            <div>
              <p className="mb-2 text-xs font-bold text-ink">وضعیت هر مبحث در این آزمون</p>
              <ul className="space-y-2">
                {detail.topics.map((t, i) => (
                  <li key={`${t.topic_id ?? i}`} className="flex items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                    <span className="truncate text-xs font-semibold text-ink">{t.topic ?? "مبحث نامشخص"}</span>
                    <span className="num shrink-0 text-[11px] text-ink-muted">
                      {fa(t.correct)}/{fa(t.total)} درست · {fa(t.percent, 1)}٪
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="mb-2 text-xs font-bold text-ink">نوع خطاها</p>
              <div className="flex flex-wrap gap-2">
                {detail.error_causes.length === 0 ? (
                  <Badge tone="success">خطایی ثبت نشده است</Badge>
                ) : (
                  detail.error_causes.map((c) => (
                    <Badge key={c.cause} tone="warning">
                      {c.cause_fa} · {fa(c.count)}
                    </Badge>
                  ))
                )}
              </div>
            </div>

            {detail.wrong_items.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-bold text-ink">سؤال‌های نادرست</p>
                <ul className="space-y-2">
                  {detail.wrong_items.map((q, i) => (
                    <li key={i} className="rounded-xl border border-line bg-surface px-3.5 py-3">
                      <p className="text-xs leading-6 text-ink">{q.body}</p>
                      <p className="mt-1 text-[11px] text-ink-muted">
                        پاسخ انتخابی: {q.selected ?? "—"} · پاسخ درست: {q.correct ?? "—"} · علت: {q.cause_fa}
                        {q.topic ? ` · ${q.topic}` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.note_fa && <Alert variant="info">{detail.note_fa}</Alert>}
          </div>
        )}
      </Modal>
    </Section>
  );
}
