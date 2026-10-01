"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SUBJECT_FA, fa, subjectFa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { Modal } from "@/components/ui/modal";
import { StatCard } from "@/components/ui/stat";
import {
  IconChart,
  IconLayers,
  IconRefresh,
  IconSchool,
  IconShield,
  IconTarget,
  IconUsers,
} from "@/components/ui/icons";

/** عوامل زمینه‌ای §8 — کلید → توضیح فارسی (از بک‌اند هم می‌آید). */
type ContextFactors = {
  baseline_mastery: number | null;
  students_count: number;
  attendance_pct: number | null;
  exam_difficulty_avg: number | null;
  prereq_weak_ratio: number | null;
  sessions_recorded: number;
  practice_evidence: number;
  plan_completion_pct: number | null;
  factor_labels_fa: Record<string, string>;
  attendance_note_fa: string;
};

type CompareRow = {
  class_id: number;
  class_name: string;
  grade: string;
  subject: string;
  teacher_id: number;
  teacher_name: string | null;
  students_with_data: number;
  mastery: number | null;
  retention: number | null;
  growth: number | null;
  total_errors: number;
  weak_topics: { topic_id: number; title: string; weak_students: number }[];
  suppressed: boolean;
  context: ContextFactors;
};

type TeacherRow = {
  teacher_id: number;
  teacher_name: string | null;
  classes_count: number;
  classes: { class_id: number; class_name: string; suppressed: boolean }[];
  avg_mastery: number | null;
  avg_retention: number | null;
  avg_growth: number | null;
  students_with_data: number;
  suppressed: boolean;
};

type CompareData = {
  school_id: number;
  subject: string;
  comparison_valid: boolean;
  min_group: number;
  min_group_note: string;
  raw_score_note_fa: string;
  weighting_note_fa: string;
  rows: CompareRow[];
  teachers: TeacherRow[];
};

const SUBJECT_KEYS = Object.keys(SUBJECT_FA);

function pct(v: number | null, digits = 0): string {
  return v === null ? "—" : `${fa(v, digits)}٪`;
}

function signed(v: number | null): string {
  return v === null ? "—" : `${v > 0 ? "+" : ""}${fa(v)}`;
}

