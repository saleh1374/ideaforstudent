"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  EXAM_STATUS_FA,
  OPTION_LETTER_FA,
  QUALIFICATION_STATUS_FA,
  QUALIFICATION_STATUS_TONE,
  fa,
  subjectFa,
} from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Modal } from "@/components/ui/modal";
import { ProgressBar } from "@/components/ui/progress";
import { DataTable, type Column } from "@/components/ui/table";
import { RadialProgress } from "@/components/ui/charts";
import { SkeletonCard, SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconExam, IconGraduation, IconSend, IconTarget } from "@/components/ui/icons";

type QualBrief = {
  id: number;
  subject: string | null;
  subject_fa: string;
  school_year: string;
  status: string;
  status_fa: string;
  status_note: string | null;
  evaluated_at: string | null;
} | null;

type ExamRow = {
  id: number;
  kind: string;
  kind_fa: string;
  title_fa: string;
  subject: string | null;
  school_year: string;
  status: string;
  due_at: string | null;
  percent: number | null;
  qualification: QualBrief;
};

type QualHistoryRow = {
  id: number;
  subject: string;
  subject_fa: string;
  school_year: string;
  school_name: string | null;
  status: string;
  status_fa: string;
  subject_percent: number | null;
  management_percent: number | null;
  status_note: string | null;
  interventions_count: number;
};

type Assessments = {
  school_year: string;
  exams: ExamRow[];
  qualifications: QualHistoryRow[];
};

type ExamItem = { id: number; order: number; body: string; options: Record<string, string>; points: number };

type Questions = {
  exam: { id: number; kind: string; kind_fa: string; title_fa: string; subject: string | null; due_at: string | null };
  items: ExamItem[];
};

type SubmitResult = { percent: number; status: string; qualification_status: string | null };

function qualBadge(status: string | null | undefined, statusFa?: string | null) {
  if (!status) return null;
  return (
    <Badge tone={QUALIFICATION_STATUS_TONE[status] ?? "neutral"} dot>
      {statusFa || (QUALIFICATION_STATUS_FA[status] ?? status)}
    </Badge>
  );
}

function percentTone(p: number | null): "success" | "warning" | "danger" | "primary" {
  if (p === null) return "primary";
  return p >= 65 ? "success" : p >= 50 ? "warning" : "danger";
}

