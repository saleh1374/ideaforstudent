"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { OPTION_LETTER_FA, fa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconAlert,
  IconExam,
  IconPlus,
  IconSend,
  IconSparkles,
  IconTarget,
  IconX,
} from "@/components/ui/icons";

/* ------------------------------- انواع سرور ------------------------------- */

type ClassInfo = {
  class_id: number;
  name: string;
  grade: string;
  subject: string;
  school_name: string | null;
  students_count: number;
};

type ExamSummary = {
  id: number;
  title_fa: string;
  exam_type: string;
  type_fa: string;
  mode: string;
  mode_fa: string;
  status: string;
  class_id: number | null;
  class_name: string | null;
  subject: string;
  grade: string;
  scope: string;
  opens_at: string | null;
  closes_at: string | null;
  negative_marking_k: number;
  item_count: number;
  attempts_count: number;
  goal: string | null;
  has_blueprint: boolean;
};

type BlueprintRow = {
  topic_id: number;
  topic_title: string;
  item_kind: string;
  count: number;
  diagnostic_purpose: string;
  available: number;
};

type ExamItemOut = {
  exam_item_id: number;
  item_id: number;
  order: number;
  points: number;
  body: string;
  options: Record<string, string>;
  correct_option: string;
  distractor_causes: Record<string, string>;
  difficulty: string;
  misconception: string | null;
  topic_id: number;
  topic_title: string;
};

type ExamDetail = {
  exam: ExamSummary;
  goal: string | null;
  blueprint: BlueprintRow[];
  items: ExamItemOut[];
};

/* ------------------------------- ثابت‌های محلی ------------------------------- */

const TYPE_OPTIONS = [
  { value: "class_exam", label: "آزمون کلاسی" },
  { value: "quiz", label: "آزمونک" },
  { value: "remedial", label: "آزمون ترمیمی" },
  { value: "prerequisite", label: "آزمون پیش‌نیاز" },
  { value: "diagnostic", label: "آزمون تشخیصی" },
];

const MODE_OPTIONS = [
  { value: "standard", label: "استاندارد — ورود به برد" },
  { value: "personal_diagnostic", label: "تشخیصی شخصی — فقط SLM" },
];

const KIND_FA: Record<string, string> = {
  concept_base: "مفهوم پایه",
  prerequisite_skill: "مهارت پیش‌نیاز",
  direct_application: "کاربرد مستقیم",
  reasoning: "استدلال و کاربرد ترکیبی",
};

const CAUSE_OPTIONS = [
  { value: "conceptual", label: "ضعف مفهومی" },
  { value: "prerequisite", label: "ضعف پیش‌نیاز" },
  { value: "calculation", label: "خطای محاسباتی" },
  { value: "careless", label: "بی‌دقتی" },
  { value: "time_management", label: "کمبود زمان" },
  { value: "guess", label: "حدس" },
];

const K_OPTIONS = [
  { value: "0", label: "بدون نمرهٔ منفی (k = ۰)" },
  { value: "0.25", label: "k = ۰٫۲۵" },
  { value: "0.33", label: "k = ۱/۳ (نزدیک کنکور)" },
  { value: "0.5", label: "k = ۰٫۵" },
];

const STATUS_LABEL: Record<string, { text: string; tone: Tone }> = {
  draft: { text: "پیش‌نویس", tone: "neutral" },
  published: { text: "منتشرشده", tone: "success" },
  closed: { text: "بسته", tone: "warning" },
  graded: { text: "تصحیح‌شده", tone: "info" },
};

const LETTERS = ["A", "B", "C", "D"] as const;

function errOf(e: unknown, fallback: string): { msg: string; status: number | null } {
  if (e instanceof ApiError) return { msg: e.detail ?? e.message, status: e.status };
  if (e instanceof Error) return { msg: e.message, status: null };
  return { msg: fallback, status: null };
}

/** مقدار <input type="datetime-local"> بدون ثانیه → رشتهٔ ISO بدون منطقهٔ زمانی. */
const naive = (v: string) => (v && v.length === 16 ? `${v}:00` : v || null);

