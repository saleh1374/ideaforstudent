"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CAUSE_SHORT, STATUS_COLOR, STATUS_FA, fa, subjectFa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { Modal } from "@/components/ui/modal";
import { StatCard } from "@/components/ui/stat";
import {
  IconChart,
  IconExam,
  IconRefresh,
  IconTarget,
  IconTrend,
  IconUser,
} from "@/components/ui/icons";

type StudentRow = {
  user_id: number;
  full_name: string | null;
  username: string | null;
  class_id: number | null;
  class_name: string | null;
  avg_mastery: number | null;
};

type TopicRow = {
  topic_id: number;
  title: string;
  mastery: number;
  retention: number;
  status: string;
  evidence_count: number;
};

type AttemptRow = {
  attempt_id: number;
  exam_id: number;
  exam_title: string | null;
  subject: string | null;
  percent: number | null;
  raw_score: number | null;
  submitted_at: string | null;
  correct: number;
  wrong: number;
  blank: number;
  avg_time_ms: number | null;
};

type StudentDetail = {
  student: {
    user_id: number;
    full_name: string | null;
    username: string | null;
    grade: string;
    class_id: number | null;
    class_name: string | null;
    status: string;
  };
  mastery: {
    overall: number | null;
    retention: number | null;
    rank_in_class: number | null;
    class_size: number | null;
    trend: string;
    trend_delta: number | null;
  };
  indicators: {
    repeat_open_errors: number;
    critical_topics: number;
    practice_completion_pct: number | null;
    attendance_pct: number | null;
    attendance_note_fa: string;
    platform: { exam_sessions_recorded: number; answers_recorded: number };
  };
  error_causes: Record<string, number>;
  main_problem_fa: string;
  interventions: { cycles: number; resolved: number; relapsed: number; result_fa: string };
  topics: TopicRow[];
  recent_attempts: AttemptRow[];
  note_fa: string;
};

const TREND_FA: Record<string, string> = {
  up: "صعودی",
  down: "نزولی",
  flat: "ثابت",
  unknown: "بدون تاریخچه کافی",
};

const TREND_TONE: Record<string, "success" | "danger" | "neutral" | "primary"> = {
  up: "success",
  down: "danger",
  flat: "neutral",
  unknown: "primary",
};

function pct(v: number | null, digits = 0): string {
  return v === null ? "—" : `${fa(v, digits)}٪`;
}

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fa-IR");
  } catch {
    return iso.slice(0, 10);
  }
}

