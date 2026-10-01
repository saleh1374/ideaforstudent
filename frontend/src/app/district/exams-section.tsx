"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { GRADE_FA, SUBJECT_FA, fa, gradeFa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { StatCard } from "@/components/ui/stat";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { BarChart } from "@/components/ui/charts";
import { IconChart, IconExam, IconPlus, IconRefresh, IconSchool, IconUsers } from "@/components/ui/icons";

/* ------------------------- نگاشت‌های محلی (فایل مشترک lib قابل ویرایش نیست) ------------------------- */

const EXAM_STATUS_FA: Record<string, string> = {
  draft: "پیش‌نویس",
  published: "منتشرشده",
  graded: "تصحیح‌شده",
  closed: "بسته‌شده",
};

const EXAM_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  published: "info",
  graded: "success",
  closed: "accent",
};

const EXAM_STATUS_FILTERS = ["draft", "published", "graded", "closed"] as const;

/** برچسب دکمهٔ هر گذار وضعیت (目标 = status مقصد). */
const NEXT_STATUS_FA: Record<string, string> = {
  draft: "بازگشت به پیش‌نویس",
  published: "انتشار",
  graded: "ثبت تصحیح",
  closed: "بستن",
};

const CAUSE_FA: Record<string, string> = {
  conceptual: "ضعف مفهومی",
  prerequisite: "ضعف پیش‌نیاز",
  calculation: "خطای محاسباتی",
  careless: "بی‌دقتی",
  time_management: "کمبود زمان",
  guess: "حدس",
};

/* ------------------------- انواع پاسخ سرور ------------------------- */

type SchoolLite = { id: number; name: string };

type ExamRow = {
  id: number;
  exam_id: number | null;
  title_fa: string;
  grade: string;
  subject: string;
  blueprint: string | null;
  status: string;
  status_fa: string;
  opens_at: string | null;
  closes_at: string | null;
  created_at: string;
  created_by_name: string | null;
  next_statuses: string[];
  schools_count: number;
  items_count: number;
  participants: number;
};

type ExamDetail = ExamRow & {
  schools: { id: number; name: string; school_code: string | null }[];
  items: {
    order: number;
    item_id: number;
    body: string;
    difficulty: string;
    topic: string | null;
    points: number;
  }[];
};

type Agg = {
  participants: number;
  avg_percent: number | null;
  pass_rate: number | null;
  suppressed: boolean;
  min_group: number;
};

type Results = {
  exam: ExamRow;
  overall: (Agg & {
    eligible: number;
    participation_rate: number | null;
    outside_participants: number;
    pass_percent: number;
  }) | null;
  schools: (Agg & { school_id: number; name: string | null; eligible: number })[];
  classes: (Agg & { class_id: number; school_id: number | null; name: string | null })[];
  note_fa: string;
};

type AnalysisItem = {
  order: number;
  item_id: number;
  body: string;
  topic: string | null;
  difficulty: string;
  prior_difficulty: number;
  responses: number;
  pct_correct: number | null;
  empirical_difficulty: number | null;
  discrimination: number | null;
  blank_pct: number | null;
  avg_time_ms: number | null;
  top_distractor: string | null;
  top_distractor_pct: number | null;
  top_distractor_cause: string | null;
  misconception: string | null;
  needs_review: boolean;
  review_reasons: { code: string; text: string }[];
  insufficient_data: boolean;
};

type Analysis = {
  exam: ExamRow;
  items: AnalysisItem[];
  thresholds: { discrimination: number; difficulty_gap: number; min_responses?: number };
  note_fa: string;
};

const DIFFICULTY_FA: Record<string, string> = { easy: "آسان", medium: "متوسط", hard: "دشوار" };

/* ------------------------- بخش آزمون‌های رسمی ناحیه (§20–§21) ------------------------- */

