"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { fa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Select } from "@/components/ui/forms";
import { StatCard } from "@/components/ui/stat";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { BarChart } from "@/components/ui/charts";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconChart, IconCheckCircle, IconClock, IconExam, IconTarget } from "@/components/ui/icons";

/* ------------------------------- انواع سرور ------------------------------- */

type ExamOption = {
  id: number;
  title_fa: string;
  type_fa: string;
  status: string;
  item_count: number;
  attempts_count: number;
};

type ItemRow = {
  exam_item_id: number;
  item_id: number;
  order: number;
  body: string;
  topic_id: number;
  topic_title: string;
  difficulty: string;
  responses_count: number;
  correct_pct: number;
  empirical_difficulty: number;
  prior_difficulty: number;
  discrimination: number | null;
  avg_time_ms: number | null;
  top_wrong_option: string | null;
  top_wrong_pct: number | null;
  misconception: string | null;
  comment_fa: string;
  needs_review: boolean;
  review_reasons: string[];
};

type Analysis = {
  ok: boolean;
  exam_id: number;
  attempts: number;
  items: ItemRow[];
  flagged_count: number;
  thresholds: {
    discrimination_min: number;
    difficulty_gap: number;
    time_zscore_max: number;
  };
  note_fa: string | null;
};

/* ------------------------------- ثابت‌های محلی ------------------------------- */

const DIFFICULTY_FA: Record<string, string> = { easy: "آسان", medium: "متوسط", hard: "سخت" };

const REVIEW_TONE: Tone = "danger";

function errOf(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.detail ?? e.message;
  if (e instanceof Error) return e.message;
  return fallback;
}

/** میلی‌ثانیه → «۳٫۴ ثانیه» */
const seconds = (ms: number | null): string => (ms === null ? "—" : `${fa(ms / 1000, 1)} ثانیه`);