export function StudentViewSection({ schoolId }: { schoolId: number | null }) {
  const [rows, setRows] = useState<StudentRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<StudentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async (sid: number | null) => {
    if (sid === null) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await api<{ school_id: number; total: number; students: StudentRow[] }>(
        `/admin/school/${sid}/students`
      );
      setRows(res.students);
      setTotal(res.total);
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : "خطا در دریافت فهرست دانش‌آموزان");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(schoolId);
  }, [schoolId, load]);

  const openDetail = useCallback(
    async (uid: number) => {
      if (schoolId === null) return;
      setSelectedId(uid);
      setDetail(null);
      setDetailError("");
      setDetailLoading(true);
      try {
        setDetail(await api<StudentDetail>(`/admin/school/${schoolId}/students/${uid}`));
      } catch (e) {
        // scope guard بک‌اند 403 می‌دهد؛ پیام همان نمایش داده می‌شود
        setDetailError(e instanceof Error ? e.message : "خطا در دریافت نمای فردی");
      } finally {
        setDetailLoading(false);
      }
    },
    [schoolId]
  );

  const closeDetail = useCallback(() => {
    setDetail(null);
    setDetailError("");
    setSelectedId(null);
  }, []);

  const listColumns: Column<StudentRow>[] = [
    {
      key: "name",
      header: "دانش‌آموز",
      render: (row) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{row.full_name ?? "—"}</p>
          <p className="num text-[11px] text-ink-faint">{row.username ?? "—"}</p>
        </div>
      ),
    },
    { key: "class", header: "کلاس", align: "center", render: (row) => row.class_name ?? "—" },
    {
      key: "mastery",
      header: "میانگین تسط",
      align: "center",
      render: (row) => (
        <span className={`num font-bold ${row.avg_mastery === null ? "text-ink-faint" : "text-ink"}`}>
          {pct(row.avg_mastery)}
        </span>
      ),
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (row) => (
        <Button size="sm" variant="soft" icon={<IconUser size={14} />} onClick={() => openDetail(row.user_id)}>
          نمای فردی
        </Button>
      ),
    },
  ];

  const topicColumns: Column<TopicRow>[] = [
    { key: "title", header: "مبحث", render: (row) => <span className="font-semibold text-ink">{row.title}</span> },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${STATUS_COLOR[row.status] ?? "bg-slate-100 text-slate-500"}`}>
          {STATUS_FA[row.status] ?? row.status}
        </span>
      ),
    },
    { key: "mastery", header: "تسط", align: "center", render: (row) => <span className="num font-bold text-ink">{fa(row.mastery)}٪</span> },
    { key: "retention", header: "ماندگاری", align: "center", render: (row) => <span className="num">{fa(row.retention * 100)}٪</span> },
    { key: "ev", header: "شواهد", align: "center", render: (row) => <span className="num">{fa(row.evidence_count)}</span> },
  ];

  const attemptColumns: Column<AttemptRow>[] = [
    {
      key: "exam",
      header: "آزمون",
      render: (row) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{row.exam_title ?? `آزمون #${row.exam_id}`}</p>
          <p className="text-[11px] text-ink-faint">
            {subjectFa(row.subject)} · {shortDate(row.submitted_at)}
          </p>
        </div>
      ),
    },
    {
      key: "percent",
      header: "درصد",
      align: "center",
      render: (row) => (
        <span className={`num font-bold ${row.percent !== null && row.percent < 50 ? "text-danger-600" : "text-ink"}`}>
          {row.percent === null ? "—" : `${fa(row.percent)}٪`}
        </span>
      ),
    },
    {
      key: "cw",
      header: "درست/غلط/blank",
      align: "center",
      render: (row) => (
        <span className="num text-[11px] text-ink-muted">
          {fa(row.correct)} / {fa(row.wrong)} / {fa(row.blank)}
        </span>
      ),
    },
    {
      key: "time",
      header: "میانگین زمان",
      align: "center",
      render: (row) => (
        <span className="num text-[11px] text-ink-muted">{row.avg_time_ms === null ? "—" : `${fa(Math.round(row.avg_time_ms / 1000))} ثانیه`}</span>
      ),
    },
  ];

  const m = detail?.mastery;
  const ind = detail?.indicators;
  const iv = detail?.interventions;

  return (
    <Section
      title="نمای فردی دانش‌آموز (§13)"
      subtitle="تسط، ماندگاری، رتبه داخل کلاس و روند هر دانش‌آموز — فقط برای بررسی مدیریتی، نه برد عمومی."
      action={
        <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => load(schoolId)}>
          تازه‌سازی
        </Button>
      }
    >
      {error && (
        <Alert variant="danger" title="خطا در دریافت فهرست">
          {error}
        </Alert>
      )}

      {loading ? (
        <SkeletonTable rows={5} cols={4} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<IconChart size={26} />} title="دانش‌آموزی ثبت نشده" description="هنوز پروفایل دانش‌آموزی برای این مدرسه وجود ندارد." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="کل دانش‌آموزان" value={fa(total)} tone="primary" icon={<IconUser size={20} />} hint="این مدرسه" />
            <StatCard
              label="دارای داده یادگیری"
              value={fa(rows.filter((r) => r.avg_mastery !== null).length)}
              tone="accent"
              icon={<IconChart size={20} />}
              hint="حداقل شواهد لازم"
            />
            <StatCard
              label="زیر ۶۰٪ تسط"
              value={fa(rows.filter((r) => r.avg_mastery !== null && (r.avg_mastery as number) < 60).length)}
              tone="warning"
              icon={<IconTarget size={20} />}
              hint="کاندیدای مداخله"
            />
            <StatCard label="بدون داده" value={fa(rows.filter((r) => r.avg_mastery === null).length)} tone="danger" icon={<IconExam size={20} />} hint="نیازمند ثبت فعالیت" />
          </div>

          <div className="rounded-2xl border border-line bg-surface p-1">
            <p className="px-3 pt-2 text-xs font-bold text-ink">فهرست دانش‌آموزان — برای دیدن نمای فردی، روی ردیف بزنید</p>
            <DataTable columns={listColumns} rows={rows} keyOf={(r) => r.user_id} empty={<EmptyState compact title="دانش‌آموزی نیست" />} />
          </div>

          <p className="text-[11px] leading-6 text-ink-faint">
            رتبه فقط داخل کلاس خودِ دانش‌آموز محاسبه می‌شود و در هیچ برد عمومی نمایش داده نمی‌شود (§13).
          </p>
        </>
      )}

      {/* ——— مودال نمای فردی ——— */}
      <Modal
        open={selectedId !== null}
        onClose={closeDetail}
        title={detail ? `نمای فردی — ${detail.student.full_name ?? detail.student.username ?? ""}` : "نمای فردی"}
        size="lg"
        footer={
          <Button variant="ghost" onClick={closeDetail}>
            بستن
          </Button>
        }
      >
        {detailLoading && <SkeletonStats count={4} />}

        {!detailLoading && detailError && (
          <Alert variant="danger" title="خطا">
            {detailError}
          </Alert>
        )}

        {!detailLoading && detail && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="primary">کلاس {detail.student.class_name ?? "—"}</Badge>
              <Badge tone="neutral">پایه: {detail.student.grade}</Badge>
              <Badge tone={TREND_TONE[detail.mastery.trend] ?? "neutral"}>
                روند: {TREND_FA[detail.mastery.trend] ?? detail.mastery.trend}
                {detail.mastery.trend_delta !== null && ` (${detail.mastery.trend_delta > 0 ? "+" : ""}${fa(detail.mastery.trend_delta)} واحد)`}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatCard
                label="تسط کلی"
                value={pct(detail.mastery.overall)}
                tone="primary"
                icon={<IconChart size={18} />}
                spark={detail.topics.length > 0 ? detail.topics.slice(0, 8).map((t) => t.mastery) : undefined}
              />
              <StatCard
                label="ماندگاری"
                value={detail.mastery.retention === null ? "—" : pct(detail.mastery.retention * 100)}
                tone="accent"
                icon={<IconTrend size={18} />}
                hint="بازآزمون‌ها"
              />
              <StatCard
                label="رتبه در کلاس"
                value={detail.mastery.rank_in_class === null ? "—" : `${fa(detail.mastery.rank_in_class)} از ${fa(detail.mastery.class_size ?? 0)}`}
                tone="success"
                icon={<IconTarget size={18} />}
                hint="فقط داخل کلاس"
              />
              <StatCard label="خطاهای باز" value={fa(detail.indicators.repeat_open_errors)} tone="danger" icon={<IconExam size={18} />} hint={`${fa(detail.indicators.critical_topics)} مبحث بحرانی`} />
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-line bg-surface p-3">
                <p className="mb-2 text-xs font-bold text-ink">شاخ‌های §13</p>
                <div className="space-y-1.5 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-ink-muted">تکمیل تمرین</span>
                    <span className="num font-bold text-ink">{pct(detail.indicators.practice_completion_pct, 1)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-ink-muted">جلسات آزمون ثبت‌شده</span>
                    <span className="num font-bold text-ink">{fa(detail.indicators.platform.exam_sessions_recorded)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-ink-muted">پاسخ‌های ثبت‌شده</span>
                    <span className="num font-bold text-ink">{fa(detail.indicators.platform.answers_recorded)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-ink-muted">حضور</span>
                    <span className="font-bold text-ink-faint">—</span>
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-line bg-surface p-3">
                <p className="mb-2 text-xs font-bold text-ink">چرخه مداخله</p>
                <div className="mb-2 flex flex-wrap gap-2">
                  <Badge tone="neutral">چرخه: {fa(detail.interventions.cycles)}</Badge>
                  <Badge tone="success">رفع: {fa(detail.interventions.resolved)}</Badge>
                  <Badge tone={detail.interventions.relapsed > 0 ? "danger" : "neutral"}>بازگشت: {fa(detail.interventions.relapsed)}</Badge>
                </div>
                <p className="text-[11px] leading-6 text-ink-muted">{detail.interventions.result_fa}</p>
              </div>
            </div>

            <Alert variant="info" title="مشکل اصلی (تشخیص خودکار)">
              {detail.main_problem_fa}
            </Alert>

            {Object.keys(detail.error_causes).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(detail.error_causes).map(([c, n]) => (
                  <Badge key={c} tone="neutral">
                    {CAUSE_SHORT[c] ?? c}: {fa(n)}
                  </Badge>
                ))}
              </div>
            )}

            <Alert variant="warning" title="حضور">
              {detail.indicators.attendance_note_fa}
            </Alert>

            <div className="rounded-2xl border border-line bg-surface p-1">
              <p className="px-3 pt-2 text-xs font-bold text-ink">مباحث (پررنگ‌ترین اول)</p>
              <DataTable columns={topicColumns} rows={detail.topics} keyOf={(t) => t.topic_id} empty={<EmptyState compact title="مبحثی ثبت نشده" />} />
            </div>

            <div className="rounded-2xl border border-line bg-surface p-1">
              <p className="px-3 pt-2 text-xs font-bold text-ink">آزمون‌های اخیر</p>
              <DataTable columns={attemptColumns} rows={detail.recent_attempts} keyOf={(a) => a.attempt_id} empty={<EmptyState compact title="آزمونی ثبت نشده" />} />
            </div>

            <p className="text-[11px] leading-6 text-ink-faint">{detail.note_fa}</p>
          </div>
        )}
      </Modal>
    </Section>
  );
}