export function TeachersCompareSection({ schoolId }: { schoolId: number | null }) {
  const [subject, setSubject] = useState("math");
  const [data, setData] = useState<CompareData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [contextRow, setContextRow] = useState<CompareRow | null>(null);

  const load = useCallback(async (sid: number | null, subj: string) => {
    if (sid === null) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setData(await api<CompareData>(`/admin/school/${sid}/teachers-compare?subject=${encodeURIComponent(subj)}`));
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : "خطا در دریافت مقایسه");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(schoolId, subject);
  }, [schoolId, subject, load]);

  const teacherColumns: Column<TeacherRow>[] = [
    {
      key: "name",
      header: "معلم",
      render: (row) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{row.teacher_name ?? "—"}</p>
          <p className="text-[11px] text-ink-faint">
            {fa(row.classes_count)} کلاس: {row.classes.map((c) => c.class_name).join("، ")}
          </p>
        </div>
      ),
    },
    {
      key: "mastery",
      header: "تسط میانگین",
      align: "center",
      render: (row) =>
        row.suppressed ? (
          <Badge tone="neutral">زیر حد نصاب</Badge>
        ) : (
          <span className="num font-bold text-ink">{pct(row.avg_mastery)}</span>
        ),
    },
    {
      key: "growth",
      header: "رشد",
      align: "center",
      render: (row) => (
        <span className={`num ${row.avg_growth !== null && row.avg_growth < 0 ? "text-danger-600" : "text-ink-muted"}`}>
          {signed(row.avg_growth)}
        </span>
      ),
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num">{pct(row.avg_retention === null ? null : row.avg_retention * 100)}</span>,
    },
    {
      key: "students",
      header: "دانش‌آموز",
      align: "center",
      render: (row) => <span className="num">{fa(row.students_with_data)}</span>,
    },
  ];

  const classColumns: Column<CompareRow>[] = [
    {
      key: "class",
      header: "کلاس",
      render: (row) => (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{row.class_name}</span>
          {row.suppressed && <Badge tone="neutral">زیر حد نصاب</Badge>}
        </div>
      ),
    },
    { key: "teacher", header: "معلم", align: "center", render: (row) => row.teacher_name ?? "—" },
    {
      key: "mastery",
      header: "تسط",
      align: "center",
      render: (row) => <span className="num font-bold text-ink">{row.suppressed ? "—" : pct(row.mastery)}</span>,
    },
    {
      key: "growth",
      header: "رشد",
      align: "center",
      render: (row) => (
        <span className={`num ${row.growth !== null && row.growth < 0 ? "text-danger-600" : "text-ink-muted"}`}>
          {row.suppressed ? "—" : signed(row.growth)}
        </span>
      ),
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num">{row.suppressed ? "—" : pct(row.retention === null ? null : row.retention * 100)}</span>,
    },
    { key: "errors", header: "خطاها", align: "center", render: (row) => <span className="num">{fa(row.total_errors)}</span> },
    { key: "n", header: "دارای داده", align: "center", render: (row) => <span className="num">{fa(row.students_with_data)}</span> },
    {
      key: "ctx",
      header: "",
      align: "end",
      render: (row) => (
        <Button size="sm" variant="soft" icon={<IconLayers size={14} />} onClick={() => setContextRow(row)}>
          عوامل زمینه‌ای
        </Button>
      ),
    },
  ];

  const ctx = contextRow?.context ?? null;
  const ctxEntries = ctx
    ? (Object.keys(ctx.factor_labels_fa) as (keyof ContextFactors)[]).map((k) => ({
        label: ctx.factor_labels_fa[k],
        value:
          k === "attendance_pct"
            ? "—"
            : k === "prereq_weak_ratio"
              ? ctx.prereq_weak_ratio === null
                ? "—"
                : `${fa(ctx.prereq_weak_ratio * 100)}٪`
              : k === "plan_completion_pct"
                ? pct(ctx.plan_completion_pct)
                : k === "exam_difficulty_avg"
                  ? ctx.exam_difficulty_avg === null
                    ? "—"
                    : fa(ctx.exam_difficulty_avg, 2)
                  : String(ctx[k as keyof ContextFactors] ?? "—"),
      }))
    : [];

  return (
    <Section
      title="مقایسه معلم با معلم — با احتیاط"
      subtitle="تسط، رشد و ماندگاری هر کلاس در کنار عوامل زمینه‌ای — بدون امتیاز کلی برای معلم."
      action={
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="rounded-xl border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-ink"
          >
            {SUBJECT_KEYS.map((k) => (
              <option key={k} value={k}>
                {SUBJECT_FA[k]}
              </option>
            ))}
          </select>
          <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => load(schoolId, subject)}>
            تازه‌سازی
          </Button>
        </div>
      }
    >
      {error && (
        <Alert variant="danger" title="خطا در دریافت مقایسه">
          {error}
        </Alert>
      )}

      {data && !data.comparison_valid && <Alert variant="warning">{data.min_group_note}</Alert>}
      <Alert variant="info" title="چرا مقایسه خام ممنوع است؟">
        {data?.raw_score_note_fa ?? "Raw Score ≠ Teacher Quality"}
      </Alert>

      {loading ? (
        <SkeletonTable rows={4} cols={5} />
      ) : (
        <>
          {data && data.teachers.length > 0 && (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <StatCard
                  label="معلم‌های این درس"
                  value={fa(data.teachers.length)}
                  tone="primary"
                  icon={<IconUsers size={20} />}
                  hint={subjectFa(data.subject)}
                />
                <StatCard
                  label="کلاس‌های مقایسه‌پذیر"
                  value={fa(data.rows.filter((r) => !r.suppressed).length)}
                  tone="accent"
                  icon={<IconSchool size={20} />}
                  hint={`حداقل ${fa(data.min_group)} دانش‌آموز`}
                />
                <StatCard
                  label="کلاس‌های زیر حد نصاب"
                  value={fa(data.rows.filter((r) => r.suppressed).length)}
                  tone="warning"
                  icon={<IconShield size={20} />}
                  hint="اعدادشان مخفی است"
                />
                <StatCard
                  label="شاخص اصلی"
                  value="تسط/رشد"
                  tone="success"
                  icon={<IconTarget size={20} />}
                  hint="بدون امتیاز کلی"
                />
              </div>

              <div className="rounded-2xl border border-line bg-surface p-1">
                <p className="px-3 pt-2 text-xs font-bold text-ink">تجمیع در سطح معلم ({subjectFa(data.subject)})</p>
                <DataTable columns={teacherColumns} rows={data.teachers} keyOf={(t) => t.teacher_id} empty={<EmptyState compact title="معلمی ثبت نشده" />} />
              </div>
            </>
          )}

          <div className="rounded-2xl border border-line bg-surface p-1">
            <p className="px-3 pt-2 text-xs font-bold text-ink">ردیف هر کلاس (شکل ۷ سند)</p>
            <DataTable
              columns={classColumns}
              rows={data?.rows ?? []}
              keyOf={(r) => r.class_id}
              empty={<EmptyState compact icon={<IconChart size={24} />} title="کلاسی با این درس فعال نیست" />}
            />
          </div>

          <p className="text-[11px] leading-6 text-ink-faint">{data?.weighting_note_fa}</p>
        </>
      )}

      {/* ——— مودال عوامل زمینه‌ای ——— */}
      <Modal
        open={contextRow !== null}
        onClose={() => setContextRow(null)}
        title={contextRow ? `عوامل زمینه‌ای — کلاس ${contextRow.class_name}` : ""}
        size="md"
        footer={
          <Button variant="ghost" onClick={() => setContextRow(null)}>
            بستن
          </Button>
        }
      >
        {contextRow && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge tone="primary">معلم: {contextRow.teacher_name ?? "—"}</Badge>
              <Badge tone="neutral">دارای داده: {fa(contextRow.students_with_data)}</Badge>
              <Badge tone="neutral">تسط: {contextRow.suppressed ? "زیر حد نصاب" : pct(contextRow.mastery)}</Badge>
            </div>

            <div className="divide-y divide-line rounded-xl border border-line">
              {ctxEntries.map((e, i) => (
                <div key={i} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                  <span className="text-ink-muted">{e.label}</span>
                  <span className="num font-bold text-ink">{e.value}</span>
                </div>
              ))}
            </div>

            <Alert variant="warning" title="حضور">
              {ctx?.attendance_note_fa}
            </Alert>
            <p className="text-[11px] leading-6 text-ink-faint">{data?.raw_score_note_fa}</p>
          </div>
        )}
      </Modal>
    </Section>
  );
}
