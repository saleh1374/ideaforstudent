"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, getToken, ExamSummary } from "@/lib/api";
import { EXAM_TYPE_FA, STATUS_FA, fa, subjectFa, gradeFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { SearchInput, Select } from "@/components/ui/forms";
import { SkeletonCard } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { LineChart } from "@/components/ui/charts";
import {
  IconExam,
  IconHome,
  IconSearch,
  IconSend,
  IconCheckCircle,
  IconTrend,
  IconTarget,
} from "@/components/ui/icons";

function fmtDate(v: string | null): string | null {
  if (!v) return null;
  try {
    return new Date(v.replace(" ", "T")).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return v;
  }
}

function fmtMs(ms: number): string {
  const total = Math.round(ms / 60000);
  if (total < 1) return "کمتر از یک دقیقه";
  return `${fa(total)} دقیقه`;
}

/* ——— تاریخچه تحلیلی آزمون (§7 + §13 «تحلیل و کارنامه») ——— */

type AttemptRow = {
  id: number;
  exam_id: number;
  exam_title: string;
  exam_type: string;
  subject: string | null;
  status: string;
  in_progress: boolean;
  started_at: string | null;
  submitted_at: string | null;
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
  topics: { topic_id: number; status: string; mastery: number | null }[];
  index: number;
};

type HistoryData = {
  attempts: AttemptRow[];
  trend: { attempt_id: number; percent: number; date: string | null; label: string }[];
  summary: {
    attempts: number;
    graded: number;
    avg_percent: number | null;
    best_percent: number | null;
    last_delta: number | null;
    total_time_ms: number;
    errors_recorded: number;
    errors_resolved: number;
  };
};

function DeltaBadge({ delta }: { delta: number | null }) {
  if (delta === null) return <Badge tone="neutral">تلاش اول</Badge>;
  const up = delta >= 0;
  return (
    <Badge tone={up ? "success" : "danger"} dot>
      {up ? "▲" : "▼"} {fa(Math.abs(delta), 1)}٪ نسبت به تلاش قبل
    </Badge>
  );
}

function HistoryView({ data, loading, error }: { data: HistoryData | null; loading: boolean; error: string }) {
  if (error) return <Alert variant="danger" title="خطا در دریافت تاریخچه">{error}</Alert>;
  if (loading && !data) {
    return (
      <div className="space-y-3">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (!data) return null;

  const s = data.summary;
  const trendReady = data.trend.length >= 2;

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="تلاش‌های ثبت‌شده" value={fa(s.attempts)} tone="primary" icon={<IconExam size={20} />} hint={`${fa(s.graded)} نمره‌دار`} />
        <StatCard
          label="میانگین درصد"
          value={s.avg_percent === null ? "—" : `${fa(s.avg_percent, 1)}٪`}
          tone="accent"
          icon={<IconTarget size={20} />}
          hint={`بهترین: ${s.best_percent === null ? "—" : `${fa(s.best_percent, 1)}٪`}`}
        />
        <StatCard
          label="آخرین تغییر"
          value={s.last_delta === null ? "—" : `${s.last_delta >= 0 ? "+" : "−"}${fa(Math.abs(s.last_delta), 1)}٪`}
          tone={s.last_delta === null ? "sky" : s.last_delta >= 0 ? "success" : "danger"}
          icon={<IconTrend size={20} />}
          hint="نسبت به تلاش قبلی همان آزمون"
        />
        <StatCard
          label="خطاهای رفع‌شده"
          value={
            <span>
              {fa(s.errors_resolved)} <span className="text-base font-bold text-ink-faint">از {fa(s.errors_recorded)}</span>
            </span>
          }
          tone="warning"
          icon={<IconCheckCircle size={20} />}
          hint={`زمان پاسخ: ${fmtMs(s.total_time_ms)}`}
        />
      </section>

      {/* ——— روند نمره ——— */}
      <Card>
        <CardHeader
          title="روند نمره در تلاش‌ها"
          subtitle="هر نقطه یک تلاش آزمون است؛ مقایسه با تلاش قبلی همان آزمون در کارت پایین آمده."
          icon={<IconTrend size={17} />}
        />
        {trendReady ? (
          <LineChart
            id="exam-trend"
            points={data.trend.map((t) => t.percent)}
            labels={data.trend.map((t) => t.label)}
            format={(v) => `${fa(v, 1)}٪`}
            height={210}
          />
        ) : (
          <EmptyState
            compact
            icon={<IconTrend size={24} />}
            title="برای نمودار دست‌کم دو تلاش لازم است"
            description="یک آزمون را دوباره بده تا رشدت را ببینی."
          />
        )}
      </Card>

      {/* ——— فهرست تلاش‌ها ——— */}
      <section className="space-y-3">
        <h2 className="text-sm font-bold text-ink">تاریخچه تلاش‌ها ({fa(data.attempts.length)})</h2>

        {data.attempts.length === 0 && (
          <EmptyState
            icon={<IconExam size={26} />}
            title="هنوز آزمونی ثبت نکرده‌ای"
            description="بعد از اولین آزمون، نمره‌ها، ترکیب پاسخ‌ها و روند یادگیری‌ات اینجا جمع می‌شود."
            action={
              <ButtonLink href="/student/exams" size="sm" variant="soft">
                رفتن به آزمون‌ها
              </ButtonLink>
            }
          />
        )}

        {data.attempts
          .slice()
          .reverse()
          .map((a) => (
            <Card key={a.id} className="flex flex-col gap-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="primary">{EXAM_TYPE_FA[a.exam_type] ?? a.exam_type}</Badge>
                    {a.subject && <Badge tone="neutral">{subjectFa(a.subject)}</Badge>}
                    <DeltaBadge delta={a.delta_percent} />
                    {a.in_progress && <Badge tone="warning" dot>در حال برگزاری</Badge>}
                  </div>
                  <h3 className="mt-2 text-sm font-bold text-ink">
                    <Link href={`/student/exams/${a.exam_id}`} className="transition hover:text-primary-600">
                      {a.exam_title}
                    </Link>
                  </h3>
                  <p className="mt-1 num text-[11px] text-ink-faint">
                    تلاش {fa(a.index)} · {fmtDate(a.submitted_at) ?? fmtDate(a.started_at)}
                  </p>
                </div>
                <div className="text-left">
                  <p className="num text-2xl font-extrabold text-ink">
                    {a.percent === null ? "—" : `${fa(a.percent, 1)}٪`}
                  </p>
                  {a.raw_score !== null && (
                    <p className="num text-[11px] text-ink-faint">نمره {fa(a.raw_score, 2)}</p>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-muted sm:grid-cols-4">
                <span>
                  صحیح: <b className="text-success-600 num">{fa(a.correct)}</b> · غلط:{" "}
                  <b className="text-danger-600 num">{fa(a.wrong)}</b> · نزده: <b className="num">{fa(a.unanswered)}</b>
                </span>
                <span>
                  زمان: <b className="num">{fmtMs(a.time_spent_ms)}</b>
                </span>
                <span>
                  نمره منفی:{" "}
                  <b className="num">
                    {a.negative_marking.applied ? `${fa(a.negative_marking.penalty, 2)} (k=${fa(a.negative_marking.k, 2)})` : "غیرفعال"}
                  </b>
                </span>
                <span>
                  خطاها: <b className="num">{fa(a.errors_recorded)}</b> · رفع‌شده:{" "}
                  <b className="num">{fa(a.errors_resolved)}</b>
                </span>
              </div>

              {a.topics.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-semibold text-ink-muted">تسط مباحث:</span>
                  {a.topics.map((t) => (
                    <Badge key={t.topic_id} tone={statusTone(t.status)}>
                      {STATUS_FA[t.status] ?? t.status}
                      {t.mastery !== null && <span className="num mr-1 font-normal">{fa(t.mastery, 0)}٪</span>}
                    </Badge>
                  ))}
                </div>
              )}

              <div className="flex justify-end">
                <ButtonLink href={`/student/exams/attempts/${a.id}`} size="sm" variant="soft" icon={<IconSearch size={14} />}>
                  مرور سؤال‌ها و تحلیل
                </ButtonLink>
              </div>
            </Card>
          ))}
      </section>
    </div>
  );
}

export default function ExamsPage() {
  const [tab, setTab] = useState("exams");
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  const [history, setHistory] = useState<HistoryData | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ exams: ExamSummary[] }>("/student/exams")
      .then((d) => setExams(d.exams))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    api<HistoryData>("/student/exam-history")
      .then(setHistory)
      .catch((e) => setHistoryError(e.message))
      .finally(() => setHistoryLoading(false));
  }, []);

  const types = useMemo(() => Array.from(new Set(exams.map((e) => e.type))), [exams]);

  const visible = useMemo(
    () =>
      exams.filter(
        (e) => (typeFilter === "all" || e.type === typeFilter) && (query.trim() === "" || e.title.includes(query.trim()))
      ),
    [exams, query, typeFilter]
  );

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="آزمون‌ها"
          description="پاسخ‌ها و زمان پاسخ ثبت می‌شود تا تحلیل خطا و بازآزمون ترمیمی ساخته شود؛ تاریخچه هم روند نمره و علت خطاها را نشان می‌دهد."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "آزمون‌ها" }]}
          badge={
            <Tabs
              items={[
                { key: "exams", label: "آزمون‌های پیش رو", count: exams.length },
                { key: "history", label: "تاریخچه و تحلیل", count: history?.attempts.length ?? 0 },
              ]}
              value={tab}
              onChange={setTab}
            />
          }
          actions={
            <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
              خانه
            </ButtonLink>
          }
        />

        {tab === "history" && <HistoryView data={history} loading={historyLoading} error={historyError} />}

        {tab === "exams" && (
          <>
            {error && <Alert variant="danger" title="خطا در دریافت آزمون‌ها">{error}</Alert>}

            {!loading && !error && (
              <>
                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <StatCard label="کل آزمون‌ها" value={fa(exams.length)} tone="primary" icon={<IconExam size={20} />} />
                  <StatCard label="در دسترس" value={fa(visible.length)} tone="accent" icon={<IconSend size={20} />} hint="با فیلتر فعلی" />
                  <StatCard
                    label="مجموع سؤالات"
                    value={fa(exams.reduce((s, e) => s + e.item_count, 0))}
                    tone="sky"
                    icon={<IconExam size={20} />}
                  />
                  <StatCard label="انواع آزمون" value={fa(types.length)} tone="success" icon={<IconExam size={20} />} />
                </section>

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <SearchInput value={query} onChange={setQuery} placeholder="جستجوی عنوان آزمون…" className="w-full max-w-sm" />
                  <Select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="w-full sm:w-52">
                    <option value="all">همه انواع</option>
                    {types.map((t) => (
                      <option key={t} value={t}>
                        {EXAM_TYPE_FA[t] ?? t}
                      </option>
                    ))}
                  </Select>
                </div>

                {visible.length === 0 && !loading && (
                  <EmptyState
                    icon={<IconSearch size={26} />}
                    title="آزمونی با این فیلترها نیست"
                    description="فیلتر را تغییر بده یا صبر کن تا آزمون جدید منتشر شود."
                    action={
                      <Button
                        type="button"
                        variant="soft"
                        size="sm"
                        onClick={() => {
                          setQuery("");
                          setTypeFilter("all");
                        }}
                      >
                        حذف فیلترها
                      </Button>
                    }
                  />
                )}

                <div className="grid gap-4 md:grid-cols-2">
                  {visible.map((e) => {
                    const opens = fmtDate(e.opens_at);
                    const closes = fmtDate(e.closes_at);
                    return (
                      <Card key={e.id} hover className="flex flex-col gap-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge tone="primary">{EXAM_TYPE_FA[e.type] ?? e.type}</Badge>
                              <Badge tone="neutral">{subjectFa(e.subject)}</Badge>
                            </div>
                            <h3 className="mt-2 text-sm font-bold text-ink">{e.title}</h3>
                          </div>
                          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                            <IconExam size={19} />
                          </span>
                        </div>

                        <div className="mt-auto space-y-1.5 rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-muted">
                          <p className="num">{fa(e.item_count)} سؤال · {gradeFa(e.grade)}</p>
                          {opens && <p>باز شدن: {opens}</p>}
                          {closes && <p>بسته شدن: {closes}</p>}
                        </div>

                        <ButtonLink href={`/student/exams/${e.id}`} size="sm" className="w-full" icon={<IconSend size={14} />}>
                          شروع آزمون
                        </ButtonLink>
                      </Card>
                    );
                  })}
                </div>
              </>
            )}

            {loading && (
              <div className="grid gap-4 md:grid-cols-2">
                <SkeletonCard />
                <SkeletonCard />
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
