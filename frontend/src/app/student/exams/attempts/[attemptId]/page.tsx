"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, getToken } from "@/lib/api";
import { CAUSE_FA, EXAM_TYPE_FA, STATUS_FA, fa, subjectFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { RadialProgress } from "@/components/ui/charts";
import { SkeletonCard } from "@/components/ui/skeleton";
import {
  IconAlert,
  IconArrowLeft,
  IconCheckCircle,
  IconClock,
  IconExam,
  IconTarget,
  IconTrend,
} from "@/components/ui/icons";

/* ——— مرور تک‌تلاش آزمون: سؤال‌به‌سؤال + دلتای تسط مبحث‌ها ——— */

type Question = {
  order: number;
  exam_item_id: number;
  body: string;
  options: Record<string, string>;
  points: number;
  selected: string | null;
  correct_option: string;
  is_correct: boolean;
  answered: boolean;
  time_spent_ms: number;
  confidence: number | null;
  answer_changes: number;
  topic_id: number;
  topic_title: string | null;
  error_cause: string | null;
  error_record: { id: number; status: string; status_fa: string } | null;
};

type TopicDelta = {
  topic_id: number;
  title: string;
  before_e: number;
  after_e: number;
  delta_e: number;
  status_before: string;
  status_after: string;
};

type AttemptInfo = {
  id: number;
  exam_id: number;
  exam_title: string;
  exam_type: string;
  subject: string | null;
  submitted_at: string | null;
  started_at: string | null;
  percent: number | null;
  raw_score: number | null;
  item_count: number;
  correct: number;
  wrong: number;
  unanswered: number;
  time_spent_ms: number;
  delta_percent: number | null;
  negative_marking: { applied: boolean; k: number; penalty: number };
  errors_recorded: number;
  errors_resolved: number;
};

type Detail = {
  attempt: AttemptInfo;
  questions: Question[];
  topics_before_after: TopicDelta[];
  causes: Record<string, number>;
};

function fmtDate(v: string | null): string | null {
  if (!v) return null;
  try {
    return new Date(v.replace(" ", "T")).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return v;
  }
}

function fmtMs(ms: number): string {
  const min = Math.round(ms / 60000);
  if (min < 1) return "کمتر از یک دقیقه";
  return `${fa(min)} دقیقه`;
}

export default function AttemptReviewPage() {
  const params = useParams<{ attemptId: string }>();
  const attemptId = Number(params.attemptId);

  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<Detail>(`/student/exam-history/${attemptId}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "خطا"))
      .finally(() => setLoading(false));
  }, [attemptId]);

  const a = data?.attempt;
  const good = (a?.percent ?? 0) >= 60;

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title={a ? `مرور آزمون — ${a.exam_title}` : "مرور آزمون"}
          description="هر سؤال با پاسخ تو، پاسخ صحیح و علت خطا؛ و تغییر تسط مبحث‌ها قبل و بعد از همین آزمون."
          crumbs={[
            { label: "دانشیار" },
            { label: "دانش‌آموز", href: "/student" },
            { label: "آزمون‌ها", href: "/student/exams" },
            { label: "تاریخچه", href: "/student/exams" },
            { label: `تلاش ${fa(attemptId)}` },
          ]}
          actions={
            <ButtonLink href="/student/exams" variant="ghost" size="sm" icon={<IconArrowLeft size={15} />}>
              بازگشت به تاریخچه
            </ButtonLink>
          }
        />

        {error && (
          <Alert variant="danger" title="خطا در دریافت مرور آزمون">
            {error}
          </Alert>
        )}

        {loading && !data && !error && (
          <div className="space-y-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {data && a && (
          <>
            {/* ——— کارنامه ——— */}
            <Card className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="primary">{EXAM_TYPE_FA[a.exam_type] ?? a.exam_type}</Badge>
                  {a.subject && <Badge tone="neutral">{subjectFa(a.subject)}</Badge>}
                  <Badge tone={good ? "success" : "warning"} dot>
                    {good ? "عملکرد خوب" : "نیازمند مرور"}
                  </Badge>
                  <Badge tone="neutral">{fmtDate(a.submitted_at) ?? fmtDate(a.started_at)}</Badge>
                  {a.delta_percent !== null && (
                    <Badge tone={a.delta_percent >= 0 ? "success" : "danger"} dot>
                      {a.delta_percent >= 0 ? "▲" : "▼"} {fa(Math.abs(a.delta_percent), 1)}٪ نسبت به تلاش قبل
                    </Badge>
                  )}
                  {a.delta_percent === null && <Badge tone="neutral">تلاش اول این آزمون</Badge>}
                </div>
                <div className="flex items-center gap-5">
                  <RadialProgress
                    value={a.percent ?? 0}
                    size={132}
                    thickness={12}
                    color={good ? "#12b76a" : "#f79009"}
                    format={(v) => `${fa(v, 1)}٪`}
                    label="درصد نهایی"
                  />
                  <div className="space-y-1 text-sm">
                    <p className="num font-extrabold text-ink">نمره: {fa(a.raw_score ?? 0, 2)}</p>
                    <p className="num text-xs text-ink-muted">
                      {fa(a.correct)} درست از {fa(a.item_count)} سؤال
                    </p>
                  </div>
                </div>
              </div>
            </Card>

            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="پاسخ‌ها"
                value={
                  <span className="num">
                    <span className="text-success-600">{fa(a.correct)}</span>
                    <span className="mx-1 text-base font-bold text-ink-faint">/</span>
                    <span className="text-danger-600">{fa(a.wrong)}</span>
                    <span className="mx-1 text-base font-bold text-ink-faint">/</span>
                    {fa(a.unanswered)}
                  </span>
                }
                tone="primary"
                icon={<IconCheckCircle size={20} />}
                hint="صحیح / غلط / نزده"
              />
              <StatCard label="زمان پاسخ" value={fmtMs(a.time_spent_ms)} tone="sky" icon={<IconClock size={20} />} hint="مجموع همه سؤال‌ها" />
              <StatCard
                label="نمره منفی"
                value={a.negative_marking.applied ? fa(a.negative_marking.penalty, 2) : "غیرفعال"}
                tone={a.negative_marking.applied ? "warning" : "success"}
                icon={<IconAlert size={20} />}
                hint={a.negative_marking.applied ? `ضریب k=${fa(a.negative_marking.k, 2)}` : "برای این آزمون فعال نیست"}
              />
              <StatCard
                label="خطاهای ثبت‌شده"
                value={
                  <span>
                    {fa(a.errors_recorded)}{" "}
                    <span className="text-base font-bold text-ink-faint">· رفع‌شده {fa(a.errors_resolved)}</span>
                  </span>
                }
                tone="accent"
                icon={<IconTarget size={20} />}
                hint="هر خطا وارد دفترچه خطا شد"
              />
            </section>

            {/* ——— علت‌ها ——— */}
            {Object.keys(data.causes).length > 0 && (
              <Card>
                <CardHeader title="توزیع علت خطاها" subtitle="طبقه‌بندی شش‌گانهٔ سند دانش‌آموز (§6)" icon={<IconAlert size={17} />} />
                <div className="flex flex-wrap gap-2">
                  {Object.entries(data.causes).map(([c, n]) => (
                    <Badge key={c} tone="warning">
                      {CAUSE_FA[c] ?? c}: {fa(n)}
                    </Badge>
                  ))}
                </div>
              </Card>
            )}

            {/* ——— دلتای تسط مباحث ——— */}
            <Card>
              <CardHeader
                title="تسط مباحث، قبل و بعد از این آزمون"
                subtitle="شواهد همین تلاش چقدر تسط مؤثر (E) را جابه‌جا کرده است."
                icon={<IconTrend size={17} />}
              />
              {data.topics_before_after.length === 0 ? (
                <EmptyState compact title="مبحثی برای این آزمون ثبت نشده" description="سؤال‌های آزمون به مباحث کاتالوگ متصل نیستند." />
              ) : (
                <div className="space-y-3">
                  {data.topics_before_after.map((t) => (
                    <div key={t.topic_id} className="rounded-xl border border-line bg-surface p-3.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-bold text-ink">{t.title}</p>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={statusTone(t.status_before)}>{STATUS_FA[t.status_before] ?? t.status_before}</Badge>
                          <span className="text-ink-faint">←</span>
                          <Badge tone={statusTone(t.status_after)}>{STATUS_FA[t.status_after] ?? t.status_after}</Badge>
                          <Badge tone={t.delta_e > 0 ? "success" : t.delta_e < 0 ? "danger" : "neutral"} dot>
                            {t.delta_e >= 0 ? "+" : "−"}
                            {fa(Math.abs(t.delta_e), 1)} واحد
                          </Badge>
                        </div>
                      </div>
                      <div className="mt-2 flex items-center gap-3 text-[11px] text-ink-muted">
                        <span className="num">قبل: {fa(t.before_e, 1)}٪</span>
                        <span className="h-1.5 flex-1 rounded-full bg-slate-200/70">
                          <span
                            className="block h-1.5 rounded-full bg-primary-500 transition-[width]"
                            style={{ width: `${Math.max(2, Math.min(100, t.after_e))}%` }}
                          />
                        </span>
                        <span className="num font-semibold text-ink">بعد: {fa(t.after_e, 1)}٪</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* ——— مرور سؤال‌ها ——— */}
            <section className="space-y-3">
              <h2 className="text-sm font-bold text-ink">مرور سؤال‌ها ({fa(data.questions.length)})</h2>
              {data.questions.map((q) => (
                <Card
                  key={q.exam_item_id}
                  className={`space-y-3 ${!q.answered ? "border-warning-100 bg-warning-50/40" : q.is_correct ? "" : "border-danger-100 bg-danger-50/40"}`}
                >
                  <div className="flex items-start gap-3">
                    <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-xs font-bold text-primary-700">
                      {fa(q.order)}
                    </span>
                    <p className="text-sm font-semibold leading-8 text-ink">{q.body}</p>
                    <span className="mr-auto shrink-0">
                      {q.is_correct ? (
                        <Badge tone="success" dot>پاسخ درست</Badge>
                      ) : !q.answered ? (
                        <Badge tone="warning" dot>بدون پاسخ</Badge>
                      ) : (
                        <Badge tone="danger" dot>پاسخ غلط</Badge>
                      )}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {Object.entries(q.options).map(([k, v]) => {
                      const isCorrect = k === q.correct_option;
                      const isMine = k === q.selected;
                      return (
                        <div
                          key={k}
                          className={`flex items-start gap-2 rounded-xl border px-3.5 py-3 text-sm ${
                            isCorrect
                              ? "border-success-500/40 bg-success-50 text-success-700"
                              : isMine
                                ? "border-danger-500/40 bg-danger-50 text-danger-700"
                                : "border-line bg-surface text-ink-muted"
                          }`}
                        >
                          <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-lg text-xs font-bold bg-slate-100 text-ink-muted">
                            {k}
                          </span>
                          <span className="leading-6">
                            {v}
                            {isCorrect && <span className="mr-2 text-[11px] font-bold">✓ پاسخ صحیح</span>}
                            {isMine && !isCorrect && <span className="mr-2 text-[11px] font-bold">پاسخ من</span>}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl bg-surface-sunken px-3.5 py-2.5 text-[11px] text-ink-muted">
                    <span>
                      مبحث: <b className="text-ink">{q.topic_title ?? `#${q.topic_id}`}</b>
                    </span>
                    <span className="num">زمان: {fmtMs(q.time_spent_ms)}</span>
                    {q.confidence !== null && <span className="num">اطمینان: {fa(q.confidence)} از ۵</span>}
                    {q.answer_changes > 0 && <span className="num">تغییر پاسخ: {fa(q.answer_changes)}</span>}
                    {q.error_cause && (
                      <Badge tone="warning">علت خطا: {CAUSE_FA[q.error_cause] ?? q.error_cause}</Badge>
                    )}
                    {q.error_record && (
                      <Badge tone={statusTone(q.error_record.status)} dot>
                        خطا: {q.error_record.status_fa}
                      </Badge>
                    )}
                  </div>
                </Card>
              ))}
            </section>

            <div className="flex flex-wrap justify-center gap-2 pb-4">
              <ButtonLink href={`/student/exams/${a.exam_id}`} icon={<IconExam size={15} />} size="sm">
                شروع تلاش بعدی
              </ButtonLink>
              <ButtonLink href="/student/errors" variant="soft" size="sm" icon={<IconAlert size={15} />}>
                دفترچه خطا
              </ButtonLink>
              <ButtonLink href="/student/calendar" variant="ghost" size="sm" icon={<IconTarget size={15} />}>
                تقویم
              </ButtonLink>
            </div>
          </>
        )}

        {!loading && !data && !error && (
          <EmptyState
            icon={<IconExam size={26} />}
            title="تلاشی یافت نشد"
            description="شاید این تلاش متعلق به حساب دیگری باشد."
            action={
              <ButtonLink href="/student/exams" size="sm" variant="soft">
                بازگشت به آزمون‌ها
              </ButtonLink>
            }
          />
        )}
      </div>
    </AppShell>
  );
}