export function ExamAnalysisSection() {
  const [exams, setExams] = useState<ExamOption[]>([]);
  const [examId, setExamId] = useState<string>("");
  const [data, setData] = useState<Analysis | null>(null);
  const [loadingExams, setLoadingExams] = useState(true);
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState("");
  const [listError, setListError] = useState("");

  const loadExams = useCallback(async () => {
    setLoadingExams(true);
    try {
      const res = await api<{ exams: ExamOption[] }>("/teacher/exams");
      setExams(res.exams);
      setListError("");
      setExamId((prev) =>
        prev === "" || !res.exams.some((e) => String(e.id) === prev) ? String(res.exams[0]?.id ?? "") : prev
      );
    } catch (err) {
      setListError(errOf(err, "خطا در بارگذاری فهرست آزمون‌ها"));
      setExams([]);
    } finally {
      setLoadingExams(false);
    }
  }, []);

  const loadAnalysis = useCallback(async (id: string) => {
    if (!id) {
      setData(null);
      return;
    }
    setLoading(true);
    setPageError("");
    try {
      setData(await api<Analysis>(`/teacher/exams/${id}/item-analysis`));
    } catch (err) {
      const msg = errOf(err, "خطا در دریای تحلیل سؤال‌ها");
      setData(null);
      if (err instanceof ApiError && err.status === 403) toast(msg, "error");
      else setPageError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadExams();
  }, [loadExams]);

  useEffect(() => {
    void loadAnalysis(examId);
  }, [examId, loadAnalysis]);

  const items = data?.items ?? [];
  const flagged = useMemo(() => items.filter((it) => it.needs_review), [items]);
  const avgCorrect = useMemo(() => {
    if (items.length === 0) return null;
    return items.reduce((s, it) => s + it.correct_pct, 0) / items.length;
  }, [items]);

  const chartData = useMemo(
    () =>
      items.map((it) => ({
        label: `سؤال ${fa(it.order)}`,
        value: Math.round(it.correct_pct),
        color: it.needs_review ? "#f43f5e" : undefined,
      })),
    [items]
  );

  const columns: Column<ItemRow>[] = [
    {
      key: "q",
      header: "سؤال",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">
            <span className="num">{fa(row.order)}</span> — {row.body.slice(0, 60)}
            {row.body.length > 60 ? "…" : ""}
          </p>
          <p className="text-[11px] text-ink-faint">
            {row.topic_title} · {DIFFICULTY_FA[row.difficulty] ?? row.difficulty} · {fa(row.responses_count)} پاسخ
          </p>
        </div>
      ),
    },
    {
      key: "correct",
      header: "درصد صحیح",
      align: "center",
      render: (row) => (
        <span className={`num text-xs font-bold ${row.correct_pct < 40 ? "text-danger-600" : "text-ink"}`}>
          {fa(row.correct_pct, 1)}٪
        </span>
      ),
    },
    {
      key: "difficulty",
      header: "دشواری تجربی / پیش‌فرض",
      align: "center",
      render: (row) => (
        <span className="num text-xs text-ink-muted">
          {fa(row.empirical_difficulty, 2)} / {fa(row.prior_difficulty, 2)}
        </span>
      ),
    },
    {
      key: "disc",
      header: "قدرت تفکیک",
      align: "center",
      render: (row) =>
        row.discrimination === null ? (
          <span className="text-xs text-ink-faint">—</span>
        ) : (
          <Badge tone={row.discrimination < 0.15 ? "danger" : "success"}>{fa(row.discrimination, 2)}</Badge>
        ),
    },
    {
      key: "time",
      header: "میانگین زمان",
      align: "center",
      render: (row) => <span className="num text-xs text-ink-muted">{seconds(row.avg_time_ms)}</span>,
    },
    {
      key: "wrong",
      header: "خطای رایج",
      render: (row) =>
        row.top_wrong_option && row.top_wrong_pct ? (
          <div className="space-y-1">
            <Badge tone="warning">گزینه {row.top_wrong_option} — {fa(row.top_wrong_pct, 1)}٪</Badge>
            {row.misconception && <p className="text-[11px] text-ink-faint">{row.misconception}</p>}
          </div>
        ) : (
          <span className="text-xs text-ink-faint">—</span>
        ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={row.needs_review ? REVIEW_TONE : "success"} dot={row.needs_review}>
          {row.needs_review ? "نیازمند بازبینی" : "سالم"}
        </Badge>
      ),
    },
    {
      key: "comment",
      header: "توضیح تحلیل",
      render: (row) => (
        <div className="space-y-1">
          <p className="text-xs leading-6 text-ink-muted">{row.comment_fa}</p>
          {row.review_reasons.map((r) => (
            <p key={r} className="text-[11px] font-semibold text-danger-600">
              ⚠ {r}
            </p>
          ))}
        </div>
      ),
    },
  ];

  /* ------------------------------ حالت‌ها ------------------------------ */

  if (loadingExams) return <SkeletonTable rows={4} cols={5} />;

  if (listError) {
    return (
      <Alert variant="danger" title="خطا">
        {listError}
      </Alert>
    );
  }

  if (exams.length === 0) {
    return (
      <EmptyState
        icon={<IconExam size={26} />}
        title="هنوز آزمونی نساخته‌اید"
        description="ابتدا در تب «سازنده آزمون» یک آزمون بسازید و منتشر کنید؛ سپس تحلیل سؤال‌های آن این‌جا نمایش داده می‌شود."
      />
    );
  }

  const selected = exams.find((e) => String(e.id) === examId);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="تحلیل پس از آزمون (§10)"
          subtitle="دشواری تجربی، قدرت تفکیک، زمان پاسخ و خطاهای رایج هر سؤال — با پرچم خودکار «نیازمند بازبینی»."
          icon={<IconChart size={17} />}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="آزمون">
            <Select value={examId} onChange={(e) => setExamId(e.target.value)}>
              {exams.map((e) => (
                <option key={e.id} value={String(e.id)}>
                  {e.title_fa} — {e.type_fa}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="خلاصه" hint={selected ? `${fa(selected.item_count)} سؤال · ${fa(selected.attempts_count)} تلاش` : undefined}>
            <div className="flex h-[42px] items-center gap-2">
              <Button size="sm" variant="soft" loading={loading} onClick={() => loadAnalysis(examId)}>
                به‌روزرسانی
              </Button>
              {selected && (
                <Badge tone={selected.status === "draft" ? "warning" : selected.status === "published" ? "success" : "neutral"}>
                  {selected.status === "draft" ? "پیش‌نویس" : selected.status === "published" ? "منتشرشده" : selected.status === "closed" ? "بسته" : "تصحیح‌شده"}
                </Badge>
              )}
            </div>
          </Field>
        </div>
      </Card>

      {pageError && (
        <Alert variant="danger" title="خطا">
          {pageError}
        </Alert>
      )}

      {loading && !data && <SkeletonTable rows={4} cols={6} />}

      {data && data.items.length === 0 && (
        <EmptyState
          icon={<IconTarget size={26} />}
          title="هنوز سؤالی برای تحلیل نیست"
          description={data.note_fa ?? "این آزمون سؤالی ندارد؛ در سازنده آزمون سؤال اضافه کنید."}
        />
      )}

      {data && data.items.length > 0 && (
        <>
          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label="تلاش‌های تصحیح‌شده"
              value={fa(data.attempts)}
              tone="primary"
              icon={<IconTarget size={20} />}
              hint="مبنای درصد صحیح هر سؤال"
            />
            <StatCard
              label="میانگین درصد صحیح"
              value={avgCorrect !== null ? `${fa(avgCorrect, 1)}٪` : "—"}
              tone={avgCorrect !== null && avgCorrect < 50 ? "warning" : "success"}
              icon={<IconChart size={20} />}
              hint="میانگین سادهٔ سؤال‌ها"
            />
            <StatCard
              label="سؤال‌های نیازمند بازبینی"
              value={fa(data.flagged_count)}
              tone={data.flagged_count > 0 ? "danger" : "success"}
              icon={<IconAlert size={20} />}
              hint="§10.2 — پرچم خودکار"
            />
            <StatCard
              label="آستانه‌های تحلیل"
              value={fa(data.thresholds.discrimination_min, 2)}
              tone="accent"
              icon={<IconClock size={20} />}
              hint={`تفکیک < ${fa(data.thresholds.discrimination_min, 2)} · شکاف > ${fa(data.thresholds.difficulty_gap, 2)} · z > ${fa(data.thresholds.time_zscore_max, 1)}`}
            />
          </section>

          {data.note_fa && <Alert variant="info" title="نکته">{data.note_fa}</Alert>}

          {data.flagged_count > 0 ? (
            <Alert variant="danger" title={`${fa(data.flagged_count)} سؤال نیازمند بازبینی است`}>
              <ul className="list-disc space-y-1 ps-5">
                {flagged.map((it) => (
                  <li key={it.exam_item_id}>
                    سؤال {fa(it.order)}: {it.review_reasons.join("؛ ")}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : (
            <Alert variant="success" title="همهٔ سؤال‌ها سالم هستند">
              هیچ سؤالی از آستانه‌های بازبینی (§10.2) عبور نکرده است.
            </Alert>
          )}

          <Card>
            <CardHeader
              title="درصد پاسخ صحیح به تفکیک سؤال"
              subtitle="ستون‌های قرمز سؤال‌های نیازمند بازبینی هستند."
              icon={<IconChart size={17} />}
            />
            <BarChart data={chartData} height={230} id="item-correct" format={(v) => `${fa(v)}٪`} />
          </Card>

          <Section
            title="جدول تحلیل سؤال‌ها"
            subtitle="دشواری تجربی = درصد صحیح؛ تمایز با روش بیست‌وهفت‌درصد بالا و پایین (حداقل ۴ تلاش)."
          >
            <DataTable
              columns={columns}
              rows={items}
              keyOf={(r) => r.exam_item_id}
              rowClass={(r) => (r.needs_review ? "bg-danger-50/40" : undefined)}
              empty={<EmptyState compact title="داده‌ای برای نمایش نیست" />}
            />
          </Section>

          <Card variant="outline">
            <div className="flex items-start gap-2 text-xs leading-6 text-ink-muted">
              <IconCheckCircle size={16} className="mt-0.5 shrink-0 text-success-600" />
              <p>
                تفسیر: دشواری تجربی پایین‌تر از پیش‌فرض یعنی سؤال از حد انتظار دشوارتر است؛ قدرت تفکیک منفی یعنی دانش‌آموزان
                قوی‌تر بدتر پاسخ داده‌اند و سؤال باید بازبینی شود. پس از هر بار محاسبه، نتایج در جدول پایدار می‌شوند.
              </p>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
