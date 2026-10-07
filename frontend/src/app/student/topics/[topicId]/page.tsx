"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, getToken } from "@/lib/api";
import { STATUS_FA, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Textarea } from "@/components/ui/forms";
import { ProgressBar } from "@/components/ui/progress";
import { HorizontalBars } from "@/components/ui/charts";
import { SkeletonCard } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconArrowLeft,
  IconBook,
  IconCheckCircle,
  IconChat,
  IconExam,
  IconHome,
  IconSend,
  IconSparkles,
  IconTarget,
} from "@/components/ui/icons";

/* ——— اشکال خروجی GET /student/topics/{id}/package (بستهٔ محتوایی §3.4) ——— */

type Lesson = { key: string; title_fa: string; ready: boolean; body: string | null; note_fa: string };

type KeyPoint = { title_fa: string; skill_id: number };

type WorkedExample = {
  item_id: number;
  body: string;
  options: Record<string, string>;
  correct_option: string;
  difficulty: string | null;
  difficulty_fa: string | null;
  why_wrong: { option: string; cause: string; cause_fa: string }[];
  steps_fa: string[];
};

type PracticeItem = {
  item_id: number;
  body: string;
  options: Record<string, string>;
  difficulty: string | null;
  difficulty_fa: string | null;
  last_result: { correct: boolean; selected: string | null } | null;
};

type Prerequisite = { topic_id: number; title: string; mastery: number | null; status: string };

type Resource = { key: string; title_fa: string; href?: string; detail_fa: string };

type QuestionRow = { id: number; body: string; status: string; created_at: string; answered_at?: string | null };

type Package = {
  topic: {
    id: number;
    title: string;
    chapter: string | null;
    book: string | null;
    subject: string | null;
    period_id: number | null;
    blueprint_weight: number | null;
    content_status: string;
    state: { mastery: number | null; status: string };
  };
  lessons: Lesson[];
  key_points: KeyPoint[];
  worked_examples: WorkedExample[];
  common_mistakes: { by_cause: { cause: string; cause_fa: string; count: number; share: number }[]; note_fa: string };
  practice: { items: PracticeItem[]; note_fa: string };
  prerequisites: Prerequisite[];
  resources: Resource[];
  minicheck: { item_ids: number[]; total: number; pass_ratio: number; task_id: number | null; note_fa: string };
  study: { studied: boolean; note_fa: string };
  my_questions: QuestionRow[];
};

type MinicheckResult = {
  passed: boolean;
  correct: number;
  total: number;
  task_id: number | null;
  message_fa: string;
};

const DIFFICULTY_FA: Record<string, string> = { easy: "ساده", medium: "متوسط", hard: "دشوار" };

const QUESTION_STATUS_FA: Record<string, string> = { sent: "ارسال‌شده", answered: "پاسخ داده شد" };

function faDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}