const toLocalInput = (iso: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const faDate = (iso: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
};

type CustomForm = {
  topic_id: string;
  body: string;
  difficulty: string;
  points: string;
  correct: string;
  options: Record<string, string>;
  causes: Record<string, string>;
  misconception: string;
};

const emptyCustom = (topicId = ""): CustomForm => ({
  topic_id: topicId,
  body: "",
  difficulty: "medium",
  points: "1",
  correct: "A",
  options: { A: "", B: "", C: "", D: "" },
  causes: { A: "", B: "", C: "", D: "" },
  misconception: "",
});

/* ------------------------------- سازنده آزمون ------------------------------- */

export function ExamBuilderSection() {
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState("");

  // فرم ساخت
  const [title, setTitle] = useState("");
  const [classId, setClassId] = useState("");
  const [examType, setExamType] = useState("diagnostic");
  const [mode, setMode] = useState("standard");
  const [negK, setNegK] = useState("0");
  const [opensAt, setOpensAt] = useState("");
  const [closesAt, setClosesAt] = useState("");
  const [creating, setCreating] = useState(false);

  // فضای کار سازنده
  const [detail, setDetail] = useState<ExamDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [goal, setGoal] = useState("");
  const [rows, setRows] = useState<BlueprintRow[]>([]);
  const [inlineError, setInlineError] = useState("");
  const [softNotice, setSoftNotice] = useState<string | null>(null);
  const [proposing, setProposing] = useState(false);
  const [savingBp, setSavingBp] = useState(false);
  const [assembling, setAssembling] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // سؤال دستی
  const [customOpen, setCustomOpen] = useState(false);
  const [custom, setCustom] = useState<CustomForm>(emptyCustom());
  const [savingItem, setSavingItem] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, e] = await Promise.all([
        api<{ classes: ClassInfo[] }>("/teacher/me/classes"),
        api<{ exams: ExamSummary[] }>("/teacher/exams"),
      ]);
      setClasses(c.classes);
      setExams(e.exams);
      setPageError("");
      if (!classId && c.classes.length > 0) setClassId(String(c.classes[0].class_id));
    } catch (err) {
      const { msg } = errOf(err, "خطا در بارگذاری آزمون‌ها");
      setPageError(msg);
    } finally {
      setLoading(false);
    }
  }, [classId]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setInlineError("");
    if (!title.trim() || !classId) {
      toast("عنوان و کلاس الزامی است.", "warning");
      return;
    }
    setCreating(true);
    try {
      const res = await api<{ ok: boolean; exam: ExamSummary }>("/teacher/exams", {
        method: "POST",
        json: {
          title_fa: title.trim(),
          class_id: Number(classId),
          exam_type: examType,
          mode,
          negative_marking_k: Number(negK),
          opens_at: naive(opensAt),
          closes_at: naive(closesAt),
        },
      });
      toast("پیش‌نویس آزمون ساخته شد؛ حالا هدف را بنویسید.", "success");
      setTitle("");
      setOpensAt("");
      setClosesAt("");
      await load();
      await openExam(res.exam.id);
    } catch (err) {
      const { msg, status } = errOf(err, "خطا در ساخت آزمون");
      if (status === 403) toast(msg, "error");
      else setInlineError(msg); // 400 → درون‌خطی
    } finally {
      setCreating(false);
    }
  }

  async function openExam(id: number) {
    setDetail(null);
    setDetailLoading(true);
    setInlineError("");
    setSoftNotice(null);
    try {
      const d = await api<ExamDetail>(`/teacher/exams/${id}`);
      setDetail(d);
      setGoal(d.goal ?? "");
      setRows(d.blueprint);
    } catch (err) {
      const { msg, status } = errOf(err, "خطا در باز کردن آزمون");
      if (status === 403 || status === 409) toast(msg, "error");
      else setInlineError(msg);
    } finally {
      setDetailLoading(false);
    }
  }

  async function refreshDetail() {
    if (!detail) return;
    const d = await api<ExamDetail>(`/teacher/exams/${detail.exam.id}`);
    setDetail(d);
    setGoal(d.goal ?? "");
    setRows(d.blueprint);
  }

  function handleError(err: unknown, fallback: string, on409?: () => void) {
    const { msg, status } = errOf(err, fallback);
    if (status === 409) {
      toast(msg, "error");
      on409?.();
    } else if (status === 400) {
      setInlineError(msg);
    } else if (status === 403) {
      toast(msg, "error");
    } else {
      toast(msg, "error");
    }
  }

  async function propose() {
    if (!detail) return;
    setInlineError("");
    setSoftNotice(null);
    setProposing(true);
    try {
      const res = await api<{ ok: boolean; rows: BlueprintRow[]; summary_fa: string }>(
        `/teacher/exams/${detail.exam.id}/blueprint`,
        { method: "POST", json: { goal } }
      );
      setRows(res.rows);
      toast(res.summary_fa, "success");
      await refreshDetail();
    } catch (err) {
      handleError(err, "خطا در پیشنهاد بلوپرینت");
    } finally {
      setProposing(false);
    }
  }

  async function saveBlueprint() {
    if (!detail) return;
    setSavingBp(true);
    setInlineError("");
    try {
      await api(`/teacher/exams/${detail.exam.id}`, {
        method: "PATCH",
        json: {
          blueprint: rows.map((r) => ({
            topic_id: r.topic_id,
            count: Number(r.count) || 1,
            item_kind: r.item_kind,
            diagnostic_purpose: r.diagnostic_purpose,
          })),
        },
      });
      toast("بلوپرینت ذخیره شد.", "success");
      await refreshDetail();
    } catch (err) {
      handleError(err, "خطا در ذخیرهٔ بلوپرینت");
    } finally {
      setSavingBp(false);
    }
  }

  async function assemble() {
    if (!detail) return;
    setAssembling(true);
    setInlineError("");
    setSoftNotice(null);
    try {
      const res = await api<{ ok: boolean; attached: number; reason: string | null }>(
        `/teacher/exams/${detail.exam.id}/items`,
        { method: "POST", json: { source: "blueprint" } }
      );
      if (res.ok) toast(`${fa(res.attached)} سؤال از بانک متصل شد.`, "success");
      else {
        // پاسخ نرم سرور: {ok:false, reason} — دلیل باید دیده شود
        setSoftNotice(res.reason ?? "کسری بانک سؤال");
        toast(`${fa(res.attached)} سؤال متصل شد؛ بانک کسری دارد.`, "warning");
      }
      await refreshDetail();
    } catch (err) {
      handleError(err, "خطا در افزودن سؤال‌ها");
    } finally {
      setAssembling(false);
    }
  }

  async function saveCustom() {
    if (!detail) return;
    setSavingItem(true);
    setInlineError("");
    try {
      const causes: Record<string, string> = {};
      LETTERS.forEach((l) => {
        if (l !== custom.correct && custom.causes[l]) causes[l] = custom.causes[l];
      });
      await api(`/teacher/exams/${detail.exam.id}/items`, {
        method: "POST",
        json: {
          source: "custom",
          body: custom.body,
          options: { ...custom.options },
          correct_option: custom.correct,
          distractor_causes: causes,
          topic_id: custom.topic_id ? Number(custom.topic_id) : null,
          points: Number(custom.points) || 1,
          difficulty: custom.difficulty,
          misconception: custom.misconception || null,
        },
      });
      toast("سؤال دستی به آزمون اضافه شد.", "success");
      setCustomOpen(false);
      setCustom(emptyCustom());
      await refreshDetail();
    } catch (err) {
      const { msg, status } = errOf(err, "خطا در افزودن سؤال");
      if (status === 400) setInlineError(msg);
      else toast(msg, "error");
    } finally {
      setSavingItem(false);
    }
  }

  async function patchItem(examItemId: number, json: Record<string, unknown>) {
    if (!detail) return;
    try {
      await api(`/teacher/exams/${detail.exam.id}/items/${examItemId}`, { method: "PATCH", json });
      await refreshDetail();
    } catch (err) {
      handleError(err, "خطا در ویرایش سؤال", () => refreshDetail());
    }
  }

  async function removeItem(examItemId: number) {
    if (!detail) return;
    if (!window.confirm("این سؤال از آزمون حذف شود؟")) return;
    try {
      await api(`/teacher/exams/${detail.exam.id}/items/${examItemId}`, { method: "DELETE" });
      toast("سؤال حذف شد.", "success");
      await refreshDetail();
    } catch (err) {
      handleError(err, "خطا در حذف سؤال", () => refreshDetail());
    }
  }

  async function saveWindow() {
    if (!detail) return;
    setInlineError("");
    try {
      await api(`/teacher/exams/${detail.exam.id}`, {
        method: "PATCH",
        json: {
          opens_at: naive(opensAt),
          closes_at: naive(closesAt),
          negative_marking_k: Number(negK),
        },
      });
      toast("زمان‌بندی و نمرهٔ منفی ذخیره شد.", "success");
      await refreshDetail();
    } catch (err) {
      handleError(err, "خطا در ذخیرهٔ زمان‌بندی", () => refreshDetail());
    }
  }

  async function publish() {
    if (!detail) return;
    setPublishing(true);
    setInlineError("");
    try {
      const res = await api<{ ok: boolean; note_fa: string }>(
        `/teacher/exams/${detail.exam.id}/publish`,
        { method: "POST" }
      );
      toast(res.note_fa, "success");
      await refreshDetail();
      await load();
    } catch (err) {
      const { msg, status } = errOf(err, "خطا در انتشار آزمون");
      if (status === 400) setInlineError(msg);
      else if (status === 409) {
        toast(msg, "error");
        await refreshDetail();
      } else toast(msg, "error");
    } finally {
      setPublishing(false);
    }
  }

  /* ------------------------------ فهرست ------------------------------ */

  const listColumns: Column<ExamSummary>[] = [
    {
      key: "title",
      header: "آزمون",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.title_fa}</p>
          <p className="text-[11px] text-ink-faint">
            {row.class_name ? `کلاس ${row.class_name}` : "—"} · {subjectFa(row.subject)} · {row.type_fa}
            {row.goal ? ` · هدف: ${row.goal.slice(0, 40)}${row.goal.length > 40 ? "…" : ""}` : ""}
          </p>
        </div>
      ),
    },
    {
      key: "mode",
      header: "حالت",
      align: "center",
      render: (row) => (
        <Badge tone={row.mode === "standard" ? "primary" : "accent"}>{row.mode_fa}</Badge>
      ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => {
        const s = STATUS_LABEL[row.status] ?? { text: row.status, tone: "neutral" as Tone };
        return (
          <Badge tone={s.tone} dot>
            {s.text}
          </Badge>
        );
      },
    },
    {
      key: "counts",
      header: "سؤال / تلاش",
      align: "center",
      render: (row) => (
        <span className="num text-xs font-bold text-ink">
          {fa(row.item_count)} / {fa(row.attempts_count)}
        </span>
      ),
    },
    {
      key: "window",
      header: "مهلت",
      align: "center",
      render: (row) => (
        <span className="num text-[11px] text-ink-faint">
          {faDate(row.opens_at)} → {faDate(row.closes_at)}
        </span>
      ),
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (row) => (
        <Button size="sm" variant="soft" onClick={() => openExam(row.id)} icon={<IconTarget size={14} />}>
          {row.status === "draft" ? "ادامه ساخت" : "مشاهده"}
        </Button>
      ),
    },
  ];

  /* ------------------------------ فضای کار ------------------------------ */

  if (detailLoading && !detail) return <SkeletonTable rows={4} cols={5} />;

  if (detail) {
    const { exam } = detail;
    const isDraft = exam.status === "draft";
    const topicsForCustom = Array.from(
      new Map(
        [...rows.map((r) => [r.topic_id, r.topic_title] as const), ...detail.items.map((it) => [it.topic_id, it.topic_title] as const)]
      ).entries()
    );
    const bpTotal = rows.reduce((s, r) => s + (Number(r.count) || 0), 0);

    return (
      <div className="space-y-6">
        {/* سربرگ */}
        <Card variant="brand" className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-extrabold text-primary-900">{exam.title_fa}</h2>
                <Badge tone="neutral">{exam.type_fa}</Badge>
                <Badge tone={exam.mode === "standard" ? "primary" : "accent"}>{exam.mode_fa}</Badge>
                <Badge tone={STATUS_LABEL[exam.status]?.tone ?? "neutral"} dot>
                  {STATUS_LABEL[exam.status]?.text ?? exam.status}
                </Badge>
              </div>
              <p className="text-xs text-primary-700">
                کلاس {exam.class_name ?? "—"} · {subjectFa(exam.subject)} · نمرهٔ منفی k = {fa(exam.negative_marking_k, 2)} ·{" "}
                {fa(exam.item_count)} سؤال · {fa(exam.attempts_count)} تلاش
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDetail(null);
                  setSoftNotice(null);
                  setInlineError("");
                  load();
                }}
              >
                بازگشت به فهرست
              </Button>
              {!isDraft && (
                <Button size="sm" variant="outline" onClick={() => refreshDetail()}>
                  تازه‌سازی
                </Button>
              )}
            </div>
          </div>
        </Card>

        {inlineError && (
          <Alert variant="danger" title="خطا">
            {inlineError}
          </Alert>
        )}
        {softNotice && (
          <Alert variant="warning" title="کسری بانک سؤال">
            {softNotice} — می‌توانید سؤال دستی اضافه کنید یا از سؤال‌های موجود استفاده کنید.
          </Alert>
        )}
        {!isDraft && (
          <Alert variant="success" title="آزمون منتشر شده">
            پس از انتشار، سؤال‌ها و زمان‌بندی قفل است؛ نتایج در بخش «تحلیل آزمون» قابل مشاهده است.
          </Alert>
        )}

        {/* مرحله ۱: هدف → بلوپرینت */}
        <Card className="space-y-4">
          <CardHeader
            title="مرحله ۱ — هدف آزمون (ساخت بر پایهٔ هدف)"
            subtitle="هدف را به زبان ساده بنویسید؛ سیستم بلوپرینت را از مباحث کاتالوگ و پیش‌نیازها پیشنهاد می‌دهد (§8.2)."
            icon={<IconSparkles size={17} />}
          />
          <Textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            disabled={!isDraft}
            placeholder="مثلاً: می‌خواهم بفهمم چرا بچه‌ها در کاربرد مشتق مشکل دارند."
          />
          {isDraft && (
            <Button loading={proposing} onClick={propose} disabled={!goal.trim()} icon={<IconSparkles size={15} />}>
              پیشنهاد بلوپرینت از هدف
            </Button>
          )}
        </Card>

        {/* مرحله ۲: بلوپرینت قابل ویرایش */}
        <Section
          title="مرحله ۲ — بلوپرینت پیشنهادی"
          subtitle={
            rows.length > 0
              ? `${fa(rows.length)} ردیف · مجموع ${fa(bpTotal)} سؤال — تعداد و توضیح هر ردیف قابل ویرایش است.`
              : "هنوز بلوپرینتی ثبت نشده است."
          }
          action={
            isDraft && rows.length > 0 ? (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" loading={savingBp} onClick={saveBlueprint}>
                  ذخیرهٔ بلوپرینت
                </Button>
                <Button size="sm" variant="primary" loading={assembling} onClick={assemble} icon={<IconPlus size={14} />}>
                  افزودن سؤال‌ها از بانک
                </Button>
              </div>
            ) : undefined
          }
        >
          {rows.length === 0 ? (
            <EmptyState
              compact
              icon={<IconTarget size={24} />}
              title="بلوپرینتی ثبت نشده"
              description="در مرحله ۱ هدف را بنویسید تا ردیف‌های پیشنهادی ساخته شود."
            />
          ) : (
            <DataTable
              columns={[
                { key: "topic", header: "مبحث", render: (r: BlueprintRow) => <span className="font-semibold text-ink">{r.topic_title}</span> },
                {
                  key: "kind",
                  header: "نوع سؤال",
                  align: "center",
                  render: (r: BlueprintRow) => <Badge tone="primary">{KIND_FA[r.item_kind] ?? r.item_kind}</Badge>,
                },
                {
                  key: "count",
                  header: "تعداد",
                  align: "center",
                  width: "88px",
                  render: (r: BlueprintRow, i: number) => (
                    <Input
                      type="number"
                      min={1}
                      max={20}
                      value={String(r.count)}
                      disabled={!isDraft}
                      className="px-2 py-1 text-center"
                      onChange={(e) =>
                        setRows((prev) => prev.map((x, idx) => (idx === i ? { ...x, count: Number(e.target.value) } : x)))
                      }
                    />
                  ),
                },
                {
                  key: "purpose",
                  header: "هدف تشخیصی",
                  render: (r: BlueprintRow, i: number) => (
                    <Input
                      value={r.diagnostic_purpose}
                      disabled={!isDraft}
                      className="px-2.5 py-1.5 text-xs"
                      onChange={(e) =>
                        setRows((prev) => prev.map((x, idx) => (idx === i ? { ...x, diagnostic_purpose: e.target.value } : x)))
                      }
                    />
                  ),
                },
                {
                  key: "avail",
                  header: "در دسترس",
                  align: "center",
                  render: (r: BlueprintRow) => (
                    <span className={`num text-xs font-bold ${r.available < Number(r.count) ? "text-warning-600" : "text-ink"}`}>
                      {fa(r.available)} / {fa(r.count)}
                    </span>
                  ),
                },
                {
                  key: "rm",
                  header: "",
                  align: "center",
                  width: "44px",
                  render: (_r: BlueprintRow, i: number) =>
                    isDraft ? (
                      <button
                        onClick={() => setRows((prev) => prev.filter((_, idx) => idx !== i))}
                        className="grid h-7 w-7 place-items-center rounded-lg text-ink-faint transition hover:bg-danger-50 hover:text-danger-600"
                        aria-label="حذف ردیف"
                      >
                        <IconX size={14} />
                      </button>
                    ) : null,
                },
              ]}
              rows={rows}
              keyOf={(_r, i) => i}
              dense
            />
          )}
        </Section>

        {/* مرحله ۳: سؤال‌ها */}
        <Section
          title="مرحله ۳ — سؤال‌های آزمون"
          subtitle={`${fa(detail.items.length)} سؤال متصل — پاسخ درست و علت هر گزینهٔ غلط فقط برای شما نمایش داده می‌شود.`}
          action={
            isDraft ? (
              <div className="flex gap-2">
                <Button size="sm" variant="soft" onClick={() => {
                  setCustom(emptyCustom(topicsForCustom[0]?.[0] ? String(topicsForCustom[0][0]) : ""));
                  setCustomOpen(true);
                }} icon={<IconPlus size={14} />}>
                  سؤال دستی
                </Button>
                <Button size="sm" variant="outline" loading={assembling} onClick={assemble} icon={<IconPlus size={14} />}>
                  از بانک (بلوپرینت)
                </Button>
              </div>
            ) : undefined
          }
        >
          {detail.items.length === 0 ? (
            <EmptyState
              compact
              icon={<IconExam size={24} />}
              title="هنوز سؤالی اضافه نشده"
              description="با دکمهٔ «از بانک (بلوپرینت)» سؤال‌ها را مونتاژ کنید یا سؤال دستی بسازید."
            />
          ) : (
            <div className="space-y-3">
              {detail.items.map((it) => (
                <Card key={it.exam_item_id} className="space-y-3">
                  <div className="flex items-start gap-3">
                    <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-xs font-bold text-primary-700">
                      {fa(it.order)}
                    </span>
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="text-sm font-semibold leading-7 text-ink">{it.body}</p>
                      <p className="text-[11px] text-ink-faint">
                        {it.topic_title} · {subjectFa(exam.subject)}
                        {it.misconception ? ` · کج‌فهمی: ${it.misconception}` : ""}
                      </p>
                    </div>
                    {isDraft && (
                      <button
                        onClick={() => removeItem(it.exam_item_id)}
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-faint transition hover:bg-danger-50 hover:text-danger-600"
                        aria-label="حذف سؤال"
                      >
                        <IconX size={15} />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {LETTERS.map((l) => {
                      const correct = l === it.correct_option;
                      const cause = it.distractor_causes[l];
                      return (
                        <div
                          key={l}
                          className={`flex items-start gap-2 rounded-xl border px-3 py-2 text-xs ${
                            correct ? "border-success-200 bg-success-50" : "border-line bg-surface"
                          }`}
                        >
                          <span
                            className={`num grid h-5 w-5 shrink-0 place-items-center rounded-md text-[10px] font-bold ${
                              correct ? "bg-success-600 text-white" : "bg-slate-100 text-ink-muted"
                            }`}
                          >
                            {OPTION_LETTER_FA[l]}
                          </span>
                          <span className="leading-6 text-ink">
                            {it.options[l]}
                            {correct && <span className="mr-1 text-[10px] font-bold text-success-600">✓ پاسخ درست</span>}
                            {!correct && cause && (
                              <span className="mr-1 text-[10px] font-bold text-warning-600">
                                علت: {CAUSE_OPTIONS.find((c) => c.value === cause)?.label ?? cause}
                              </span>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <Badge tone="neutral">دشواری: {it.difficulty === "easy" ? "آسان" : it.difficulty === "hard" ? "سخت" : "متوسط"}</Badge>
                    <label className="flex items-center gap-2 text-xs font-semibold text-ink-muted">
                      امتیاز
                      <Input
                        type="number"
                        min={0.5}
                        step={0.5}
                        max={100}
                        value={String(it.points)}
                        disabled={!isDraft}
                        className="w-20 px-2 py-1 text-center"
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          setDetail((prev) =>
                            prev
                              ? { ...prev, items: prev.items.map((x) => (x.exam_item_id === it.exam_item_id ? { ...x, points: v } : x)) }
                              : prev
                          );
                        }}
                        onBlur={() => patchItem(it.exam_item_id, { points: it.points })}
                      />
                    </label>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </Section>

        {/* مرحله ۴: زمان‌بندی و انتشار */}
        {isDraft && (
          <Card className="space-y-4">
            <CardHeader
              title="مرحله ۴ — زمان‌بندی و انتشار"
              subtitle="استاندارد وارد برد می‌شود؛ تشخیصی شخصی فقط SLM را به‌روز می‌کند (§8.3)."
              icon={<IconSend size={17} />}
            />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="زمان شروع">
                <Input type="datetime-local" value={opensAt} onChange={(e) => setOpensAt(e.target.value)} />
              </Field>
              <Field label="زمان پایان">
                <Input type="datetime-local" value={closesAt} onChange={(e) => setClosesAt(e.target.value)} />
              </Field>
              <Field label="نمرهٔ منفی (k)" hint="§8.4 — برای هر پایه قابل تنظیم">
                <Select value={negK} onChange={(e) => setNegK(e.target.value)}>
                  {K_OPTIONS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="flex items-end gap-2">
                <Button variant="outline" onClick={saveWindow} className="flex-1">
                  ذخیرهٔ زمان‌بندی
                </Button>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface-sunken px-4 py-3">
              <p className="text-xs text-ink-muted">
                {detail.items.length === 0
                  ? "برای انتشار باید دست‌کم یک سؤال اضافه کنید."
                  : `${fa(detail.items.length)} سؤال آمادهٔ انتشار است.`}
              </p>
              <Button
                loading={publishing}
                disabled={detail.items.length === 0}
                onClick={publish}
                icon={<IconSend size={15} />}
              >
                انتشار آزمون
              </Button>
            </div>
          </Card>
        )}

        {/* مودال سؤال دستی */}
        <Modal
          open={customOpen}
          onClose={() => setCustomOpen(false)}
          title="افزودن سؤال دستی"
          size="lg"
          footer={
            <>
              <Button variant="ghost" onClick={() => setCustomOpen(false)}>
                انصراف
              </Button>
              <Button loading={savingItem} onClick={saveCustom} icon={<IconPlus size={15} />}>
                افزودن به آزمون
              </Button>
            </>
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="مبحث" required>
                <Select value={custom.topic_id} onChange={(e) => setCustom({ ...custom, topic_id: e.target.value })}>
                  <option value="">انتخاب مبحث…</option>
                  {topicsForCustom.map(([tid, ttitle]) => (
                    <option key={tid} value={String(tid)}>
                      {ttitle}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="دشواری">
                <Select value={custom.difficulty} onChange={(e) => setCustom({ ...custom, difficulty: e.target.value })}>
                  <option value="easy">آسان</option>
                  <option value="medium">متوسط</option>
                  <option value="hard">سخت</option>
                </Select>
              </Field>
              <Field label="امتیاز">
                <Input
                  type="number"
                  min={0.5}
                  step={0.5}
                  value={custom.points}
                  onChange={(e) => setCustom({ ...custom, points: e.target.value })}
                />
              </Field>
            </div>

            <Field label="متن سؤال" required>
              <Textarea value={custom.body} onChange={(e) => setCustom({ ...custom, body: e.target.value })} />
            </Field>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-bold text-ink">گزینه‌ها و علت هر گزینهٔ غلط</span>
                <Field label="گزینهٔ درست" className="w-36">
                  <Select value={custom.correct} onChange={(e) => setCustom({ ...custom, correct: e.target.value })}>
                    {LETTERS.map((l) => (
                      <option key={l} value={l}>
                        {OPTION_LETTER_FA[l]}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              {LETTERS.map((l) => {
                const correct = l === custom.correct;
                return (
                  <div key={l} className="grid grid-cols-1 gap-2 sm:grid-cols-5">
                    <div className="flex items-center gap-2 sm:col-span-3">
                      <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100 text-xs font-bold text-ink-muted">
                        {OPTION_LETTER_FA[l]}
                      </span>
                      <Input
                        value={custom.options[l]}
                        placeholder={`گزینه ${OPTION_LETTER_FA[l]}`}
                        onChange={(e) => setCustom({ ...custom, options: { ...custom.options, [l]: e.target.value } })}
                      />
                    </div>
                    <div className="sm:col-span-2">
                      {correct ? (
                        <div className="rounded-xl bg-success-50 px-3 py-2.5 text-center text-xs font-bold text-success-700">
                          پاسخ درست
                        </div>
                      ) : (
                        <Select
                          value={custom.causes[l]}
                          aria-label={`علت گزینه ${OPTION_LETTER_FA[l]}`}
                          onChange={(e) => setCustom({ ...custom, causes: { ...custom.causes, [l]: e.target.value } })}
                        >
                          <option value="">علت خطا (اختیاری)…</option>
                          {CAUSE_OPTIONS.map((c) => (
                            <option key={c.value} value={c.value}>
                              {c.label}
                            </option>
                          ))}
                        </Select>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            <Field label="کج‌فهمی مرتبط (اختیاری)" hint="مثلاً: اشتباه ۲^n با n — در تحلیل پس از آزمون نمایش داده می‌شود.">
              <Input value={custom.misconception} onChange={(e) => setCustom({ ...custom, misconception: e.target.value })} />
            </Field>

            {inlineError && (
              <Alert variant="danger" title="خطا">
                {inlineError}
              </Alert>
            )}
          </div>
        </Modal>
      </div>
    );
  }

  /* ------------------------------ فهرست + ساخت ------------------------------ */

  return (
    <div className="space-y-6">
      {pageError && (
        <Alert variant="danger" title="خطا">
          {pageError}
        </Alert>
      )}
      {inlineError && (
        <Alert variant="danger" title="خطا در ساخت">
          {inlineError}
        </Alert>
      )}

      <Card>
        <CardHeader
          title="ساخت آزمون جدید"
          subtitle="نوع آزمون (§8.1)، حالت برگزاری (§8.3) و ضریب نمرهٔ منفی (§8.4) را انتخاب کنید؛ سؤال‌ها در مرحلهٔ بعد."
          icon={<IconPlus size={17} />}
        />
        {classes.length === 0 && !loading ? (
          <EmptyState compact title="کلاسی به شما تخصیص نیافته" description="با مدیر مدرسه هماهنگ کنید." />
        ) : (
          <form onSubmit={create} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="عنوان آزمون" required>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="مثلاً: آزمون تشخیصی مبحث…" />
            </Field>
            <Field label="کلاس" required>
              <Select value={classId} onChange={(e) => setClassId(e.target.value)}>
                <option value="">انتخاب کلاس…</option>
                {classes.map((c) => (
                  <option key={c.class_id} value={String(c.class_id)}>
                    کلاس {c.name} — {subjectFa(c.subject)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="نوع آزمون">
              <Select value={examType} onChange={(e) => setExamType(e.target.value)}>
                {TYPE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="حالت برگزاری">
              <Select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODE_OPTIONS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="زمان شروع (اختیاری)">
              <Input type="datetime-local" value={opensAt} onChange={(e) => setOpensAt(e.target.value)} />
            </Field>
            <Field label="زمان پایان (اختیاری)">
              <Input type="datetime-local" value={closesAt} onChange={(e) => setClosesAt(e.target.value)} />
            </Field>
            <Field label="نمرهٔ منفی (k)">
              <Select value={negK} onChange={(e) => setNegK(e.target.value)}>
                {K_OPTIONS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex items-end">
              <Button type="submit" loading={creating} className="w-full" icon={<IconExam size={15} />}>
                ساخت پیش‌نویس
              </Button>
            </div>
          </form>
        )}
      </Card>

      <Section title="آزمون‌های من" subtitle="هر آزمون: هدف ← بلوپرینت ← سؤال‌ها ← انتشار؛ سپس در تب «تحلیل آزمون».">
        {loading ? (
          <SkeletonTable rows={3} cols={5} />
        ) : (
          <DataTable
            columns={listColumns}
            rows={exams}
            keyOf={(r) => r.id}
            empty={
              <EmptyState
                compact
                icon={<IconAlert size={24} />}
                title="هنوز آزمونی نساخته‌اید"
                description="با فرم بالا اولین پیش‌نویس آزمون کلاس خود را بسازید."
              />
            }
          />
        )}
      </Section>

      {!loading && exams.some((e) => e.attempts_count > 0) && (
        <Alert variant="info" title="نکته">
          برای دیدن تحلیل هر سؤال (دشواری تجربی، قدرت تفکیک و «نیازمند بازبینی») به تب «تحلیل آزمون» بروید.
        </Alert>
      )}
    </div>
  );
}
