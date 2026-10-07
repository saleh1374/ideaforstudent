"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, api } from "@/lib/api";
import { GRADE_FA, SUBJECT_FA, fa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Select } from "@/components/ui/forms";
import { Tabs } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/ui/table";
import { ProgressBar } from "@/components/ui/progress";
import { DonutChart, HorizontalBars, LineChart, chartColor } from "@/components/ui/charts";
import { SkeletonCard, SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import {
  IconAlert,
  IconChart,
  IconClock,
  IconExam,
  IconRefresh,
  IconSchool,
  IconSparkles,
  IconTarget,
  IconTrend,
  IconUsers,
} from "@/components/ui/icons";

/* ------------------------- انواع پاسخ سرور (دقیقاً مطابق backend) ------------------------- */

type Band = "good" | "medium" | "weak" | "unknown";

type HealthAxis = {
  key: string;
  title_fa: string;
  question_fa: string;
  value: number | null;
  unit: string;
  band: Band;
  suppressed: boolean;
  detail_fa: string;
};

type HealthResp = {
  district_id: number;
  axes: HealthAxis[];
  suppressed: boolean;
  min_group: number;
  note_fa: string;
};

type TrendItem = {
  key: string;
  title_fa: string;
  value: number | null;
  unit: string;
  direction: "up" | "down" | "flat" | "none";
  band: Band;
  note_fa: string;
};

type TrendsResp = {
  district_id: number;
  suppressed: boolean;
  min_group: number;
  trends: TrendItem[];
  note_fa: string;
};

type CompareRow = {
  school_id: number;
  name: string;
  school_code: string;
  school_type: string;
  ownership_type: string;
  status: string;
  students_count: number;
  students_with_data: number;
  suppressed: boolean;
  min_group: number;
  entry_mastery: number | null;
  current_mastery: number | null;
  growth: number | null;
  avg_retention: number | null;
  exam_avg: number | null;
  conceptual_error_pct: number | null;
  calculation_error_pct: number | null;
  practice_completion_pct: number | null;
  needs_intervention_pct: number | null;
  errors_total: number | null;
};

type CompareResp = {
  district_id: number;
  grade: string | null;
  subject: string | null;
  min_group: number;
  stages: string[];
  goal_mastery: number;
  rows: CompareRow[];
  note_fa: string;
};

type SeriesPoint = { label: string; value: number; points?: number };

type GrowthRow = {
  school_id: number;
  name: string;
  suppressed: boolean;
  entry: number | null;
  current: number | null;
  growth: number | null;
  series: SeriesPoint[];
  exam_series: { label: string; value: number }[];
  growth_vs_prev_exam: number | null;
  trend: "up" | "flat" | "down" | null;
};

type GrowthResp = {
  district_id: number;
  min_group: number;
  district: { entry: number | null; current: number | null; growth: number | null; series: SeriesPoint[] };
  rows: GrowthRow[];
  note_fa: string;
};

type ErrorCause = { key: string; title_fa: string; count: number | null; pct: number | null };

type ErrorSchoolRow = {
  school_id: number;
  name: string;
  total: number | null;
  students: number | null;
  causes: Record<string, number> | null;
  suppressed: boolean;
};

type ErrorTopicRow = {
  topic_id: number;
  title: string;
  count: number;
  dominant_error: string;
  dominant_error_fa: string;
};

type ErrorResp = {
  district_id: number;
  total: number | null;
  students: number | null;
  suppressed: boolean;
  min_group: number;
  causes: ErrorCause[];
  schools: ErrorSchoolRow[];
  topics: ErrorTopicRow[];
  note_fa: string;
};

type AttentionFlag = { code: string; severity: string; title_fa: string; detail_fa: string };

type AttentionRow = {
  kind: string;
  id: number;
  name: string;
  school_code?: string;
  school_id?: number;
  grade?: string;
  students_count: number;
  students_with_data: number;
  suppressed: boolean;
  growth: number | null;
  current_mastery: number | null;
  needs_intervention_pct?: number | null;
  flags: AttentionFlag[];
  severity: string;
  severity_fa: string;
  score: number;
};

type AttentionProblem = {
  topic_id: number;
  title: string;
  weak_students: number;
  students_count: number;
  weak_ratio: number;
  schools: number[];
  schools_count: number;
  classes_count: number;
  dominant_error: string | null;
  dominant_error_fa: string | null;
  prerequisites: string[];
  avg_mastery: number;
};

type AttentionAlert = {
  level: string;
  level_fa: string;
  title_fa: string;
  message_fa: string;
  school_id: number | null;
};

type AttentionResp = {
  district_id: number;
  min_group: number;
  district_growth: number | null;
  schools: AttentionRow[];
  classes: AttentionRow[];
  problems: AttentionProblem[];
  alerts: AttentionAlert[];
  severity_counts: Record<string, number>;
  thresholds: Record<string, number>;
  note_fa: string;
};

/* ------------------------- نگاشت‌های محلی (lib مشترک قابل ویرایش نیست) ------------------------- */

const BAND_FA: Record<string, string> = {
  good: "خوب",
  medium: "متوسط",
  weak: "ضعیف",
  unknown: "زیر حد نصاب",
};

const BAND_TONE: Record<string, Tone> = {
  good: "success",
  medium: "warning",
  weak: "danger",
  unknown: "neutral",
};

const SEVERITY_TONE: Record<string, Tone> = {
  critical: "danger",
  attention: "warning",
  forming: "info",
  normal: "neutral",
  positive: "success",
};

const TREND_FA: Record<string, string> = { up: "صعودی", flat: "ثابت", down: "نزولی" };
const TREND_TONE: Record<string, Tone> = { up: "success", flat: "neutral", down: "danger" };

const SEVERITY_FA: Record<string, string> = {
  critical: "بحرانی",
  attention: "نیازمند توجه",
  forming: "در حال شکل‌گیری",
  normal: "عادی",
  positive: "مثبت",
};

const AXIS_ICON: Record<string, ReactNode> = {
  learning: <IconTrend size={18} />,
  mastery: <IconTarget size={18} />,
  retention: <IconClock size={18} />,
  assessment: <IconExam size={18} />,
  engagement: <IconUsers size={18} />,
  intervention: <IconSparkles size={18} />,
};

const SEVERITY_FA_ORDER = ["critical", "attention", "forming", "normal", "positive"];

/** متن فارسی خطا — پیام دوستانه برای 403 (مجوز). */
function blockError(e: unknown, fallback: string): string {
  if (e instanceof ApiError && e.status === 403) {
    return "دسترسی به این بخش برای نقش شما فراهم نیست (۴۰۳) — مجوز «مشاهده تحلیل ناحیه» لازم است.";
  }
  return e instanceof Error && e.message ? e.message : fallback;
}

/** قالب‌بندی مقدار شاخص بر اساس واحد سرور. */
function fmtMetric(value: number | null, unit: string): string {
  if (value === null) return "زیر حد نصاب";
  switch (unit) {
    case "٪":
    case "درصد":
    case "٪ اثرگذار":
    case "٪ بهبود":
      return `${fa(value, 1)}٪`;
    case "نسبت":
      return fa(value, 2);
    case "واحد تسط":
      return `${fa(value, 1)} واحد`;
    default:
      return fa(value, 1);
  }
}

function pct(value: number | null): ReactNode {
  return value === null ? <span className="text-ink-faint">—</span> : <span className="num font-bold text-ink">{fa(value, 1)}٪</span>;
}

function deltaCell(value: number | null): ReactNode {
  if (value === null) return <span className="text-ink-faint">—</span>;
  const tone = value > 0.5 ? "text-success-600" : value < -0.5 ? "text-danger-600" : "text-ink-muted";
  return (
    <span className={`num text-xs font-bold ${tone}`}>
      {value > 0 ? "+" : ""}
      {fa(value, 1)}
    </span>
  );
}

type Res<T> = { data: T | null; loading: boolean; error: string };
const fresh = <T,>(): Res<T> => ({ data: null, loading: true, error: "" });

/* ------------------------- بخش تحلیل و سلامت ناحیه (۶ بلوک مستقل) ------------------------- */

export function AnalyticsSection() {
  const [health, setHealth] = useState<Res<HealthResp>>(fresh);
  const [trends, setTrends] = useState<Res<TrendsResp>>(fresh);
  const [compare, setCompare] = useState<Res<CompareResp>>(fresh);
  const [growth, setGrowth] = useState<Res<GrowthResp>>(fresh);
  const [errors, setErrors] = useState<Res<ErrorResp>>(fresh);
  const [attention, setAttention] = useState<Res<AttentionResp>>(fresh);

  const [cmpGrade, setCmpGrade] = useState("");
  const [cmpSubject, setCmpSubject] = useState("");
  // فیلترهای مقایسه در loadAll هم خوانده می‌شوند (فقط هنگام به‌روزرسانی کل بخش)
  const [filters, setFilters] = useState({ grade: "", subject: "" });
  const [refreshing, setRefreshing] = useState(false);

  const loadOne = useCallback(async <T,>(path: string, set: (v: Res<T>) => void) => {
    set({ data: null, loading: true, error: "" });
    try {
      set({ data: await api<T>(path), loading: false, error: "" });
    } catch (e) {
      set({ data: null, loading: false, error: blockError(e, "خطا در دریافت داده") });
    }
  }, []);

  const loadCompare = useCallback(
    (grade: string, subject: string) => {
      const qs = [grade ? `grade=${encodeURIComponent(grade)}` : "", subject ? `subject=${encodeURIComponent(subject)}` : ""]
        .filter(Boolean)
        .join("&");
      return loadOne<CompareResp>(`/district/schools/compare${qs ? `?${qs}` : ""}`, setCompare);
    },
    [loadOne]
  );

  const loadAll = useCallback(async () => {
    setRefreshing(true);
    // هر بلوک خطای خودش را مدیریت می‌کند → شکست یکی تب را خراب نمی‌کند
    await Promise.allSettled([
      loadOne<HealthResp>("/district/health", setHealth),
      loadOne<TrendsResp>("/district/trends", setTrends),
      loadOne<GrowthResp>("/district/schools/growth", setGrowth),
      loadOne<ErrorResp>("/district/error-analysis", setErrors),
      loadOne<AttentionResp>("/district/attention-center", setAttention),
      loadCompare(filters.grade, filters.subject),
    ]);
    setRefreshing(false);
  }, [loadOne, loadCompare, filters.grade, filters.subject]);

  useEffect(() => {
    loadAll();
    // بارگذاری یک‌باره هنگام نصب بخش
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyCompareFilter(key: "grade" | "subject", value: string) {
    const next = { grade: filters.grade, subject: filters.subject, [key]: value };
    setFilters(next);
    if (key === "grade") setCmpGrade(value);
    else setCmpSubject(value);
    setCompare({ data: null, loading: true, error: "" });
    loadCompare(next.grade, next.subject);
  }

  /* ------------------------- ستون‌های جدول‌ها ------------------------- */

  const trendColumns: Column<TrendItem>[] = [
    { key: "title", header: "شاخص", render: (r) => <span className="font-semibold text-ink">{r.title_fa}</span> },
    {
      key: "value",
      header: "مقدار",
      align: "center",
      render: (r) => <span className="num text-xs font-extrabold text-ink">{fmtMetric(r.value, r.unit)}</span>,
    },
    {
      key: "direction",
      header: "جهت",
      align: "center",
      render: (r) =>
        r.direction === "none" ? (
          <Badge tone="neutral">—</Badge>
        ) : (
          <Badge tone={r.direction === "up" ? "success" : r.direction === "down" ? "danger" : "neutral"} dot>
            {r.direction === "up" ? "رو به بالا" : r.direction === "down" ? "رو به پایین" : "ثابت"}
          </Badge>
        ),
    },
    {
      key: "band",
      header: "طبقه‌بندی",
      align: "center",
      render: (r) => <Badge tone={BAND_TONE[r.band] ?? "neutral"}>{BAND_FA[r.band] ?? r.band}</Badge>,
    },
    { key: "note", header: "توضیح سرور", render: (r) => <span className="text-[11px] leading-5 text-ink-faint">{r.note_fa}</span> },
  ];

  const compareColumns: Column<CompareRow>[] = [
    {
      key: "school",
      header: "مدرسه",
      render: (r) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{r.name}</p>
          <p className="num text-[11px] text-ink-faint">{r.school_code}</p>
          {r.suppressed && (
            <Badge tone="neutral">
              زیر حد نصاب ({fa(r.students_with_data)}/{fa(r.min_group)} دانش‌آموز دارای داده)
            </Badge>
          )}
        </div>
      ),
    },
    { key: "entry", header: "سطح ورودی", align: "center", render: (r) => pct(r.entry_mastery) },
    {
      key: "current",
      header: "وضعیت فعلی",
      render: (r) =>
        r.current_mastery === null ? (
          <span className="text-ink-faint">—</span>
        ) : (
          <div className="space-y-1">
            <span className="num text-xs font-bold text-ink">{fa(r.current_mastery)}٪</span>
            <ProgressBar
              value={r.current_mastery}
              size="sm"
              tone={r.current_mastery >= 65 ? "success" : r.current_mastery >= 50 ? "warning" : "danger"}
            />
          </div>
        ),
    },
    { key: "growth", header: "میزان رشد", align: "center", render: (r) => deltaCell(r.growth) },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (r) => (r.avg_retention === null ? <span className="text-ink-faint">—</span> : <span className="num font-bold text-ink">{fa(Math.round(r.avg_retention * 100))}٪</span>),
    },
    { key: "exam", header: "میانگین آزمون", align: "center", render: (r) => pct(r.exam_avg) },
    {
      key: "errors",
      header: "خطاهای غالب",
      align: "center",
      render: (r) =>
        r.conceptual_error_pct === null && r.calculation_error_pct === null ? (
          <span className="text-ink-faint">—</span>
        ) : (
          <div className="space-y-0.5 text-[11px]">
            <p className="num text-ink-muted">مفهومی: {r.conceptual_error_pct === null ? "—" : `${fa(r.conceptual_error_pct, 1)}٪`}</p>
            <p className="num text-ink-muted">محاسباتی: {r.calculation_error_pct === null ? "—" : `${fa(r.calculation_error_pct, 1)}٪`}</p>
          </div>
        ),
    },
    {
      key: "practice",
      header: "تکمیل تمرین",
      align: "center",
      render: (r) => pct(r.practice_completion_pct),
    },
    {
      key: "need",
      header: "نیازمند مداخله",
      align: "center",
      render: (r) => (r.needs_intervention_pct === null ? <span className="text-ink-faint">—</span> : <span className="num font-bold text-danger-600">{fa(r.needs_intervention_pct, 1)}٪</span>),
    },
  ];

  const growthColumns: Column<GrowthRow>[] = [
    {
      key: "school",
      header: "مدرسه",
      render: (r) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{r.name}</p>
          {r.suppressed && <Badge tone="neutral">زیر حد نصاب</Badge>}
        </div>
      ),
    },
    { key: "entry", header: "سطح ورودی", align: "center", render: (r) => pct(r.entry) },
    { key: "current", header: "وضعیت فعلی", align: "center", render: (r) => pct(r.current) },
    { key: "growth", header: "میزان رشد", align: "center", render: (r) => deltaCell(r.growth) },
    {
      key: "trend",
      header: "جهت رشد",
      align: "center",
      render: (r) =>
        r.trend === null ? <Badge tone="neutral">—</Badge> : <Badge tone={TREND_TONE[r.trend] ?? "neutral"} dot>{TREND_FA[r.trend] ?? r.trend}</Badge>,
    },
    {
      key: "exam_delta",
      header: "رشد نسبت به آزمون قبلی",
      align: "center",
      render: (r) => deltaCell(r.growth_vs_prev_exam),
    },
  ];

  const errorSchoolColumns: Column<ErrorSchoolRow>[] = [
    { key: "school", header: "مدرسه", render: (r) => <span className="font-semibold text-ink">{r.name}</span> },
    {
      key: "total",
      header: "خطاها",
      align: "center",
      render: (r) =>
        r.suppressed || r.total === null ? (
          <Badge tone="neutral">زیر حد نصاب</Badge>
        ) : (
          <span className="num font-bold text-ink">{fa(r.total)}</span>
        ),
    },
    {
      key: "students",
      header: "دانش‌آموزان خطاکار",
      align: "center",
      render: (r) => (r.students === null ? <span className="text-ink-faint">—</span> : <span className="num text-ink">{fa(r.students)}</span>),
    },
    {
      key: "causes",
      header: "علل غالب (خطا به تفکیک)",
      render: (r) =>
        r.causes === null ? (
          <span className="text-ink-faint">—</span>
        ) : Object.keys(r.causes).length === 0 ? (
          <span className="text-ink-faint">بدون خطا</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(r.causes).map(([k, v]) => (
              <Badge key={k} tone="neutral">
                {k}: <span className="num">{fa(v)}</span>
              </Badge>
            ))}
          </div>
        ),
    },
  ];

  const errorTopicColumns: Column<ErrorTopicRow>[] = [
    { key: "topic", header: "مبحث", render: (r) => <span className="font-semibold text-ink">{r.title}</span> },
    {
      key: "count",
      header: "تعداد خطا",
      align: "center",
      render: (r) => <span className="num font-bold text-ink">{fa(r.count)}</span>,
    },
    {
      key: "dominant",
      header: "خطای غالب",
      align: "center",
      render: (r) => <Badge tone="warning">{r.dominant_error_fa}</Badge>,
    },
  ];

  const attentionSchoolColumns: Column<AttentionRow>[] = [
    {
      key: "name",
      header: "مدرسه",
      render: (r) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{r.name}</p>
          <p className="num text-[11px] text-ink-faint">{r.school_code ?? `#${fa(r.id)}`}</p>
        </div>
      ),
    },
    {
      key: "severity",
      header: "شدت",
      align: "center",
      render: (r) => (
        <Badge tone={SEVERITY_TONE[r.severity] ?? "neutral"} dot>
          {r.severity_fa}
        </Badge>
      ),
    },
    { key: "growth", header: "رشد", align: "center", render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : deltaCell(r.growth)) },
    {
      key: "mastery",
      header: "تسط فعلی",
      align: "center",
      render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : pct(r.current_mastery)),
    },
    {
      key: "need",
      header: "نیازمند مداخله",
      align: "center",
      render: (r) =>
        r.needs_intervention_pct === null || r.needs_intervention_pct === undefined ? (
          <span className="text-ink-faint">—</span>
        ) : (
          <span className="num font-bold text-danger-600">{fa(r.needs_intervention_pct, 1)}٪</span>
        ),
    },
    {
      key: "flags",
      header: "پرچم‌ها و اقدام پیشنهادی",
      render: (r) =>
        r.flags.length === 0 ? (
          <span className="text-[11px] text-ink-faint">پرچمی ثبت نشده است.</span>
        ) : (
          <div className="space-y-1.5">
            {r.flags.map((f) => (
              <div key={f.code} className="space-y-0.5">
                <Badge tone={SEVERITY_TONE[f.severity] ?? "neutral"}>{f.title_fa}</Badge>
                <p className="text-[11px] leading-5 text-ink-faint">{f.detail_fa}</p>
              </div>
            ))}
          </div>
        ),
    },
  ];

  const attentionClassColumns: Column<AttentionRow>[] = [
    { key: "name", header: "کلاس", render: (r) => <span className="font-semibold text-ink">{r.name}</span> },
    { key: "grade", header: "پایه", align: "center", render: (r) => <span className="text-[11px] text-ink-muted">{GRADE_FA[r.grade ?? ""] ?? "—"}</span> },
    {
      key: "severity",
      header: "شدت",
      align: "center",
      render: (r) => (
        <Badge tone={SEVERITY_TONE[r.severity] ?? "neutral"} dot>
          {r.severity_fa}
        </Badge>
      ),
    },
    { key: "growth", header: "رشد", align: "center", render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : deltaCell(r.growth)) },
    { key: "mastery", header: "تسط فعلی", align: "center", render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : pct(r.current_mastery)) },
  ];

  const problemColumns: Column<AttentionProblem>[] = [
    {
      key: "topic",
      header: "مبحث مشترک",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{r.title}</p>
          <p className="num text-[11px] text-ink-faint">
            {fa(r.weak_students)} از {fa(r.students_count)} دانش‌آموز ضعیف · {fa(r.schools_count)} مدرسه · {fa(r.classes_count)} کلاس
          </p>
        </div>
      ),
    },
    {
      key: "ratio",
      header: "سهم ضعف",
      align: "center",
      render: (r) => (
        <div className="space-y-1">
          <span className="num text-xs font-bold text-danger-600">{fa(r.weak_ratio, 1)}٪</span>
          <ProgressBar value={r.weak_ratio} size="sm" tone="danger" />
        </div>
      ),
    },
    {
      key: "dominant",
      header: "خطای غالب",
      align: "center",
      render: (r) => (r.dominant_error_fa ? <Badge tone="warning">{r.dominant_error_fa}</Badge> : <span className="text-ink-faint">—</span>),
    },
    {
      key: "action",
      header: "اقدام پیشنهادی",
      render: (r) => {
        const parts: string[] = [];
        if (r.dominant_error_fa) parts.push(`کار هدفمند روی خطای ${r.dominant_error_fa}`);
        if (r.prerequisites.length) parts.push(`تقویت پیش‌نیاز: ${r.prerequisites.join("، ")}`);
        return <p className="text-[11px] leading-5 text-ink-muted">{parts.join(" · ") || "—"}</p>;
      },
    },
  ];

  const alertColumns: Column<AttentionAlert>[] = [
    {
      key: "level",
      header: "سطح",
      align: "center",
      render: (r) => (
        <Badge tone={SEVERITY_TONE[r.level] ?? "neutral"} dot>
          {r.level_fa}
        </Badge>
      ),
    },
    { key: "title", header: "هشدار", render: (r) => <span className="font-semibold text-ink">{r.title_fa}</span> },
    { key: "message", header: "پیام", render: (r) => <span className="text-[11px] leading-5 text-ink-muted">{r.message_fa}</span> },
  ];

  /* ------------------------- رندر ------------------------- */

  return (
    <Section
      title="تحلیل و سلامت ناحیه"
      subtitle="شش محور سلامت، روندها، مقایسه/رشد مدارس، تحلیل خطاهای ناحیه و کانون توجه — همه تجمیعی و با رعایت حداقل جمعیت (§2، §3، §5، §6، §9، §23)."
      action={
        <Button size="sm" variant="soft" loading={refreshing} icon={<IconRefresh size={14} />} onClick={loadAll}>
          به‌روزرسانی
        </Button>
      }
    >
      {/* ================= 1) سلامت ناحیه ================= */}
      <div>
        <p className="mb-3 text-xs font-bold text-ink">شش محور سلامت آموزشی</p>
        {health.loading ? (
          <SkeletonStats count={6} />
        ) : health.error ? (
          <Alert variant="warning" title="سلامت آموزشی ناحیه">
            {health.error}
          </Alert>
        ) : health.data ? (
          <div className="space-y-4">
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {health.data.axes.map((a) => (
                <Card key={a.key}>
                  <CardHeader title={a.title_fa} subtitle={a.question_fa} icon={AXIS_ICON[a.key] ?? <IconChart size={18} />} />
                  <div className="flex items-end justify-between gap-3">
                    <p className={`num text-2xl font-extrabold ${a.value === null ? "text-ink-faint" : "text-ink"}`}>
                      {fmtMetric(a.value, a.unit)}
                    </p>
                    <Badge tone={BAND_TONE[a.band] ?? "neutral"} dot>
                      {BAND_FA[a.band] ?? a.band}
                    </Badge>
                  </div>
                  <p className="mt-3 text-[11px] leading-5 text-ink-faint">{a.detail_fa}</p>
                </Card>
              ))}
            </section>
            <Alert variant="info">{health.data.note_fa}</Alert>
          </div>
        ) : (
          <EmptyState compact title="داده سلامت ناحیه‌ای موجود نیست" description="هنوز داده کافی برای محاسبه محورها ثبت نشده است." />
        )}
      </div>

      {/* ================= 2) روندها ================= */}
      <Card>
        <CardHeader
          title="روندهای داشبورد ناحیه"
          subtitle="رشد نسبت به آزمون/دوره قبلی، روند تسط و ماندگاری، مشارکت، تکمیل برنامه، مداخله‌ها و وضعیت آزمون‌ها (§2)."
          icon={<IconTrend size={17} />}
        />
        {trends.loading ? (
          <SkeletonTable rows={5} cols={5} />
        ) : trends.error ? (
          <Alert variant="warning" title="روندهای ناحیه">
            {trends.error}
          </Alert>
        ) : trends.data && trends.data.trends.length > 0 ? (
          <div className="space-y-3">
            <DataTable columns={trendColumns} rows={trends.data.trends} keyOf={(r) => r.key} dense empty={<EmptyState compact title="روندی ثبت نشده" />} />
            <Alert variant="info">{trends.data.note_fa}</Alert>
          </div>
        ) : (
          <EmptyState compact title="روندی محاسبه نشده" description="برای این ناحیه داده کافی جهت محاسبه روند وجود ندارد." />
        )}
      </Card>

      {/* ================= 3) مقایسه مدارس ================= */}
      <Card>
        <CardHeader
          title="مقایسه مدارس (سه گام)"
          subtitle={
            compare.data
              ? `${compare.data.stages.join(" ← ")} — هدف تسط ${fa(compare.data.goal_mastery)}٪`
              : "سطح ورودی ← وضعیت فعلی ← میزان رشد؛ زیر حداقل جمعیت هیچ عدد آموزشی نمایش داده نمی‌شود (§5)."
          }
          icon={<IconSchool size={17} />}
        />
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="پایه (فیلتر اختیاری)">
            <Select value={cmpGrade} onChange={(e) => applyCompareFilter("grade", e.target.value)}>
              <option value="">همه پایه‌ها</option>
              {Object.entries(GRADE_FA).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="درس (فیلتر اختیاری)">
            <Select value={cmpSubject} onChange={(e) => applyCompareFilter("subject", e.target.value)}>
              <option value="">همه درس‌ها</option>
              {Object.entries(SUBJECT_FA).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {compare.loading ? (
          <SkeletonTable rows={4} cols={5} />
        ) : compare.error ? (
          <Alert variant="warning" title="مقایسه مدارس">
            {compare.error}
          </Alert>
        ) : compare.data && compare.data.rows.length > 0 ? (
          <div className="space-y-3">
            <DataTable columns={compareColumns} rows={compare.data.rows} keyOf={(r) => r.school_id} empty={<EmptyState compact title="مدرسه‌ای یافت نشد" />} />
            <Alert variant="info">{compare.data.note_fa}</Alert>
          </div>
        ) : (
          <EmptyState compact title="مدرسه‌ای برای مقایسه نیست" description="فیلترها را تغییر دهید یا منتظر ثبت داده بمانید." />
        )}
      </Card>

      {/* ================= 4) رشد مدارس ================= */}
      <Card>
        <CardHeader
          title="وضعیت فعلی در برابر رشد"
          subtitle="وضعیت فعلی و میزان رشد دو شاخص متفاوت‌اند — مدرسه‌ای که امروز پایین‌تر است ممکن است رشد بیشتری ایجاد کرده باشد (§6)."
          icon={<IconChart size={17} />}
        />
        {growth.loading ? (
          <SkeletonTable rows={4} cols={5} />
        ) : growth.error ? (
          <Alert variant="warning" title="تحلیل رشد مدارس">
            {growth.error}
          </Alert>
        ) : growth.data ? (
          <div className="space-y-4">
            {growth.data.district.series.length >= 2 ? (
              <div className="rounded-xl border border-line bg-surface-sunken p-4">
                <p className="mb-2 text-xs font-bold text-ink">سری رشد تسط ناحیه در طول زمان</p>
                <LineChart
                  id="district-growth-series"
                  height={200}
                  format={(v) => `${fa(v, 1)}٪`}
                  points={growth.data.district.series.map((p) => p.value)}
                  labels={growth.data.district.series.map((p) => p.label)}
                />
              </div>
            ) : null}
            {growth.data.rows.length > 0 ? (
              <DataTable columns={growthColumns} rows={growth.data.rows} keyOf={(r) => r.school_id} dense empty={<EmptyState compact title="مدرسه‌ای ثبت نشده" />} />
            ) : (
              <EmptyState compact title="داده رشدی موجود نیست" />
            )}
            <Alert variant="info">{growth.data.note_fa}</Alert>
          </div>
        ) : (
          <EmptyState compact title="تحلیل رشد موجود نیست" />
        )}
      </Card>

      {/* ================= 5) تحلیل خطا ================= */}
      <Card>
        <CardHeader
          title="تحلیل خطاهای ناحیه"
          subtitle="طبقه‌بندی خطاها به تفکیک علت، مدرسه و مبحث — با قاعده حداقل جمعیت (§23)."
          icon={<IconAlert size={17} />}
        />
        {errors.loading ? (
          <SkeletonCard />
        ) : errors.error ? (
          <Alert variant="warning" title="تحلیل خطاهای ناحیه">
            {errors.error}
          </Alert>
        ) : errors.data ? (
          <div className="space-y-5">
            {errors.data.suppressed ? (
              <Alert variant="warning" title="زیر حد نصاب">
                {errors.data.note_fa}
              </Alert>
            ) : (
              <>
                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
                    <p className="text-xs font-semibold text-ink-muted">کل خطاها</p>
                    <p className="num mt-2 text-2xl font-extrabold text-ink">{fa(errors.data.total ?? 0)}</p>
                  </div>
                  <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
                    <p className="text-xs font-semibold text-ink-muted">دانش‌آموزان خطاکار</p>
                    <p className="num mt-2 text-2xl font-extrabold text-ink">{fa(errors.data.students ?? 0)}</p>
                  </div>
                  <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
                    <p className="text-xs font-semibold text-ink-muted">مباحث پرتکرار</p>
                    <p className="num mt-2 text-2xl font-extrabold text-ink">{fa(errors.data.topics.length)}</p>
                  </div>
                  <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
                    <p className="text-xs font-semibold text-ink-muted">مدارس دارای خطا</p>
                    <p className="num mt-2 text-2xl font-extrabold text-ink">
                      {fa(errors.data.schools.filter((s) => !s.suppressed && (s.total ?? 0) > 0).length)}
                    </p>
                  </div>
                </section>

                <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                  <div className="rounded-xl border border-line bg-surface-sunken p-4">
                    <p className="mb-3 text-xs font-bold text-ink">سهم هر نوع خطا</p>
                    {errors.data.causes.some((c) => (c.count ?? 0) > 0) ? (
                      <DonutChart
                        size={150}
                        thickness={20}
                        centerSubtitle="خطا"
                        data={errors.data.causes
                          .filter((c) => (c.count ?? 0) > 0)
                          .map((c) => ({ label: c.title_fa, value: c.count ?? 0 }))}
                      />
                    ) : (
                      <EmptyState compact title="خطایی ثبت نشده" />
                    )}
                  </div>
                  <div className="rounded-xl border border-line bg-surface-sunken p-4">
                    <p className="mb-3 text-xs font-bold text-ink">سهم درصدی علل</p>
                    {errors.data.causes.some((c) => (c.pct ?? 0) > 0) ? (
                      <HorizontalBars
                        data={errors.data.causes
                          .filter((c) => (c.pct ?? 0) > 0)
                          .map((c, i) => ({ label: c.title_fa, value: c.pct ?? 0, color: chartColor(i) }))}
                        format={(v) => `${fa(v, 1)}٪`}
                      />
                    ) : (
                      <EmptyState compact title="درصدی محاسبه نشده" />
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-bold text-ink">تفکیک مدارس</p>
                  <DataTable columns={errorSchoolColumns} rows={errors.data.schools} keyOf={(r) => r.school_id} dense empty={<EmptyState compact title="مدرسه‌ای یافت نشد" />} />
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-bold text-ink">مباحث پرتکرار (با خطای غالب)</p>
                  <DataTable columns={errorTopicColumns} rows={errors.data.topics} keyOf={(r) => r.topic_id} dense empty={<EmptyState compact title="مبحثی با خطا ثبت نشده" />} />
                </div>

                <Alert variant="info">{errors.data.note_fa}</Alert>
              </>
            )}
          </div>
        ) : (
          <EmptyState compact title="تحلیل خطا موجود نیست" description="هنوز خطایی در سطح ناحیه ثبت نشده است." />
        )}
      </Card>

      {/* ================= 6) کانون توجه ================= */}
      <Card>
        <CardHeader
          title="کانون توجه ناحیه"
          subtitle="مدارس و کلاس‌های نیازمند اقدام، مشکلات مشترک و هشدارها — همه پرچم‌های مدیریتی، نه ارزیابی قطعی (§9، §11، §29، §30)."
          icon={<IconTarget size={17} />}
        />
        {attention.loading ? (
          <SkeletonStats count={4} />
        ) : attention.error ? (
          <Alert variant="warning" title="کانون توجه ناحیه">
            {attention.error}
          </Alert>
        ) : attention.data ? (
          <AttentionBody
            data={attention.data}
            cols={{
              schools: attentionSchoolColumns,
              classes: attentionClassColumns,
              problems: problemColumns,
              alerts: alertColumns,
            }}
          />
        ) : (
          <EmptyState compact title="داده‌ای برای کانون توجه نیست" />
        )}
      </Card>
    </Section>
  );
}

/* ------------------------- بدنه کانون توجه (ریز تب‌ها) ------------------------- */

function AttentionBody({
  data,
  cols,
}: {
  data: AttentionResp;
  cols: {
    schools: Column<AttentionRow>[];
    classes: Column<AttentionRow>[];
    problems: Column<AttentionProblem>[];
    alerts: Column<AttentionAlert>[];
  };
}) {
  const [view, setView] = useState("schools");

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
          <p className="text-xs font-semibold text-ink-muted">رشد تسط ناحیه</p>
          <p className="num mt-2 text-2xl font-extrabold text-ink">{data.district_growth === null ? "زیر حد نصاب" : `${data.district_growth > 0 ? "+" : ""}${fa(data.district_growth, 1)} واحد`}</p>
        </div>
        {SEVERITY_FA_ORDER.slice(0, 3).map((key) => (
          <div key={key} className="rounded-2xl border border-line bg-surface p-5 shadow-soft">
            <p className="text-xs font-semibold text-ink-muted">
              مدارس {data.schools.find((s) => s.severity === key)?.severity_fa ?? SEVERITY_FA[key] ?? key}
            </p>
            <p className="num mt-2 text-2xl font-extrabold text-ink">{fa(data.severity_counts[key] ?? 0)}</p>
          </div>
        ))}
      </section>

      <div className="flex flex-wrap gap-1.5">
        {SEVERITY_FA_ORDER.map((key) => (
          <Badge key={key} tone={SEVERITY_TONE[key] ?? "neutral"}>
            {data.schools.find((s) => s.severity === key)?.severity_fa ?? SEVERITY_FA[key] ?? key}: <span className="num">{fa(data.severity_counts[key] ?? 0)}</span>
          </Badge>
        ))}
      </div>

      <Tabs
        items={[
          { key: "schools", label: "مدارس", count: data.schools.length },
          { key: "classes", label: "کلاس‌ها", count: data.classes.length },
          { key: "problems", label: "مشکلات مشترک", count: data.problems.length },
          { key: "alerts", label: "هشدارها", count: data.alerts.length },
        ]}
        value={view}
        onChange={setView}
      />

      {view === "schools" &&
        (data.schools.length === 0 ? (
          <EmptyState compact title="مدرسه‌ای در کانون توجه نیست" />
        ) : (
          <DataTable columns={cols.schools} rows={data.schools} keyOf={(r) => r.id} dense empty={<EmptyState compact title="موردی نیست" />} />
        ))}

      {view === "classes" &&
        (data.classes.length === 0 ? (
          <EmptyState compact title="کلاسی در کانون توجه نیست" />
        ) : (
          <DataTable columns={cols.classes} rows={data.classes} keyOf={(r) => r.id} dense empty={<EmptyState compact title="موردی نیست" />} />
        ))}

      {view === "problems" &&
        (data.problems.length === 0 ? (
          <EmptyState compact title="مشکل مشترکی کشف نشده" description="مشکل مشترک یعنی دست‌کم ۶۰٪ دانش‌آموزان یک پایه در چند مدرسه ضعیف باشند." />
        ) : (
          <DataTable columns={cols.problems} rows={data.problems} keyOf={(r) => r.topic_id} dense empty={<EmptyState compact title="موردی نیست" />} />
        ))}

      {view === "alerts" &&
        (data.alerts.length === 0 ? (
          <EmptyState compact title="هشداری ثبت نشده" />
        ) : (
          <DataTable columns={cols.alerts} rows={data.alerts} keyOf={(r, i) => `${r.level}-${r.title_fa}-${i}`} dense empty={<EmptyState compact title="موردی نیست" />} />
        ))}

      <Alert variant="info">{data.note_fa}</Alert>
    </div>
  );
}