export default function TopicPage() {
  const params = useParams<{ topicId: string }>();
  const topicId = Number(params.topicId);

  const [pkg, setPkg] = useState<Package | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [mcAnswers, setMcAnswers] = useState<Record<number, string>>({});
  const [mcResult, setMcResult] = useState<MinicheckResult | null>(null);
  const [mcBusy, setMcBusy] = useState(false);

  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const d = await api<Package>(`/student/topics/${topicId}/package`);
      setPkg(d);
      setMcAnswers({});
      setMcResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicId]);

  /* سؤال‌های آزمونک = همان چند سؤال اولِ تمرین پله‌ای (minicheck.item_ids) */
  const minicheckItems = useMemo(() => {
    if (!pkg) return [];
    const byId = new Map(pkg.practice.items.map((i) => [i.item_id, i]));
    return pkg.minicheck.item_ids
      .map((id) => byId.get(id))
      .filter((x): x is PracticeItem => Boolean(x));
  }, [pkg]);

  const mcAnswered = minicheckItems.filter((q) => mcAnswers[q.item_id]).length;

  /** POST /student/topics/{id}/minicheck — { answers: [{item_id, selected}] } */
  async function submitMinicheck() {
    if (mcBusy || minicheckItems.length === 0) return;
    setMcBusy(true);
    try {
      const res = await api<MinicheckResult>(`/student/topics/${topicId}/minicheck`, {
        method: "POST",
        json: {
          answers: Object.entries(mcAnswers).map(([id, selected]) => ({ item_id: Number(id), selected })),
        },
      });
      setMcResult(res);
      toast(res.message_fa, res.passed ? "success" : "info");
      if (res.passed) {
        setPkg((prev) =>
          prev
            ? { ...prev, study: { ...prev.study, studied: true, note_fa: "مطالعه‌شده ✓ — آزمونک را گذرانده‌اید." } }
            : prev
        );
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ثبت آزمونک", "error");
    } finally {
      setMcBusy(false);
    }
  }

  /** POST /student/topics/{id}/ask-teacher — { body: "متن پرسش" } */
  async function sendQuestion() {
    const body = question.trim();
    if (!body || asking) return;
    setAsking(true);
    try {
      const res = await api<{ ok: boolean; question: QuestionRow; message_fa: string }>(
        `/student/topics/${topicId}/ask-teacher`,
        { method: "POST", json: { body } }
      );
      toast(res.message_fa, "success");
      setQuestion("");
      setPkg((prev) => (prev ? { ...prev, my_questions: [res.question, ...prev.my_questions] } : prev));
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ارسال پرسش", "error");
    } finally {
      setAsking(false);
    }
  }

  /* ——— loading / error ——— */
  if (loading && !pkg) {
    return (
      <AppShell>
        <div className="mx-auto max-w-4xl space-y-5">
          <PageHeader title="در حال بارگذاری مبحث…" crumbs={[{ label: "دانشیار" }, { label: "مبحث" }]} />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </AppShell>
    );
  }

  if (error && !pkg) {
    return (
      <AppShell>
        <div className="mx-auto max-w-4xl space-y-5">
          <PageHeader
            title="بستهٔ محتوایی مبحث"
            crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "کتاب‌های من", href: "/student/books" }]}
          />
          <Alert variant="danger" title="خطا در دریافت مبحث">
            {error}
          </Alert>
          <div className="flex gap-2">
            <Button onClick={load}>تلاش دوباره</Button>
            <ButtonLink href="/student/books" variant="ghost">
              بازگشت به کتاب‌ها
            </ButtonLink>
          </div>
        </div>
      </AppShell>
    );
  }

  if (!pkg) return null;

  const t = pkg.topic;

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl space-y-6">
        <PageHeader
          title={t.title}
          description={[t.book, t.chapter].filter(Boolean).join(" · ") || undefined}
          crumbs={[
            { label: "دانشیار" },
            { label: "دانش‌آموز", href: "/student" },
            { label: "کتاب‌های من", href: "/student/books" },
            { label: t.title },
          ]}
          badge={
            <>
              <Badge tone={statusTone(t.state.status)} dot>
                {STATUS_FA[t.state.status] ?? t.state.status}
              </Badge>
              <Badge tone="primary">تسط {t.state.mastery !== null ? `${fa(t.state.mastery)}٪` : "—"}</Badge>
            </>
          }
          actions={
            <ButtonLink href="/student/books" variant="ghost" size="sm" icon={<IconBook size={15} />}>
              کتاب‌های من
            </ButtonLink>
          }
        />

        {error && <Alert variant="warning">بروزرسانی ناقص ماند: {error}</Alert>}

        {/* ——— وضعیت مطالعه ——— */}        <Card variant={pkg.study.studied ? "brand" : "sunken"} className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span
              className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${
                pkg.study.studied ? "bg-success-50 text-success-600" : "bg-warning-50 text-warning-600"
              }`}
            >
              {pkg.study.studied ? <IconCheckCircle size={19} /> : <IconExam size={19} />}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-bold text-ink">
                {pkg.study.studied ? "این مبحث مطالعه شده ✓" : "مطالعهٔ این مبحث هنوز ثبت نشده"}
              </p>
              <p className="mt-0.5 text-[11px] leading-5 text-ink-muted">{pkg.study.note_fa}</p>
            </div>
          </div>
          <Badge tone={pkg.study.studied ? "success" : "warning"}>{pkg.study.studied ? "مطالعه شد" : "آزمونک مانده"}</Badge>
        </Card>

        {/* ——— درس‌نامه + نکات کلیدی ——— */}
        <Section title="درس‌نامه و نکات کلیدی" subtitle="دو سطح ساده و تکمیلی؛ نکات از مهارت‌های همین مبحث ساخته شده است.">
          <div className="grid gap-4 sm:grid-cols-2">
            {pkg.lessons.map((l) => (
              <Card key={l.key} className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-bold text-ink">{l.title_fa}</h3>
                  <Badge tone={l.ready ? "success" : "warning"}>{l.ready ? "منتشرشده" : "در انتظار انتشار"}</Badge>
                </div>
                {l.body ? (
                  <p className="text-xs leading-7 text-ink-muted">{l.body}</p>
                ) : (
                  <p className="rounded-lg bg-surface-sunken px-3 py-2 text-[11px] leading-6 text-ink-faint">{l.note_fa}</p>
                )}
                {l.body && <p className="text-[11px] leading-5 text-ink-faint">{l.note_fa}</p>}
              </Card>
            ))}
          </div>

          {pkg.key_points.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {pkg.key_points.map((k, i) => (
                <span
                  key={`${k.skill_id}-${i}`}
                  className="rounded-lg bg-brand-gradient-soft px-3 py-2 text-xs font-semibold text-primary-700"
                >
                  {k.title_fa}
                </span>
              ))}
            </div>
          )}
        </Section>

        {/* ——— مثال حل‌شده + اشتباهات رایج ——— */}
        <Section title="مثال حل‌شده و اشتباهات رایج" subtitle="مثال‌ها را با دلیل غلط بودن گزینه‌ها مقایسه کن.">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-4">
              {pkg.worked_examples.length === 0 && (
                <EmptyState compact title="مثال حل‌شده‌ای ثبت نشده" description="به‌محض انتشار محتوا، مثال‌ها اینجا می‌آیند." />
              )}
              {pkg.worked_examples.map((ex, i) => (
                <Card key={ex.item_id} className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-xs font-bold text-ink">مثال {fa(i + 1)}</h3>
                    <Badge tone="neutral">{ex.difficulty_fa ?? DIFFICULTY_FA[ex.difficulty ?? ""] ?? "—"}</Badge>
                  </div>
                  <p className="text-sm font-semibold leading-7 text-ink">{ex.body}</p>
                  <ul className="space-y-1.5">
                    {Object.entries(ex.options).map(([k, v]) => (
                      <li
                        key={k}
                        className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-6 ${
                          k === ex.correct_option ? "bg-success-50 font-semibold text-success-700" : "bg-surface-sunken text-ink-muted"
                        }`}
                      >
                        <span className="num grid h-5 w-5 shrink-0 place-items-center rounded-md bg-white/70 text-[11px] font-bold">
                          {k}
                        </span>
                        <span>{v}</span>
                      </li>
                    ))}
                  </ul>
                  {ex.why_wrong.length > 0 && (
                    <div>
                      <p className="mb-1 text-[11px] font-bold text-ink-muted">چرا بقیهٔ گزینه‌ها غلط‌اند؟</p>
                      <ul className="space-y-1 text-[11px] leading-6 text-ink-muted">
                        {ex.why_wrong.map((w) => (
                          <li key={w.option}>
                            گزینهٔ {w.option}: {w.cause_fa}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div>
                    <p className="mb-1 text-[11px] font-bold text-ink-muted">مراحل حل</p>
                    <ol className="space-y-1 text-[11px] leading-6 text-ink-muted">
                      {ex.steps_fa.map((s, i2) => (
                        <li key={i2}>
                          {fa(i2 + 1)}. {s}
                        </li>
                      ))}
                    </ol>
                  </div>
                </Card>
              ))}
            </div>

            <Card className="h-fit">
              <CardHeader title="اشتباهات رایج این مبحث" subtitle="بر اساس خطاهای واقعی دانش‌آموزان" icon={<IconTarget size={17} />} />
              {pkg.common_mistakes.by_cause.length === 0 ? (
                <EmptyState compact title="هنوز خطایی ثبت نشده" description="با شروع آزمون‌ها این بخش پر می‌شود." />
              ) : (
                <HorizontalBars
                  data={pkg.common_mistakes.by_cause.map((c) => ({ label: `${c.cause_fa} (${fa(c.share, 1)}٪)`, value: c.count }))}
                  showTotal
                />
              )}
              <p className="mt-3 text-[11px] leading-5 text-ink-faint">{pkg.common_mistakes.note_fa}</p>
            </Card>
          </div>
        </Section>

        {/* ——— تمرین پله‌ای ——— */}
        <Section title="تمرین پله‌ای" subtitle={pkg.practice.note_fa}>
          <Card className="space-y-3">
            {pkg.practice.items.length === 0 ? (
              <EmptyState compact title="سؤالی برای این مبحث نیست" description="به‌محض افزوده شدن سؤال، تمرین‌ها اینجا ظاهر می‌شوند." />
            ) : (
              pkg.practice.items.map((q, i) => (
                <div key={q.item_id} className="flex items-start gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                  <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-[11px] font-bold text-primary-700">
                    {fa(i + 1)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold leading-6 text-ink">{q.body}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <Badge tone="neutral">{q.difficulty_fa ?? DIFFICULTY_FA[q.difficulty ?? ""] ?? "—"}</Badge>
                      {q.last_result && (
                        <Badge tone={q.last_result.correct ? "success" : "danger"}>
                          {q.last_result.correct ? "آخرین تلاش: درست" : "آخرین تلاش: غلط"}
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </Card>
        </Section>

        {/* ——— آزمونک ——— */}
        <Section title="آزمونک مبحث" subtitle={pkg.minicheck.note_fa}>
          <Card className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Badge tone="primary">
                {fa(minicheckItems.length)} سؤال · قبول از {fa(Math.round(pkg.minicheck.pass_ratio * 100))}٪
              </Badge>
              <Badge tone={pkg.study.studied ? "success" : "neutral"}>
                {pkg.study.studied ? "مطالعه شد ✓" : "بدون قبول، تیک درس نمی‌خورد"}
              </Badge>
            </div>

            {minicheckItems.length === 0 ? (
              <EmptyState
                compact
                title="آزمونکی برای این مبحث موجود نیست"
                description="سؤال فعالی برای ساخت آزمونک ثبت نشده است؛ تمرین پله‌ای را انجام بده."
              />
            ) : (
              <>
                <div className="space-y-4">
                  {minicheckItems.map((q, i) => (
                    <div key={q.item_id} className="space-y-2">
                      <div className="flex items-start gap-2.5">
                        <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-[11px] font-bold text-primary-700">
                          {fa(i + 1)}
                        </span>
                        <p className="text-sm font-semibold leading-7 text-ink">{q.body}</p>
                      </div>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {Object.entries(q.options).map(([k, v]) => {
                          const selected = mcAnswers[q.item_id] === k;
                          return (
                            <button
                              key={k}
                              type="button"
                              onClick={() => setMcAnswers((prev) => ({ ...prev, [q.item_id]: k }))}
                              className={`flex items-start gap-2 rounded-xl border px-3.5 py-3 text-right text-sm transition ${
                                selected
                                  ? "border-primary-400 bg-primary-50 text-primary-800 shadow-soft"
                                  : "border-line bg-surface text-ink-muted hover:border-primary-200 hover:bg-primary-50/40"
                              }`}
                            >
                              <span
                                className={`num grid h-6 w-6 shrink-0 place-items-center rounded-lg text-xs font-bold ${
                                  selected ? "bg-primary-600 text-white" : "bg-slate-100 text-ink-muted"
                                }`}
                              >
                                {k}
                              </span>
                              <span className="leading-6">{v}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                  <p className="text-xs text-ink-muted">
                    {mcAnswered === minicheckItems.length
                      ? "همهٔ سؤال‌ها پاسخ داده شده ✓"
                      : `${fa(mcAnswered)} از ${fa(minicheckItems.length)} پاسخ داده شده`}
                  </p>
                  <Button
                    size="sm"
                    onClick={submitMinicheck}
                    loading={mcBusy}
                    disabled={mcAnswered < minicheckItems.length}
                    icon={<IconCheckCircle size={15} />}
                  >
                    ثبت آزمونک
                  </Button>
                </div>

                {mcResult && (
                  <Alert variant={mcResult.passed ? "success" : "warning"} title={mcResult.passed ? "آزمونک قبول شد" : "هنوز کافی نیست"}>
                    <p>{mcResult.message_fa}</p>
                    <p className="mt-1 text-[11px] opacity-80">
                      نتیجه: {fa(mcResult.correct)} از {fa(mcResult.total)} درست
                    </p>
                  </Alert>
                )}
              </>
            )}
          </Card>
        </Section>

        {/* ——— پیش‌نیازها + پرسش از دبیر + منابع ——— */}
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="h-fit space-y-3">
            <CardHeader title="پیش‌نیازها" subtitle="وضعیت تسط هر پیش‌نیاز — برای مرور" icon={<IconTarget size={17} />} />
            {pkg.prerequisites.length === 0 ? (
              <EmptyState compact title="پیش‌نیازی ثبت نشده" description="این مبحث پیش‌نیاز قبلی ندارد." />
            ) : (
              <ul className="space-y-2">
                {pkg.prerequisites.map((p) => (
                  <li key={p.topic_id}>
                    <Link
                      href={`/student/topics/${p.topic_id}`}
                      className="flex items-center justify-between gap-3 rounded-xl bg-surface-sunken px-3.5 py-2.5 transition hover:bg-primary-50"
                    >
                      <span className="truncate text-xs font-semibold text-ink">{p.title}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="num text-[11px] font-bold text-ink-muted">
                          {p.mastery !== null ? `${fa(p.mastery)}٪` : "—"}
                        </span>
                        <Badge tone={statusTone(p.status)}>{STATUS_FA[p.status] ?? p.status}</Badge>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            {pkg.resources.length > 0 && (
              <div className="mt-2 border-t border-line pt-3">
                <p className="mb-2 text-[11px] font-bold text-ink-muted">منابع کمکی</p>
                <ul className="space-y-2">
                  {pkg.resources.map((r) => {
                    const inner = (
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-primary-600">
                          {r.key === "errors" ? <IconTarget size={15} /> : r.key === "teacher" ? <IconChat size={15} /> : <IconSparkles size={15} />}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-ink">{r.title_fa}</p>
                          <p className="truncate text-[11px] text-ink-faint">{r.detail_fa}</p>
                        </div>
                      </div>
                    );
                    return (
                      <li key={r.key}>
                        {r.href ? (
                          <Link
                            href={r.href}
                            className="flex items-center justify-between gap-2 rounded-xl bg-surface-sunken px-3 py-2.5 transition hover:bg-primary-50"
                          >
                            {inner}
                            <IconArrowLeft size={15} className="shrink-0 text-ink-faint" />
                          </Link>
                        ) : (
                          <div className="rounded-xl bg-surface-sunken px-3 py-2.5">{inner}</div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </Card>

          <Card className="h-fit space-y-4">
            <CardHeader
              title="پرسش از دبیر"
              subtitle="پرسش نوشتاری دربارهٔ همین مبحث — وارد کارتابل دبیر کالس می‌شود (پاسخ هدف: ۴۸ ساعت)."
              icon={<IconChat size={17} />}
            />
            <Field label="متن پرسش" required hint="کوتاه و مشخص بنویس تا پاسخ سریع‌تر برسد.">
              <Textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="مثلاً: در تمرین ۳ چرا از روش دوم استفاده نمی‌کنیم؟"
                maxLength={2000}
              />
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="num text-[11px] text-ink-faint">{fa(question.trim().length)} از {fa(2000)} نویسه</p>
              <Button
                size="sm"
                onClick={sendQuestion}
                loading={asking}
                disabled={question.trim().length === 0}
                icon={<IconSend size={14} />}
              >
                ارسال پرسش
              </Button>
            </div>

            {pkg.my_questions.length > 0 && (
              <div className="border-t border-line pt-3">
                <p className="mb-2 text-[11px] font-bold text-ink-muted">پرسش‌های من از دبیر ({fa(pkg.my_questions.length)})</p>
                <ul className="space-y-2">
                  {pkg.my_questions.map((q) => (
                    <li key={q.id} className="rounded-xl bg-surface-sunken px-3.5 py-2.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Badge tone={q.status === "answered" ? "success" : "info"}>
                          {QUESTION_STATUS_FA[q.status] ?? q.status}
                        </Badge>
                        <span className="num text-[11px] text-ink-faint">{faDate(q.created_at)}</span>
                      </div>
                      <p className="mt-1 text-xs leading-6 text-ink">{q.body}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        </div>

        {/* ——— نوار تسلط ——— */}
        <Card className="space-y-2">
          <ProgressBar
            value={t.state.mastery ?? 0}
            tone={statusTone(t.state.status) === "success" ? "success" : "primary"}
            label={`تسط این مبحث: ${t.state.mastery !== null ? `${fa(t.state.mastery)}٪` : "بدون داده"}`}
            showValue
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-ink-faint">
              {t.book && t.chapter ? `${t.book} · ${t.chapter}` : t.book ?? "—"}
            </p>
            <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={14} />}>
              خانه
            </ButtonLink>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