export function AssessmentSection() {
  const [data, setData] = useState<Assessments | null>(null);
  const [loading, setLoading] = useState(true);

  const [activeExam, setActiveExam] = useState<{ exam: ExamRow; items: ExamItem[] } | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [busyExamId, setBusyExamId] = useState<number | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SubmitResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api<Assessments>("/teacher/assessments"));
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در دریافت آزمون‌های صلاحیت", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function start(exam: ExamRow) {
    setBusyExamId(exam.id);
    setAnswers({});
    setResult(null);
    try {
      await api(`/teacher/assessments/${exam.id}/start`, { method: "POST" });
      const q = await api<Questions>(`/teacher/assessments/${exam.id}/questions`);
      setActiveExam({ exam, items: q.items });
    } catch (e) {
      // 409 = تکمیل‌شده/منقضی/ارسال‌شده — دلیل سرور فارسی است
      toast(e instanceof Error ? e.message : "خطا در شروع آزمون", "error");
      await load();
    } finally {
      setBusyExamId(null);
    }
  }

  const unanswered = activeExam ? activeExam.items.filter((it) => !answers[it.id]).length : 0;

  async function submit() {
    if (!activeExam) return;
    setConfirmOpen(false);
    setSubmitting(true);
    try {
      const payload = activeExam.items
        .filter((it) => answers[it.id])
        .map((it) => ({ item_id: it.id, option: answers[it.id] }));
      const res = await api<SubmitResult>(`/teacher/assessments/${activeExam.exam.id}/submit`, {
        method: "POST",
        json: { answers: payload },
      });
      setResult(res);
      toast("پاسخ‌ها ثبت و تصحیح شد.", "success");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ارسال آزمون", "error");
      await load();
      setActiveExam(null);
    } finally {
      setSubmitting(false);
    }
  }

  function backToList() {
    setResult(null);
    setActiveExam(null);
    setAnswers({});
  }

  /* ---------------- نتیجه ---------------- */
  if (result && activeExam) {
    const qStatus = result.qualification_status;
    return (
      <div className="mx-auto max-w-2xl space-y-5">
        <Card className="animate-fade-in-up space-y-6 p-8 text-center">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-brand-gradient-soft text-primary-600">
            <IconCheckCircle size={26} />
          </span>
          <div className="grid place-items-center">
            <RadialProgress
              value={result.percent}
              size={168}
              thickness={14}
              color={result.percent >= 65 ? "#12b76a" : result.percent >= 50 ? "#f79009" : "#f04438"}
              format={(v) => `${fa(v, 1)}٪`}
              label="درصد این آزمون"
            />
          </div>
          <p className="text-sm font-bold text-ink">{activeExam.exam.title_fa}</p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Badge tone="primary">{activeExam.exam.kind_fa}</Badge>
            {qualBadge(qStatus) ?? (
              <Badge tone="neutral">در انتظار تصحیح آزمون دیگر — صلاحیت هنوز pending است</Badge>
            )}
          </div>
          <p className="mx-auto max-w-md text-xs leading-6 text-ink-muted">
            صلاحیت نهایی وقتی مشخص می‌شود که هر دو آزمون (دانش درس + مدیریت کلاس) تصحیح شده باشند؛ کمترین درصد دو آزمون ملاک است.
          </p>
          <Button onClick={backToList} icon={<IconTarget size={15} />}>
            بازگشت به فهرست آزمون‌ها
          </Button>
        </Card>
      </div>
    );
  }

  /* ---------------- در حال آزمون ---------------- */
  if (activeExam) {
    const { items, exam } = activeExam;
    return (
      <div className="space-y-5">
        <div className="sticky top-16 z-20 rounded-2xl border border-line bg-surface/95 p-4 shadow-soft backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-bold text-ink">{exam.title_fa}</p>
              <p className="text-[11px] text-ink-faint">{exam.kind_fa}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={backToList}>
              خروج موقت
            </Button>
          </div>
          <ProgressBar
            className="mt-3"
            value={items.length - unanswered}
            max={items.length}
            tone={unanswered === 0 ? "success" : "primary"}
            label="پیشرفت پاسخ‌گویی"
            showValue
          />
        </div>

        <div className="space-y-4">
          {items.map((it) => (
            <Card key={it.id} className="space-y-3">
              <div className="flex items-start gap-3">
                <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-xs font-bold text-primary-700">
                  {fa(it.order)}
                </span>
                <p className="text-sm font-semibold leading-8 text-ink">{it.body}</p>
              </div>
              <fieldset className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <legend className="sr-only">گزینه‌ها</legend>
                {Object.entries(it.options).map(([key, value]) => {
                  const selected = answers[it.id] === key;
                  return (
                    <label
                      key={key}
                      className={`flex cursor-pointer items-start gap-2.5 rounded-xl border px-3.5 py-3 text-right text-sm transition ${
                        selected
                          ? "border-primary-400 bg-primary-50 text-primary-800 shadow-soft"
                          : "border-line bg-surface text-ink-muted hover:border-primary-200 hover:bg-primary-50/40"
                      }`}
                    >
                      <input
                        type="radio"
                        name={`q-${it.id}`}
                        checked={selected}
                        onChange={() => setAnswers((prev) => ({ ...prev, [it.id]: key }))}
                        className="mt-1 h-4 w-4 shrink-0 border-line text-primary-600 focus:ring-primary-500/40"
                        aria-label={`گزینه ${OPTION_LETTER_FA[key] ?? key}`}
                      />
                      <span
                        className={`num grid h-6 w-6 shrink-0 place-items-center rounded-lg text-xs font-bold ${
                          selected ? "bg-primary-600 text-white" : "bg-slate-100 text-ink-muted"
                        }`}
                      >
                        {OPTION_LETTER_FA[key] ?? key}
                      </span>
                      <span className="leading-6">{value}</span>
                    </label>
                  );
                })}
              </fieldset>
            </Card>
          ))}
        </div>

        <div className="sticky bottom-4 rounded-2xl border border-line bg-surface/95 p-4 shadow-card backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="num text-xs text-ink-muted">
              {unanswered === 0 ? "همه سؤالات پاسخ داده شده ✓" : `${fa(unanswered)} سؤال بدون پاسخ`}
            </p>
            <Button onClick={() => setConfirmOpen(true)} loading={submitting} disabled={items.length === 0} icon={<IconSend size={15} />}>
              ارسال نهایی
            </Button>
          </div>
        </div>

        <Modal
          open={confirmOpen}
          onClose={() => setConfirmOpen(false)}
          title="ارسال نهایی آزمون"
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
                بازگشت به سؤالات
              </Button>
              <Button variant="success" loading={submitting} onClick={submit} icon={<IconCheckCircle size={15} />}>
                قطعاً ارسال کن
              </Button>
            </>
          }
        >
          {unanswered > 0 ? (
            <p className="leading-7">
              <b className="text-danger-600">{fa(unanswered)} سؤال</b> بدون پاسخ است؛ پاسخ‌های خالی غلط حساب می‌شوند. پس از ارسال، آزمون
              تکمیل‌شده و امکان ویرایش ندارد.
            </p>
          ) : (
            <p className="leading-7">همه {fa(activeExam.items.length)} سؤال پاسخ داده شده است. پس از ارسال آزمون تکمیل می‌شود.</p>
          )}
        </Modal>
      </div>
    );
  }

  /* ---------------- فهرست آزمون‌ها + تاریخچه ---------------- */
  const columns: Column<QualHistoryRow>[] = [
    { key: "subject", header: "درس", render: (row) => <span className="font-semibold text-ink">{row.subject_fa || subjectFa(row.subject)}</span> },
    { key: "year", header: "سال تحصیلی", align: "center", render: (row) => <span className="num text-xs">{row.school_year}</span> },
    { key: "school", header: "مدرسه", align: "center", render: (row) => <span className="text-xs">{row.school_name ?? "—"}</span> },
    {
      key: "status",
      header: "وضعیت صلاحیت",
      align: "center",
      render: (row) => (
        <Badge tone={QUALIFICATION_STATUS_TONE[row.status] ?? "neutral"} dot>
          {row.status_fa || (QUALIFICATION_STATUS_FA[row.status] ?? row.status)}
        </Badge>
      ),
    },
    {
      key: "percents",
      header: "درس / مدیریت کلاس",
      align: "center",
      render: (row) => (
        <span className="num text-xs font-semibold text-ink">
          {row.subject_percent !== null ? `${fa(row.subject_percent)}٪` : "—"}
          <span className="text-ink-faint"> / </span>
          {row.management_percent !== null ? `${fa(row.management_percent)}٪` : "—"}
        </span>
      ),
    },
    {
      key: "iv",
      header: "اقدامات",
      align: "center",
      render: (row) => <span className="num text-xs text-ink-faint">{fa(row.interventions_count)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      {loading && !data && (
        <div className="space-y-5">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {data && (
        <>
          <Section
            title={`آزمون‌های صلاحیت — سال ${data.school_year}`}
            subtitle="دو آزمون سالانه: سنجش دانش درس و سنجش مهارت مدیریت کلاس؛ کمترین درصد دو آزمون ملاک صلاحیت است."
          >
            {data.exams.length === 0 ? (
              <EmptyState
                icon={<IconGraduation size={26} />}
                title="آزمون صلاحیتی برای شما تخصیص نیافته"
                description="مدیر ناحیه آزمون‌های سال جاری را برای شما تخصیص می‌دهد."
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {data.exams.map((ex) => {
                  const done = ex.percent !== null || ex.status === "completed";
                  const closed = done || ex.status === "expired";
                  return (
                    <Card key={ex.id} className="space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                          <IconExam size={19} />
                        </span>
                        <div className="flex flex-wrap justify-end gap-1.5">
                          <Badge tone="neutral">{ex.kind_fa}</Badge>
                          <Badge
                            tone={
                              ex.status === "completed"
                                ? "success"
                                : ex.status === "in_progress"
                                  ? "info"
                                  : ex.status === "expired"
                                    ? "danger"
                                    : "primary"
                            }
                            dot
                          >
                            {EXAM_STATUS_FA[ex.status] ?? ex.status}
                          </Badge>
                        </div>
                      </div>
                      <div>
                        <p className="text-sm font-bold leading-6 text-ink">{ex.title_fa}</p>
                        <p className="num mt-1 text-[11px] text-ink-faint">
                          {ex.subject ? subjectFa(ex.subject) : "مدیریت کلاس"}
                          {ex.due_at ? ` · مهلت: ${new Date(ex.due_at).toLocaleDateString("fa-IR")}` : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                        <span className="flex flex-wrap items-center gap-1.5">
                          {qualBadge(ex.qualification?.status, ex.qualification?.status_fa) ?? (
                            <Badge tone="neutral">بدون رکورد صلاحیت</Badge>
                          )}
                        </span>
                        <span className="num text-xs font-bold text-ink">
                          {ex.percent !== null ? `${fa(ex.percent)}٪` : <span className="font-normal text-ink-faint">بدون نمره</span>}
                        </span>
                      </div>
                      <ProgressBar value={ex.percent ?? 0} size="sm" tone={percentTone(ex.percent)} />
                      {!closed ? (
                        <Button className="w-full" size="sm" loading={busyExamId === ex.id} onClick={() => start(ex)} icon={<IconSend size={15} />}>
                          {ex.status === "in_progress" ? "ادامه آزمون" : "شروع آزمون"}
                        </Button>
                      ) : (
                        <p className="text-center text-[11px] text-ink-faint">
                          {ex.status === "expired" ? "مهلت این آزمون به پایان رسیده است." : "این آزمون قبلاً ارسال شده است."}
                        </p>
                      )}
                    </Card>
                  );
                })}
              </div>
            )}
          </Section>

          <Section title="تاریخچه صلاحیت" subtitle="وضعیت و درصدهای ثبت‌شده برای سال جاری.">
            <DataTable
              columns={columns}
              rows={data.qualifications}
              keyOf={(r) => r.id}
              empty={<EmptyState compact title="رکورد صلاحیتی ثبت نشده" description="پس از تخصیص آزمون توسط ناحیه، رکورد اینجا ظاهر می‌شود." />}
            />
          </Section>

          <Alert variant="info" title="قاعده ارزیابی">
            صلاحیت وقتی مشخص می‌شود که هر دو آزمون تصحیح شده باشند: بالای حد قبول → «تأیید صلاحیت»، بین حد بحران و قبول → «دوره الزامی»،
            زیر حد بحران → «بحرانی» با اقدام اصلاحی ناحیه.
          </Alert>
        </>
      )}
    </div>
  );
}