export function ExamsSection() {
  const [rows, setRows] = useState<ExamRow[]>([]);
  const [schools, setSchools] = useState<SchoolLite[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // فرم ساخت
  const [form, setForm] = useState({
    title: "",
    grade: "grade_10",
    subject: "math",
    blueprint: "",
    opens: "",
    closes: "",
    item_count: "",
  });
  const [formSchools, setFormSchools] = useState<number[]>([]);
  const [creating, setCreating] = useState(false);

  // مودال جزئیات + گذار وضعیت
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ExamDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  // مودال نتایج
  const [resultsId, setResultsId] = useState<number | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [resultsLoading, setResultsLoading] = useState(false);

  // مودال تحلیل سؤال
  const [analysisId, setAnalysisId] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);

  const load = useCallback(async (st: string) => {
    setLoading(true);
    try {
      const res = await api<{ total: number; exams: ExamRow[] }>(
        `/district/exams${st ? `?status=${st}` : ""}`
      );
      setRows(res.exams);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت آزمون‌های رسمی");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(status);
  }, [status, load]);

  useEffect(() => {
    api<{ schools: SchoolLite[] }>("/district/me/schools")
      .then((d) => setSchools(d.schools))
      .catch(() => setSchools([]));
  }, []);

  async function createExam(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim()) {
      toast("عنوان آزمون الزامی است.", "warning");
      return;
    }
    if (formSchools.length === 0) {
      toast("دست‌کم یک مدرسه را انتخاب کنید.", "warning");
      return;
    }
    setCreating(true);
    try {
      const res = await api<{ ok: boolean; exam: ExamDetail }>("/district/exams", {
        method: "POST",
        json: {
          title_fa: form.title.trim(),
          grade: form.grade,
          subject: form.subject,
          school_ids: formSchools,
          blueprint: form.blueprint.trim() || null,
          opens_at: form.opens || null,
          closes_at: form.closes || null,
          item_count: form.item_count ? Number(form.item_count) : null,
        },
      });
      toast(`آزمون «${res.exam.title_fa}» در وضعیت پیش‌نویس ساخته شد.`, "success");
      setForm({ title: "", grade: "grade_10", subject: "math", blueprint: "", opens: "", closes: "", item_count: "" });
      setFormSchools([]);
      await load(status);
    } catch (err) {
      // 400 عنوان/پایه/زمان/بانک سؤال — همه فارسی‌اند
      toast(err instanceof Error ? err.message : "خطا در ساخت آزمون", "error");
    } finally {
      setCreating(false);
    }
  }

  async function openDetail(id: number) {
    setDetailId(id);
    setDetail(null);
    setDetailLoading(true);
    try {
      const res = await api<{ exam: ExamDetail }>(`/district/exams/${id}`);
      setDetail(res.exam);
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در دریافت جزئیات", "error");
      setDetailId(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function changeStatus(next: string) {
    if (detailId === null) return;
    setBusy(true);
    try {
      const res = await api<{ exam: ExamDetail }>(`/district/exams/${detailId}/status`, {
        method: "PATCH",
        json: { status: next },
      });
      setDetail(res.exam);
      toast(`وضعیت آزمون: ${res.exam.status_fa}`, "success");
      await load(status);
    } catch (e) {
      // 400 گذار غیرمجاز / 409 پاسخ ثبت‌شده برای بازگشت به پیش‌نویس
      toast(e instanceof Error ? e.message : "خطا در تغییر وضعیت", "error");
    } finally {
      setBusy(false);
    }
  }

  async function openResults(id: number) {
    setResultsId(id);
    setResults(null);
    setResultsLoading(true);
    try {
      setResults(await api<Results>(`/district/exams/${id}/results`));
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در دریافت نتایج", "error");
      setResultsId(null);
    } finally {
      setResultsLoading(false);
    }
  }

  async function openAnalysis(id: number) {
    setAnalysisId(id);
    setAnalysis(null);
    setAnalysisLoading(true);
    try {
      setAnalysis(await api<Analysis>(`/district/exams/${id}/item-analysis`));
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در دریافت تحلیل سؤال", "error");
      setAnalysisId(null);
    } finally {
      setAnalysisLoading(false);
    }
  }

  function toggleSchool(id: number) {
    setFormSchools((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  /* ------------------------- ستون‌های جدول آزمون‌ها ------------------------- */

  const columns: Column<ExamRow>[] = [
    {
      key: "title",
      header: "آزمون",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.title_fa}</p>
          <p className="text-[11px] text-ink-faint">
            {gradeFa(row.grade)} · {subjectFa(row.subject)}
            {row.created_by_name ? ` · ${row.created_by_name}` : ""}
          </p>
        </div>
      ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={EXAM_STATUS_TONE[row.status] ?? "neutral"} dot>
          {row.status_fa || EXAM_STATUS_FA[row.status] || row.status}
        </Badge>
      ),
    },
    {
      key: "counts",
      header: "مدرسه / سؤال / شرکت‌کننده",
      align: "center",
      render: (row) => (
        <span className="num text-xs font-semibold text-ink">
          {fa(row.schools_count)} <span className="text-ink-faint">/</span> {fa(row.items_count)}{" "}
          <span className="text-ink-faint">/</span> {fa(row.participants)}
        </span>
      ),
    },
    {
      key: "window",
      header: "زمان برگزاری",
      align: "center",
      render: (row) => (
        <span className="num text-[11px] text-ink-faint">
          {row.opens_at ? faDate(row.opens_at) : "—"}
          {" ← "}
          {row.closes_at ? faDate(row.closes_at) : "—"}
        </span>
      ),
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (row) => (
        <span className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="soft" onClick={() => openDetail(row.id)}>
            جزئیات
          </Button>
          <Button size="sm" variant="outline" onClick={() => openResults(row.id)}>
            نتایج
          </Button>
          <Button size="sm" variant="outline" onClick={() => openAnalysis(row.id)}>
            تحلیل سؤال
          </Button>
        </span>
      ),
    },
  ];

  /* ------------------------- ستون‌های جدول مدرسه‌ها/کلاس‌های نتایج ------------------------- */

  const resultSchoolColumns: Column<Results["schools"][number]>[] = [
    { key: "name", header: "مدرسه", render: (row) => <span className="font-semibold text-ink">{row.name ?? "—"}</span> },
    { key: "n", header: "شرکت‌کننده", align: "center", render: (row) => <span className="num text-xs font-bold text-ink">{fa(row.participants)}</span> },
    { key: "avg", header: "میانگین", align: "center", render: (row) => <PercentCell value={row.avg_percent} suppressed={row.suppressed} /> },
    { key: "pass", header: "نرخ قبولی", align: "center", render: (row) => <PercentCell value={row.pass_rate} suppressed={row.suppressed} /> },
    {
      key: "sup",
      header: "جمعیت",
      align: "center",
      render: (row) =>
        row.suppressed ? (
          <Badge tone="warning">زیر حد نصاب ({fa(row.min_group)})</Badge>
        ) : (
          <Badge tone="success">کافی</Badge>
        ),
    },
  ];

  const resultClassColumns: Column<Results["classes"][number]>[] = [
    { key: "name", header: "کلاس", render: (row) => <span className="font-semibold text-ink">{row.name ?? "—"}</span> },
    { key: "n", header: "شرکت‌کننده", align: "center", render: (row) => <span className="num text-xs font-bold text-ink">{fa(row.participants)}</span> },
    { key: "avg", header: "میانگین", align: "center", render: (row) => <PercentCell value={row.avg_percent} suppressed={row.suppressed} /> },
    { key: "pass", header: "نرخ قبولی", align: "center", render: (row) => <PercentCell value={row.pass_rate} suppressed={row.suppressed} /> },
    {
      key: "sup",
      header: "جمعیت",
      align: "center",
      render: (row) =>
        row.suppressed ? <Badge tone="warning">زیر حد نصاب</Badge> : <Badge tone="success">کافی</Badge>,
    },
  ];

  const analysisColumns: Column<AnalysisItem>[] = [
    {
      key: "item",
      header: "سؤال",
      render: (row) => (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-ink">
            <span className="num text-ink-faint">{fa(row.order)}.</span> {truncate(row.body, 70)}
          </p>
          <p className="text-[11px] text-ink-faint">
            {row.topic ?? "—"} · {DIFFICULTY_FA[row.difficulty] ?? row.difficulty}
          </p>
          {row.needs_review && (
            <ul className="space-y-0.5">
              {row.review_reasons.map((rr) => (
                <li key={rr.code} className="text-[11px] font-semibold leading-5 text-danger-600">
                  ● {rr.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      ),
    },
    {
      key: "resp",
      header: "پاسخ / صحیح",
      align: "center",
      render: (row) => (
        <span className="num text-xs font-semibold text-ink">
          {fa(row.responses)} <span className="text-ink-faint">/</span>{" "}
          {row.pct_correct !== null ? `${fa(row.pct_correct)}٪` : "—"}
        </span>
      ),
    },
    {
      key: "diff",
      header: "دشواری تجربی (پیشینی)",
      align: "center",
      render: (row) => (
        <span className="num text-xs text-ink-muted">
          {row.empirical_difficulty !== null ? fa(row.empirical_difficulty * 100) : "—"}
          <span className="text-ink-faint"> / </span>
          {fa(Math.round(row.prior_difficulty * 100))}
        </span>
      ),
    },
    {
      key: "disc",
      header: "تفکیک",
      align: "center",
      render: (row) =>
        row.discrimination === null ? (
          <span className="num text-xs text-ink-faint">—</span>
        ) : (
          <span
            className={`num text-xs font-bold ${
              row.discrimination < 0.15 ? "text-danger-600" : "text-success-600"
            }`}
          >
            {row.discrimination}
          </span>
        ),
    },
    {
      key: "blank",
      header: "خالی / زمان",
      align: "center",
      render: (row) => (
        <span className="num text-[11px] text-ink-faint">
          {row.blank_pct !== null ? `${fa(row.blank_pct)}٪` : "—"}
          <br />
          {row.avg_time_ms !== null ? `${fa(Math.round(row.avg_time_ms / 1000))} ثانیه` : "—"}
        </span>
      ),
    },
    {
      key: "distractor",
      header: "گزینهٔ غلط پرتکرار",
      render: (row) =>
        row.top_distractor ? (
          <div className="space-y-0.5">
            <p className="text-xs font-semibold text-ink">
              گزینه {row.top_distractor}
              {row.top_distractor_pct !== null && (
                <span className="num text-ink-faint"> ({fa(row.top_distractor_pct)}٪)</span>
              )}
            </p>
            {row.top_distractor_cause && (
              <p className="text-[11px] text-ink-faint">{CAUSE_FA[row.top_distractor_cause] ?? row.top_distractor_cause}</p>
            )}
            {row.misconception && <p className="text-[11px] text-warning-600">{row.misconception}</p>}
          </div>
        ) : (
          <span className="text-[11px] text-ink-faint">—</span>
        ),
    },
    {
      key: "review",
      header: "بازبینی",
      align: "center",
      render: (row) =>
        row.insufficient_data ? (
          <Badge tone="neutral">داده ناکافی</Badge>
        ) : row.needs_review ? (
          <Badge tone="danger" dot>
            نیازمند بازبینی
          </Badge>
        ) : (
          <Badge tone="success">سالم</Badge>
        ),
    },
  ];

  /* ------------------------- رندر ------------------------- */

  return (
    <Section
      title="آزمون‌های رسمی ناحیه"
      subtitle="ساخت آزمون رسمی با جدول مشخصات و مدارس انتخابی، انتشار با ممیزی، نتایج مقایسه‌ای و تحلیل سؤال (§20–§21)."
      action={<Badge tone="accent">گذار: پیش‌نویس ← منتشر ← تصحیح‌شده ← بسته</Badge>}
    >
      {/* ---------- ساخت آزمون ---------- */}
      <Card>
        <CardHeader
          title="ساخت آزمون رسمی"
          subtitle="پس از ساخت، آزمون در وضعیت پیش‌نویس است؛ انتشار نیازمند دست‌کم یک مدرسه و یک سؤال است."
          icon={<IconExam size={17} />}
        />
        <form onSubmit={createExam} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="عنوان آزمون" required>
            <Input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="مثلاً آزمون دوسالانه ناحیه — پایه دهم"
            />
          </Field>
          <Field label="پایه" required>
            <Select value={form.grade} onChange={(e) => setForm({ ...form, grade: e.target.value })}>
              {Object.entries(GRADE_FA).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="درس" required>
            <Select value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })}>
              {Object.entries(SUBJECT_FA).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="تعداد سؤال (نمونه از بانک)" hint="خالی → ۱۰ سؤال پیش‌فرض">
            <Input
              type="number"
              min={1}
              value={form.item_count}
              onChange={(e) => setForm({ ...form, item_count: e.target.value })}
              placeholder="مثلاً ۱۰"
            />
          </Field>
          <Field label="زمان شروع">
            <Input type="datetime-local" value={form.opens} onChange={(e) => setForm({ ...form, opens: e.target.value })} />
          </Field>
          <Field label="زمان پایان">
            <Input type="datetime-local" value={form.closes} onChange={(e) => setForm({ ...form, closes: e.target.value })} />
          </Field>
          <Field label="جدول مشخصات (Blueprint)" className="sm:col-span-2">
            <Textarea
              value={form.blueprint}
              onChange={(e) => setForm({ ...form, blueprint: e.target.value })}
              placeholder="توزیع مباحث، تعداد سؤال از هر مبحث، ضرایب…"
            />
          </Field>

          <div className="sm:col-span-2 lg:col-span-4">
            <div className="rounded-xl border border-line bg-surface-sunken p-3.5">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs font-bold text-ink">مدارس هدف (دانش‌آموزان همین مدارس در آزمون شرکت می‌کنند)</p>
                <div className="flex gap-2">
                  <Button type="button" size="sm" variant="ghost" onClick={() => setFormSchools(schools.map((s) => s.id))}>
                    همه
                  </Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setFormSchools([])}>
                    هیچ
                  </Button>
                </div>
              </div>
              {schools.length === 0 ? (
                <p className="text-[11px] text-ink-faint">مدرسه‌ای برای انتخاب یافت نشد.</p>
              ) : (
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {schools.map((sc) => (
                    <label
                      key={sc.id}
                      className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-muted transition hover:bg-white/70"
                    >
                      <input
                        type="checkbox"
                        checked={formSchools.includes(sc.id)}
                        onChange={() => toggleSchool(sc.id)}
                        className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                      />
                      {sc.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="sm:col-span-2 lg:col-span-4">
            <Button type="submit" loading={creating} icon={<IconPlus size={15} />}>
              ساخت آزمون در وضعیت پیش‌نویس
            </Button>
          </div>
        </form>
      </Card>

      {/* ---------- فیلتر وضعیت ---------- */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-56" aria-label="فیلتر وضعیت">
          <option value="">همه وضعیت‌ها</option>
          {EXAM_STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {EXAM_STATUS_FA[s]}
            </option>
          ))}
        </Select>
        <Button size="sm" variant="soft" icon={<IconRefresh size={14} />} onClick={() => load(status)} loading={loading}>
          به‌روزرسانی
        </Button>
      </div>

      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={4} cols={5} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.id}
          empty={
            <EmptyState
              compact
              icon={<IconExam size={24} />}
              title="آزمون رسمی ثبت نشده"
              description="با فرم بالا اولین آزمون رسمی ناحیه را بسازید؛ پس از انتشار، نتایج و تحلیل سؤال در دسترس می‌شود."
            />
          }
        />
      )}

      {/* ---------- مودال جزئیات + گذار وضعیت ---------- */}
      <Modal
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        title={detail ? `آزمون رسمی — ${detail.title_fa}` : "جزئیات آزمون رسمی"}
        size="lg"
        footer={
          <Button variant="ghost" onClick={() => setDetailId(null)}>
            بستن
          </Button>
        }
      >
        {detailLoading && !detail && <SkeletonTable rows={3} cols={3} />}

        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={EXAM_STATUS_TONE[detail.status] ?? "neutral"} dot>
                {detail.status_fa}
              </Badge>
              <Badge tone="neutral">{gradeFa(detail.grade)}</Badge>
              <Badge tone="neutral">{subjectFa(detail.subject)}</Badge>
              <Badge tone="info">
                {fa(detail.schools_count)} مدرسه · {fa(detail.items_count)} سؤال · {fa(detail.participants)} شرکت‌کننده
              </Badge>
            </div>

            {detail.blueprint && (
              <div className="rounded-xl border border-line bg-surface-sunken px-3.5 py-3">
                <p className="mb-1 text-xs font-bold text-ink">جدول مشخصات</p>
                <p className="text-[11px] leading-6 whitespace-pre-wrap text-ink-muted">{detail.blueprint}</p>
              </div>
            )}

            {/* گذارهای وضعیت */}
            <div className="space-y-2">
              <p className="text-xs font-bold text-ink">عملیات وضعیت</p>
              {detail.next_statuses.length === 0 ? (
                <p className="rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-faint">
                  آزمون بسته شده است؛ وضعیت نهایی.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {detail.next_statuses.map((next) => (
                    <Button
                      key={next}
                      size="sm"
                      variant={next === "draft" ? "outline" : "primary"}
                      loading={busy}
                      onClick={() => changeStatus(next)}
                    >
                      {NEXT_STATUS_FA[next] ?? next}
                    </Button>
                  ))}
                </div>
              )}
              <p className="text-[11px] leading-5 text-ink-faint">
                انتشار، بازگشت به پیش‌نویس، تصحیح و بستن همگی با رویداد ممیزی ثبت می‌شوند؛ بازگشت به پیش‌نویس فقط پیش از ثبت
                هر پاسخ ممکن است.
              </p>
            </div>

            {/* مدارس */}
            <div className="space-y-2">
              <p className="text-xs font-bold text-ink">مدارس هدف</p>
              <div className="flex flex-wrap gap-2">
                {detail.schools.map((sc) => (
                  <Badge key={sc.id} tone="primary">
                    {sc.name}
                  </Badge>
                ))}
              </div>
            </div>

            {/* اقلام سؤال */}
            <div className="space-y-2">
              <p className="text-xs font-bold text-ink">اقلام سؤال</p>
              {detail.items.length === 0 ? (
                <p className="rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-faint">سؤالی ثبت نشده است.</p>
              ) : (
                <ul className="divide-y divide-line-soft rounded-xl border border-line">
                  {detail.items.map((it) => (
                    <li key={it.item_id} className="flex items-start justify-between gap-3 px-3.5 py-2.5 text-xs">
                      <span className="min-w-0">
                        <span className="num font-bold text-ink">{fa(it.order)}.</span>{" "}
                        <span className="text-ink">{truncate(it.body, 90)}</span>
                        <span className="mt-0.5 block text-[11px] text-ink-faint">
                          {it.topic ?? "—"} · {DIFFICULTY_FA[it.difficulty] ?? it.difficulty} · {fa(it.points)} نمره
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* ---------- مودال نتایج ---------- */}
      <Modal
        open={resultsId !== null}
        onClose={() => setResultsId(null)}
        title="نتایج آزمون رسمی"
        size="lg"
        footer={
          <Button variant="ghost" onClick={() => setResultsId(null)}>
            بستن
          </Button>
        }
      >
        {resultsLoading && !results && <SkeletonTable rows={3} cols={4} />}

        {results && (
          <div className="space-y-5">
            {results.overall === null ? (
              <Alert variant="info">{results.note_fa}</Alert>
            ) : (
              <>
                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <StatCard
                    label="میانگین کل ناحیه"
                    value={results.overall.suppressed ? "زیر حد نصاب" : `${fa(results.overall.avg_percent)}٪`}
                    tone={results.overall.suppressed ? "warning" : "primary"}
                    icon={<IconChart size={20} />}
                    hint={`حداقل جمعیت: ${fa(results.overall.min_group)}`}
                  />
                  <StatCard
                    label="نرخ قبولی"
                    value={results.overall.suppressed ? "زیر حد نصاب" : `${fa(results.overall.pass_rate)}٪`}
                    tone={results.overall.suppressed ? "warning" : "success"}
                    icon={<IconExam size={20} />}
                    hint={`آستانه: ${fa(results.overall.pass_percent)}٪`}
                  />
                  <StatCard
                    label="شرکت‌کنندگان"
                    value={fa(results.overall.participants)}
                    tone="accent"
                    icon={<IconUsers size={20} />}
                    hint={`${fa(results.overall.eligible)} واجد شرایط · ${fa(results.overall.outside_participants)} خارج از مدارس هدف`}
                  />
                  <StatCard
                    label="نرخ مشارکت"
                    value={results.overall.participation_rate !== null ? `${fa(results.overall.participation_rate)}٪` : "—"}
                    tone="sky"
                    icon={<IconSchool size={20} />}
                    hint="دانش‌آموزان واجد شرایط که شرکت کردند"
                  />
                </section>

                <Alert variant="info">{results.note_fa}</Alert>

                <div className="space-y-2">
                  <p className="text-xs font-bold text-ink">به تفکیک مدرسه</p>
                  <DataTable
                    columns={resultSchoolColumns}
                    rows={results.schools}
                    keyOf={(r) => r.school_id}
                    dense
                    empty={<EmptyState compact title="مدرسه‌ای ثبت نشده" />}
                  />
                </div>

                {results.schools.some((s) => !s.suppressed && s.avg_percent !== null) && (
                  <Card variant="sunken">
                    <CardHeader title="میانگین مدارس (فقط گروه‌های بالای حداقل جمعیت)" icon={<IconChart size={17} />} />
                    <BarChart
                      id="district-exam-results"
                      height={220}
                      format={(v) => `${fa(v)}٪`}
                      data={results.schools
                        .filter((s) => !s.suppressed && s.avg_percent !== null)
                        .map((s) => ({
                          label: s.name ?? `مدرسه ${fa(s.school_id)}`,
                          value: Math.round(s.avg_percent as number),
                          color: (s.avg_percent as number) >= (results.overall?.pass_percent ?? 60) ? "#10b981" : "#f59e0b",
                        }))}
                    />
                  </Card>
                )}

                <div className="space-y-2">
                  <p className="text-xs font-bold text-ink">به تفکیک کلاس</p>
                  <DataTable
                    columns={resultClassColumns}
                    rows={results.classes}
                    keyOf={(r) => r.class_id}
                    dense
                    empty={<EmptyState compact title="کلاسی ثبت نشده" />}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </Modal>

      {/* ---------- مودال تحلیل سؤال ---------- */}
      <Modal
        open={analysisId !== null}
        onClose={() => setAnalysisId(null)}
        title="تحلیل سؤال‌های آزمون"
        size="lg"
        footer={
          <Button variant="ghost" onClick={() => setAnalysisId(null)}>
            بستن
          </Button>
        }
      >
        {analysisLoading && !analysis && <SkeletonTable rows={4} cols={5} />}

        {analysis && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge tone="danger">تفکیک &lt; {analysis.thresholds.discrimination}</Badge>
              <Badge tone="warning">
                فاصله دشواری &gt; {analysis.thresholds.difficulty_gap}
              </Badge>
              {typeof analysis.thresholds.min_responses === "number" && (
                <Badge tone="neutral">حداقل پاسخ: {fa(analysis.thresholds.min_responses)}</Badge>
              )}
            </div>

            <Alert variant="info">{analysis.note_fa}</Alert>

            {analysis.items.length === 0 ? (
              <EmptyState compact icon={<IconExam size={24} />} title="تحلیلی در دسترس نیست" description={analysis.note_fa} />
            ) : (
              <DataTable columns={analysisColumns} rows={analysis.items} keyOf={(r) => r.item_id} dense />
            )}
          </div>
        )}
      </Modal>
    </Section>
  );
}

/* ------------------------- ابزارهای کمکی ------------------------- */

function PercentCell({ value, suppressed }: { value: number | null; suppressed: boolean }) {
  if (suppressed || value === null) return <Badge tone="warning">زیر حد نصاب</Badge>;
  return <span className="num text-xs font-bold text-ink">{fa(value)}٪</span>;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function faDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}
