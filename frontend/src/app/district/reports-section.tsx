"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, api } from "@/lib/api";
import { GRADE_FA, fa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { StatCard } from "@/components/ui/stat";
import { SkeletonCard, SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { Tabs } from "@/components/ui/tabs";
import { HorizontalBars } from "@/components/ui/charts";
import {
  IconChart,
  IconCheckCircle,
  IconClock,
  IconExam,
  IconInbox,
  IconLayers,
  IconPlus,
  IconRefresh,
  IconSchool,
  IconSend,
} from "@/components/ui/icons";

/* ------------------------- انواع پاسخ سرور (دقیقاً مطابق backend) ------------------------- */

type SchoolLite = { id: number; name: string; school_code: string; status: string };

type StudentLite = { user_id: number; full_name: string | null; username: string | null };

type TransferRow = {
  id: number;
  student_user_id: number;
  student_name: string | null;
  from_school_id: number;
  from_school: string | null;
  to_school_id: number;
  to_school: string | null;
  from_class_id: number | null;
  to_class_id: number | null;
  reason_fa: string;
  effective_date: string;
  status: string;
  created_at: string | null;
};

type ReportRow = {
  id: number;
  district_id: number;
  title_fa: string;
  period_start: string;
  period_end: string;
  status: string;
  status_fa: string;
  created_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  review_note: string | null;
};

type ReportPayload = {
  period: { start: string; end: string };
  generated_at: string;
  summary: {
    schools_count: number;
    students_count: number;
    avg_mastery: number | null;
    growth: number | null;
    exam_avg: number | null;
    needs_attention_schools: number;
    positive_schools: number;
    common_problems: number;
  };
  schools: {
    school_id: number;
    name: string;
    students_count: number;
    current_mastery: number | null;
    growth: number | null;
    needs_intervention_pct: number | null;
    suppressed: boolean;
  }[];
  grades: {
    grade: string;
    students_count: number;
    suppressed: boolean;
    avg_mastery: number | null;
    growth: number | null;
    weak_topics: { topic_id: number; title: string }[];
  }[];
  classes: {
    name: string;
    grade: string;
    current_mastery: number | null;
    growth: number | null;
    severity_fa: string;
    suppressed: boolean;
  }[];
  exams: { total: number; by_status: Record<string, number>; avg_percent: number | null };
  interventions: {
    id: number;
    title_fa: string;
    type: string;
    status: string;
    before: number | null;
    after: number | null;
    retention: number | null;
    effect: number | null;
  }[];
  errors: {
    total: number | null;
    causes: { key: string; title_fa: string; count: number | null; pct: number | null }[];
    suppressed: boolean;
  };
  health_axes: { title_fa: string; value: number | null; unit: string; band: string }[];
  attention: {
    severity_counts: Record<string, number>;
    problems: {
      topic_id: number;
      title: string;
      weak_students: number;
      students_count: number;
      weak_ratio: number;
      schools_count: number;
      dominant_error_fa: string | null;
      prerequisites: string[];
    }[];
  };
  note_fa: string;
};

type ReportDetail = ReportRow & { payload?: ReportPayload | null };

/* ------------------------- نگاشت‌های محلی (lib مشترک قابل ویرایش نیست) ------------------------- */

const TRANSFER_STATUS_FA: Record<string, string> = {
  approved: "تأییدشده",
  pending: "در انتظار",
  rejected: "ردشده",
};

const REPORT_TONE: Record<string, Tone> = {
  draft: "neutral",
  submitted: "info",
  reviewed: "primary",
  returned: "warning",
  approved: "success",
};

const BAND_FA: Record<string, string> = { good: "خوب", medium: "متوسط", weak: "ضعیف", unknown: "زیر حد نصاب" };
const BAND_TONE: Record<string, Tone> = { good: "success", medium: "warning", weak: "danger", unknown: "neutral" };

/** متن فارسی خطا — پیام دوستانه برای 403 (مجوز). */
function blockError(e: unknown, fallback: string): string {
  if (e instanceof ApiError && e.status === 403) {
    return "دسترسی به این بخش برای نقش شما فراهم نیست (۴۰۳) — مجوز لازم را از مدیر سیستم بخواهید.";
  }
  return e instanceof Error && e.message ? e.message : fallback;
}

function faDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fa-IR");
}

function pctCell(value: number | null, danger = false): ReactNode {
  if (value === null) return <span className="text-ink-faint">—</span>;
  return <span className={`num font-bold ${danger ? "text-danger-600" : "text-ink"}`}>{fa(value, 1)}٪</span>;
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

/* ------------------------- بخش گزارش‌ها و انتقالات ------------------------- */

export function ReportsSection() {
  const [view, setView] = useState("transfers");

  // مدارس (مشترک هر دو فرم)
  const [schools, setSchools] = useState<SchoolLite[]>([]);
  const [schoolsError, setSchoolsError] = useState("");

  // انتقال‌ها
  const [transfers, setTransfers] = useState<TransferRow[]>([]);
  const [trLoading, setTrLoading] = useState(true);
  const [trError, setTrError] = useState("");
  const [trForm, setTrForm] = useState({ fromSid: "", studentId: "", toSid: "", reason: "", date: "" });
  const [students, setStudents] = useState<StudentLite[]>([]);
  const [studentsLoading, setStudentsLoading] = useState(false);
  const [studentsError, setStudentsError] = useState("");
  const [trCreating, setTrCreating] = useState(false);

  // گزارش‌ها
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [rpLoading, setRpLoading] = useState(true);
  const [rpError, setRpError] = useState("");
  const [rpForm, setRpForm] = useState({ title: "", start: "", end: "" });
  const [rpGenerating, setRpGenerating] = useState(false);

  // مودال جزئیات گزارش
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  // تأیید ارسال گزارش
  const [submitTarget, setSubmitTarget] = useState<ReportRow | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [refreshing, setRefreshing] = useState(false);

  /* ------------------------- بارگذاری ------------------------- */

  useEffect(() => {
    api<{ schools: SchoolLite[] }>("/district/me/schools?status=active")
      .then((d) => setSchools(d.schools))
      .catch((e) => setSchoolsError(blockError(e, "خطا در دریافت مدارس ناحیه")));
  }, []);

  const loadTransfers = useCallback(async () => {
    setTrLoading(true);
    try {
      const res = await api<{ total: number; transfers: TransferRow[] }>("/district/transfers");
      setTransfers(res.transfers);
      setTrError("");
    } catch (e) {
      setTrError(blockError(e, "خطا در دریافت سابقه انتقال‌ها"));
    } finally {
      setTrLoading(false);
    }
  }, []);

  const loadReports = useCallback(async () => {
    setRpLoading(true);
    try {
      const res = await api<{ total: number; reports: ReportRow[] }>("/district/reports");
      setReports(res.reports);
      setRpError("");
    } catch (e) {
      setRpError(blockError(e, "خطا در دریافت گزارش‌ها"));
    } finally {
      setRpLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTransfers();
    loadReports();
  }, [loadTransfers, loadReports]);

  async function refreshAll() {
    setRefreshing(true);
    await Promise.allSettled([loadTransfers(), loadReports()]);
    setRefreshing(false);
  }

  /* ------------------------- دانش‌آموزان مدرسه مبدأ ------------------------- */

  useEffect(() => {
    if (!trForm.fromSid) {
      setStudents([]);
      setStudentsError("");
      return;
    }
    let alive = true;
    setStudentsLoading(true);
    setStudentsError("");
    api<{ students: StudentLite[] }>(`/admin/school/${trForm.fromSid}/students`)
      .then((d) => {
        if (alive) setStudents(d.students);
      })
      .catch((e) => {
        if (alive) {
          setStudents([]);
          setStudentsError(blockError(e, "خطا در دریافت دانش‌آموزان این مدرسه"));
        }
      })
      .finally(() => {
        if (alive) setStudentsLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [trForm.fromSid]);

  /* ------------------------- ثبت انتقال ------------------------- */

  async function createTransfer(e: React.FormEvent) {
    e.preventDefault();
    if (!trForm.studentId) {
      toast("دانش‌آموز را انتخاب کنید.", "warning");
      return;
    }
    if (!trForm.toSid) {
      toast("مدرسه مقصد را انتخاب کنید.", "warning");
      return;
    }
    if (trForm.toSid === trForm.fromSid) {
      toast("مدرسه مبدأ و مقصد یکسان است.", "warning");
      return;
    }
    if (!trForm.reason.trim()) {
      toast("دلیل انتقال الزامی است.", "warning");
      return;
    }
    setTrCreating(true);
    try {
      const res = await api<{ ok: boolean; transfer: TransferRow }>("/district/transfers", {
        method: "POST",
        json: {
          student_user_id: Number(trForm.studentId),
          to_school_id: Number(trForm.toSid),
          reason_fa: trForm.reason.trim(),
          effective_date: trForm.date || null,
        },
      });
      toast(`انتقال «${res.transfer.student_name ?? `دانش‌آموز ${fa(res.transfer.student_user_id)}`}» به مدرسه «${res.transfer.to_school}» ثبت شد.`, "success");
      setTrForm({ fromSid: "", studentId: "", toSid: "", reason: "", date: "" });
      setStudents([]);
      await loadTransfers();
    } catch (err) {
      toast(blockError(err, "خطا در ثبت انتقال"), "error");
    } finally {
      setTrCreating(false);
    }
  }

  /* ------------------------- ساخت گزارش ------------------------- */

  async function generateReport(e: React.FormEvent) {
    e.preventDefault();
    if (!rpForm.title.trim()) {
      toast("عنوان گزارش الزامی است.", "warning");
      return;
    }
    if (!rpForm.start || !rpForm.end) {
      toast("آغاز و پایان بازه گزارش را انتخاب کنید.", "warning");
      return;
    }
    if (rpForm.end < rpForm.start) {
      toast("پایان بازه نمی‌تواند پیش از آغاز آن باشد.", "warning");
      return;
    }
    setRpGenerating(true);
    try {
      const res = await api<{ ok: boolean; report: ReportRow }>("/district/reports/generate", {
        method: "POST",
        json: {
          title_fa: rpForm.title.trim(),
          period_start: rpForm.start,
          period_end: rpForm.end,
        },
      });
      toast(`گزارش «${res.report.title_fa}» ساخته شد.`, "success");
      setRpForm({ title: "", start: "", end: "" });
      await loadReports();
      openDetail(res.report);
    } catch (err) {
      toast(blockError(err, "خطا در ساخت گزارش"), "error");
    } finally {
      setRpGenerating(false);
    }
  }

  /* ------------------------- مشاهده و ارسال گزارش ------------------------- */

  async function openDetail(row: ReportRow) {
    setDetailId(row.id);
    setDetail({ ...row, payload: null });
    setDetailLoading(true);
    setDetailError("");
    try {
      const res = await api<{ report: ReportDetail }>(`/district/reports/${row.id}`);
      setDetail(res.report);
    } catch (e) {
      setDetailError(blockError(e, "خطا در دریافت محتوای گزارش"));
    } finally {
      setDetailLoading(false);
    }
  }

  async function submitReport() {
    if (!submitTarget) return;
    setSubmitting(true);
    try {
      await api(`/district/reports/${submitTarget.id}/submit`, { method: "POST" });
      toast(`گزارش «${submitTarget.title_fa}» به استان ارسال شد.`, "success");
      const openedId = detailId;
      setSubmitTarget(null);
      await loadReports();
      if (openedId === submitTarget.id) await openDetail(submitTarget);
    } catch (err) {
      toast(blockError(err, "خطا در ارسال گزارش"), "error");
    } finally {
      setSubmitting(false);
    }
  }

  /* ------------------------- ستون‌های جدول‌ها ------------------------- */

  const transferColumns: Column<TransferRow>[] = [
    {
      key: "student",
      header: "دانش‌آموز",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{r.student_name ?? `دانش‌آموز #${fa(r.student_user_id)}`}</p>
          <p className="num text-[11px] text-ink-faint"># {fa(r.student_user_id)}</p>
        </div>
      ),
    },
    {
      key: "from",
      header: "از مدرسه",
      render: (r) => <span className="text-ink-muted">{r.from_school ?? `#${fa(r.from_school_id)}`}</span>,
    },
    {
      key: "to",
      header: "به مدرسه",
      render: (r) => <span className="font-semibold text-ink">{r.to_school ?? `#${fa(r.to_school_id)}`}</span>,
    },
    { key: "reason", header: "دلیل", render: (r) => <span className="text-[11px] leading-5 text-ink-muted">{r.reason_fa}</span> },
    {
      key: "date",
      header: "تاریخ اجرا",
      align: "center",
      render: (r) => <span className="num text-[11px] text-ink-faint">{faDate(r.effective_date)}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (r) => (
        <Badge tone={statusTone(r.status)} dot>
          {TRANSFER_STATUS_FA[r.status] ?? r.status}
        </Badge>
      ),
    },
    {
      key: "created",
      header: "تاریخ ثبت",
      align: "center",
      render: (r) => <span className="num text-[11px] text-ink-faint">{faDate(r.created_at)}</span>,
    },
  ];

  const reportColumns: Column<ReportRow>[] = [
    {
      key: "title",
      header: "عنوان گزارش",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{r.title_fa}</p>
          <p className="num text-[11px] text-ink-faint">#{fa(r.id)}</p>
        </div>
      ),
    },
    {
      key: "period",
      header: "بازه",
      align: "center",
      render: (r) => (
        <span className="num text-[11px] text-ink-muted">
          {faDate(r.period_start)} تا {faDate(r.period_end)}
        </span>
      ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (r) => (
        <Badge tone={REPORT_TONE[r.status] ?? "neutral"} dot>
          {r.status_fa}
        </Badge>
      ),
    },
    {
      key: "created",
      header: "ایجاد",
      align: "center",
      render: (r) => <span className="num text-[11px] text-ink-faint">{faDate(r.created_at)}</span>,
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (r) => (
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="soft" onClick={() => openDetail(r)}>
            مشاهده
          </Button>
          {(r.status === "draft" || r.status === "returned") && (
            <Button size="sm" variant="primary" icon={<IconSend size={13} />} onClick={() => setSubmitTarget(r)}>
              ارسال به استان
            </Button>
          )}
        </div>
      ),
    },
  ];

  const gradeColumns: Column<NonNullable<ReportPayload>["grades"][number]>[] = [
    {
      key: "grade",
      header: "پایه",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{GRADE_FA[r.grade] ?? r.grade}</p>
          <p className="num text-[11px] text-ink-faint">{fa(r.students_count)} دانش‌آموز</p>
        </div>
      ),
    },
    {
      key: "mastery",
      header: "میانگین تسط",
      align: "center",
      render: (r) => (r.suppressed ? <Badge tone="neutral">زیر حد نصاب</Badge> : pctCell(r.avg_mastery)),
    },
    { key: "growth", header: "رشد", align: "center", render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : deltaCell(r.growth)) },
    {
      key: "weak",
      header: "مباحث ضعیف",
      render: (r) =>
        r.weak_topics.length === 0 ? (
          <span className="text-ink-faint">—</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {r.weak_topics.map((t) => (
              <Badge key={t.topic_id} tone="warning">
                {t.title}
              </Badge>
            ))}
          </div>
        ),
    },
  ];

  const schoolColumns: Column<NonNullable<ReportPayload>["schools"][number]>[] = [
    { key: "name", header: "مدرسه", render: (r) => <span className="font-semibold text-ink">{r.name}</span> },
    { key: "students", header: "دانش‌آموزان", align: "center", render: (r) => <span className="num text-ink">{fa(r.students_count)}</span> },
    {
      key: "mastery",
      header: "تسط فعلی",
      align: "center",
      render: (r) => (r.suppressed ? <Badge tone="neutral">زیر حد نصاب</Badge> : pctCell(r.current_mastery)),
    },
    { key: "growth", header: "رشد", align: "center", render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : deltaCell(r.growth)) },
    { key: "need", header: "نیازمند مداخله", align: "center", render: (r) => (r.suppressed ? <span className="text-ink-faint">—</span> : pctCell(r.needs_intervention_pct, true)) },
  ];

  /* ------------------------- رندر ------------------------- */

  return (
    <Section
      title="گزارش‌ها و انتقالات"
      subtitle="انتقال دانش‌آموزان بین مدارس ناحیه با حفظ سابقه (§19) + چرخه کامل گزارش مدیریتی: ساخت ← فهرست ← مشاهده ← ارسال به استان (§31–§32)."
      action={
        <Button size="sm" variant="soft" loading={refreshing} icon={<IconRefresh size={14} />} onClick={refreshAll}>
          به‌روزرسانی
        </Button>
      }
    >
      <Tabs
        items={[
          { key: "transfers", label: "انتقال دانش‌آموزان", count: transfers.length },
          { key: "reports", label: "گزارش‌های ناحیه", count: reports.length },
        ]}
        value={view}
        onChange={setView}
      />

      {/* ================= انتقالات (§18–§19) ================= */}
      {view === "transfers" && (
        <>
          <Card>
            <CardHeader
              title="ثبت انتقال دانش‌آموز"
              subtitle="مدرسه مبدأ از روی پروفایل دانش‌آموز تعیین می‌شود؛ هر دو مدرسه باید در همین ناحیه و فعال باشند. سابقه مدرسه/کلاس قبلی حفظ می‌شود."
              icon={<IconSchool size={17} />}
            />
            {schoolsError && <Alert variant="warning">{schoolsError}</Alert>}
            <form onSubmit={createTransfer} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="مدرسه مبدأ" required hint="برای بارگذاری فهرست دانش‌آموزان">
                <Select
                  value={trForm.fromSid}
                  onChange={(e) => setTrForm({ ...trForm, fromSid: e.target.value, studentId: "" })}
                >
                  <option value="">انتخاب مدرسه…</option>
                  {schools.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="دانش‌آموز" required hint={studentsLoading ? "در حال بارگذاری…" : studentsError || undefined}>
                <Select value={trForm.studentId} onChange={(e) => setTrForm({ ...trForm, studentId: e.target.value })} disabled={!trForm.fromSid || studentsLoading}>
                  <option value="">{studentsError ? "دانش‌آموزی در دسترس نیست" : "انتخاب دانش‌آموز…"}</option>
                  {students.map((st) => (
                    <option key={st.user_id} value={st.user_id}>
                      {st.full_name ?? st.username ?? `#${st.user_id}`}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="مدرسه مقصد" required>
                <Select value={trForm.toSid} onChange={(e) => setTrForm({ ...trForm, toSid: e.target.value })}>
                  <option value="">انتخاب مدرسه…</option>
                  {schools.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="تاریخ اجرا" hint="خالی → امروز">
                <Input type="date" value={trForm.date} onChange={(e) => setTrForm({ ...trForm, date: e.target.value })} />
              </Field>
              <Field label="دلیل انتقال" required className="sm:col-span-2 lg:col-span-4">
                <Input
                  value={trForm.reason}
                  onChange={(e) => setTrForm({ ...trForm, reason: e.target.value })}
                  placeholder="مثلاً جابه‌جایی خانوادگی به محدوده مدرسه دیگر"
                />
              </Field>
              <div className="sm:col-span-2 lg:col-span-4">
                <Button type="submit" loading={trCreating} icon={<IconSend size={15} />}>
                  ثبت انتقال
                </Button>
              </div>
            </form>
          </Card>

          {trError ? (
            <Alert variant="warning" title="سابقه انتقال‌ها">
              {trError}
            </Alert>
          ) : trLoading ? (
            <SkeletonTable rows={4} cols={5} />
          ) : transfers.length === 0 ? (
            <EmptyState
              icon={<IconInbox size={26} />}
              title="انتقالی ثبت نشده"
              description="با فرم بالا اولین انتقال دانش‌آموز بین مدارس ناحیه را ثبت کنید؛ همه انتقال‌ها برای شفافیت و ممیزی نگهداری می‌شوند."
            />
          ) : (
            <DataTable columns={transferColumns} rows={transfers} keyOf={(r) => r.id} dense empty={<EmptyState compact title="انتقالی نیست" />} />
          )}
        </>
      )}

      {/* ================= گزارش‌ها (§31–§32) ================= */}
      {view === "reports" && (
        <>
          <Card>
            <CardHeader
              title="ساخت گزارش مدیریتی ناحیه"
              subtitle="گزارش از همان داده‌های تجمیعی موجود ساخته می‌شود (رویداد district_report_generated) و پس از ارسال قفل می‌شود."
              icon={<IconPlus size={17} />}
            />
            <form onSubmit={generateReport} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="عنوان گزارش" required className="sm:col-span-2">
                <Input
                  value={rpForm.title}
                  onChange={(e) => setRpForm({ ...rpForm, title: e.target.value })}
                  placeholder="مثلاً گزارش عملکرد نیم‌سال اول ناحیه"
                />
              </Field>
              <Field label="آغاز بازه" required>
                <Input type="date" value={rpForm.start} onChange={(e) => setRpForm({ ...rpForm, start: e.target.value })} />
              </Field>
              <Field label="پایان بازه" required>
                <Input type="date" value={rpForm.end} onChange={(e) => setRpForm({ ...rpForm, end: e.target.value })} />
              </Field>
              <div className="sm:col-span-2 lg:col-span-4">
                <Button type="submit" loading={rpGenerating} icon={<IconPlus size={15} />}>
                  ساخت گزارش
                </Button>
              </div>
            </form>
          </Card>

          {rpError ? (
            <Alert variant="warning" title="فهرست گزارش‌ها">
              {rpError}
            </Alert>
          ) : rpLoading ? (
            <SkeletonTable rows={4} cols={5} />
          ) : reports.length === 0 ? (
            <EmptyState
              icon={<IconInbox size={26} />}
              title="گزارشی ساخته نشده"
              description="با فرم بالا اولین گزارش مدیریتی ناحیه را برای یک بازه مشخص بسازید، سپس آن را برای استان ارسال کنید."
            />
          ) : (
            <DataTable columns={reportColumns} rows={reports} keyOf={(r) => r.id} empty={<EmptyState compact title="گزارشی نیست" />} />
          )}
        </>
      )}

      {/* ---------- مودال جزئیات گزارش ---------- */}
      <Modal
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        title={detail ? `گزارش — ${detail.title_fa}` : "جزئیات گزارش"}
        size="lg"
        footer={
          <>
            {detail && (detail.status === "draft" || detail.status === "returned") && (
              <Button variant="primary" icon={<IconSend size={14} />} onClick={() => setSubmitTarget(detail)}>
                ارسال به استان
              </Button>
            )}
            <Button variant="ghost" onClick={() => setDetailId(null)}>
              بستن
            </Button>
          </>
        }
      >
        {detail && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={REPORT_TONE[detail.status] ?? "neutral"} dot>
                {detail.status_fa}
              </Badge>
              <Badge tone="neutral">
                <IconClock size={12} /> {faDate(detail.period_start)} تا {faDate(detail.period_end)}
              </Badge>
              {detail.submitted_at && <Badge tone="info">ارسال: {faDate(detail.submitted_at)}</Badge>}
              {detail.reviewed_at && <Badge tone="primary">بازبینی: {faDate(detail.reviewed_at)}</Badge>}
            </div>

            {detail.review_note && <Alert variant="warning" title="یادداشت بازبینی">{detail.review_note}</Alert>}

            {detailLoading ? (
              <SkeletonCard />
            ) : detailError ? (
              <Alert variant="warning" title="محتوای گزارش">{detailError}</Alert>
            ) : detail.payload ? (
              <ReportPayloadView payload={detail.payload} gradeColumns={gradeColumns} schoolColumns={schoolColumns} />
            ) : (
              <EmptyState compact title="محتوای گزارش بارگذاری نشد" />
            )}
          </div>
        )}
      </Modal>

      {/* ---------- مودال تأیید ارسال ---------- */}
      <Modal
        open={submitTarget !== null}
        onClose={() => setSubmitTarget(null)}
        title="ارسال گزارش به استان"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setSubmitTarget(null)}>
              انصراف
            </Button>
            <Button variant="primary" loading={submitting} icon={<IconSend size={14} />} onClick={submitReport}>
              ارسال نهایی
            </Button>
          </>
        }
      >
        {submitTarget && (
          <div className="space-y-3">
            <p className="leading-6 text-ink-muted">
              گزارش «{submitTarget.title_fa}» برای بازه {faDate(submitTarget.period_start)} تا {faDate(submitTarget.period_end)} به استان ارسال شود؟
            </p>
            <Alert variant="warning">
              پس از ارسال، گزارش قفل می‌شود و دیگر قابل ویرایش/ارسال مجدد نیست (فقط پیش‌نویس یا گزارش برگشت‌خورده قابل ارسال است).
            </Alert>
          </div>
        )}
      </Modal>
    </Section>
  );
}

/* ------------------------- نمای محتوای گزارش (payload §31) ------------------------- */

function ReportPayloadView({
  payload,
  gradeColumns,
  schoolColumns,
}: {
  payload: ReportPayload;
  gradeColumns: Column<ReportPayload["grades"][number]>[];
  schoolColumns: Column<ReportPayload["schools"][number]>[];
}) {
  const s = payload.summary;
  const byStatus = Object.entries(payload.exams.by_status);

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="مدارس" value={fa(s.schools_count)} tone="primary" icon={<IconSchool size={20} />} />
        <StatCard label="دانش‌آموزان" value={fa(s.students_count)} tone="accent" icon={<IconExam size={20} />} />
        <StatCard
          label="میانگین تسط"
          value={s.avg_mastery === null ? "زیر حد نصاب" : `${fa(s.avg_mastery)}٪`}
          tone={s.avg_mastery !== null && s.avg_mastery >= 65 ? "success" : "warning"}
          icon={<IconChart size={20} />}
        />
        <StatCard
          label="رشد تسط"
          value={s.growth === null ? "زیر حد نصاب" : `${s.growth > 0 ? "+" : ""}${fa(s.growth, 1)} واحد`}
          tone={s.growth !== null && s.growth > 0 ? "success" : s.growth !== null && s.growth < 0 ? "danger" : "primary"}
          icon={<IconCheckCircle size={20} />}
        />
      </section>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="میانگین آزمون" value={s.exam_avg === null ? "—" : `${fa(s.exam_avg, 1)}٪`} tone="sky" icon={<IconExam size={20} />} />
        <StatCard label="مدارس نیازمند توجه" value={fa(s.needs_attention_schools)} tone={s.needs_attention_schools > 0 ? "danger" : "success"} icon={<IconLayers size={20} />} />
        <StatCard label="مدارس با تجربه مثبت" value={fa(s.positive_schools)} tone="success" icon={<IconCheckCircle size={20} />} />
        <StatCard label="مشکلات مشترک" value={fa(s.common_problems)} tone={s.common_problems > 0 ? "warning" : "success"} icon={<IconChart size={20} />} />
      </section>

      <div className="flex flex-wrap gap-2">
        {payload.health_axes.map((a) => (
          <Badge key={a.title_fa} tone={BAND_TONE[a.band] ?? "neutral"}>
            {a.title_fa}:{" "}
            <span className="num">
              {a.value === null
                ? "زیر حد نصاب"
                : a.unit === "٪" || a.unit === "درصد" || a.unit === "٪ اثرگذار" || a.unit === "٪ بهبود"
                  ? `${fa(a.value, 1)}٪`
                  : a.unit === "نسبت"
                    ? fa(a.value, 2)
                    : a.unit === "واحد تسط"
                      ? `${fa(a.value, 1)} واحد`
                      : fa(a.value, 1)}
            </span>
            <span className="opacity-70">({BAND_FA[a.band] ?? a.band})</span>
          </Badge>
        ))}
      </div>

      <p className="text-[11px] leading-6 text-ink-muted">
        آزمون‌ها: <span className="num font-bold text-ink">{fa(payload.exams.total)}</span>
        {byStatus.length > 0 && ` (${byStatus.map(([k, v]) => `${k}: ${fa(v)}`).join("، ")})`}
        {" · "}میانگین آزمون: <span className="num font-bold text-ink">{payload.exams.avg_percent === null ? "—" : `${fa(payload.exams.avg_percent, 1)}٪`}</span>
        {" · "}مداخله‌ها: <span className="num font-bold text-ink">{fa(payload.interventions.length)}</span>
      </p>

      <div className="space-y-2">
        <p className="text-xs font-bold text-ink">وضعیت پایه‌ها</p>
        <DataTable columns={gradeColumns} rows={payload.grades} keyOf={(r) => r.grade} dense empty={<EmptyState compact title="پایه‌ای ثبت نشده" />} />
      </div>

      <div className="space-y-2">
        <p className="text-xs font-bold text-ink">مدارس</p>
        <DataTable columns={schoolColumns} rows={payload.schools} keyOf={(r) => r.school_id} dense empty={<EmptyState compact title="مدرسه‌ای ثبت نشده" />} />
      </div>

      {payload.errors.causes.some((c) => (c.count ?? 0) > 0) && (
        <div className="rounded-xl border border-line bg-surface-sunken p-4">
          <p className="mb-3 text-xs font-bold text-ink">توزیع خطاهای ناحیه</p>
          <HorizontalBars
            data={payload.errors.causes
              .filter((c) => (c.count ?? 0) > 0)
              .map((c) => ({ label: c.title_fa, value: c.count ?? 0 }))}
          />
        </div>
      )}

      {payload.attention.problems.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-bold text-ink">کانون توجه (مشکلات مشترک)</p>
          <ul className="space-y-2">
            {payload.attention.problems.map((p) => (
              <li key={p.topic_id} className="rounded-xl border border-line bg-surface-sunken px-3.5 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-ink">{p.title}</span>
                  <Badge tone="danger">
                    <span className="num">{fa(p.weak_ratio, 1)}٪</span> ضعف · {fa(p.schools_count)} مدرسه
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] leading-5 text-ink-muted">
                  {p.dominant_error_fa ? `خطای غالب: ${p.dominant_error_fa} · ` : ""}
                  {p.prerequisites.length ? `تقویت پیش‌نیاز: ${p.prerequisites.join("، ")}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Alert variant="info">{payload.note_fa}</Alert>
    </div>
  );
}
