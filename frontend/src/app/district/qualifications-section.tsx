"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  EXAM_STATUS_FA,
  INTERVENTION_FA,
  INTERVENTION_STATUS_FA,
  INTERVENTION_STATUS_TONE,
  QUALIFICATION_STATUS_FA,
  QUALIFICATION_STATUS_TONE,
  SUBJECT_FA,
  fa,
  subjectFa,
} from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconExam, IconGraduation, IconPlus, IconShield } from "@/components/ui/icons";

type QualRow = {
  id: number;
  teacher_user_id: number;
  teacher_name: string | null;
  subject: string;
  subject_fa: string;
  school_year: string;
  school_id: number | null;
  school_name: string | null;
  status: string;
  status_fa: string;
  subject_percent: number | null;
  management_percent: number | null;
  status_note: string | null;
  evaluated_at: string | null;
  interventions_count: number;
};

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
};

type AttemptRow = {
  id: number;
  exam_id: number;
  kind: string | null;
  kind_fa: string | null;
  status: string;
  percent: number | null;
  started_at: string | null;
  submitted_at: string | null;
};

type InterventionRow = {
  id: number;
  qualification_id: number;
  type: string;
  type_fa: string;
  status: string;
  notes: string | null;
  created_at: string;
  closed_at: string | null;
};

type QualDetail = {
  qualification: QualRow;
  exams: ExamRow[];
  attempts: AttemptRow[];
  interventions: InterventionRow[];
};

type TeacherRow = {
  user_id: number;
  full_name: string;
  school_id: number;
  school_name: string | null;
  subject: string | null;
  qualification_status_current_year: string | null;
};

const STATUS_OPTIONS = ["pending", "qualified", "probation", "critical"] as const;

/** فقط برای وضعیت آزمایشی/بحرانی مجاز است (سرور در غیر این صورت 409 می‌دهد). */
const canIntervene = (status: string) => status === "probation" || status === "critical";

export function QualificationsSection() {
  const [rows, setRows] = useState<QualRow[]>([]);
  const [districtId, setDistrictId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [filters, setFilters] = useState({ status: "", subject: "", school_year: "" });
  const [teachers, setTeachers] = useState<TeacherRow[]>([]);

  // تخصیص
  const [teacherKey, setTeacherKey] = useState(""); // user_id::subject
  const [assignSubject, setAssignSubject] = useState("");
  const [assignYear, setAssignYear] = useState("");
  const [assigning, setAssigning] = useState(false);

  // جزئیات
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<QualDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [ivType, setIvType] = useState("training");
  const [ivNotes, setIvNotes] = useState("");
  const [ivBusy, setIvBusy] = useState(false);

  const load = useCallback(async (f: { status: string; subject: string; school_year: string }) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (f.status) params.set("status", f.status);
      if (f.subject) params.set("subject", f.subject);
      if (f.school_year.trim()) params.set("school_year", f.school_year.trim());
      const res = await api<{ district_id: number; total: number; qualifications: QualRow[] }>(
        `/district/teacher-qualifications${params.toString() ? `?${params.toString()}` : ""}`
      );
      setRows(res.qualifications);
      setDistrictId(res.district_id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت رکوردهای صلاحیت");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filters);
  }, [filters, load]);

  useEffect(() => {
    api<{ teachers: TeacherRow[] }>("/district/teachers")
      .then((d) => setTeachers(d.teachers))
      .catch(() => setTeachers([]));
  }, []);

  async function assign(e: React.FormEvent) {
    e.preventDefault();
    if (!teacherKey) {
      toast("ابتدا معلم را انتخاب کنید.", "warning");
      return;
    }
    if (!assignSubject.trim()) {
      toast("درس الزامی است.", "warning");
      return;
    }
    const [teacherUserId] = teacherKey.split("::");
    setAssigning(true);
    try {
      const res = await api<{ ok: boolean; created: boolean; qualification_id: number; school_year: string; exams: ExamRow[] }>(
        "/district/teacher-qualifications/assign",
        {
          method: "POST",
          json: {
            teacher_user_id: Number(teacherUserId),
            subject: assignSubject.trim(),
            school_year: assignYear.trim() || undefined,
          },
        }
      );
      toast(
        res.created
          ? `آزمون‌های صلاحیت ${subjectFa(assignSubject)} برای سال ${res.school_year} تخصیص یافت.`
          : `برای سال ${res.school_year} از قبل تخصیص داده شده بود (همان رکورد بازگردانده شد).`,
        res.created ? "success" : "info"
      );
      setAssignYear("");
      await load(filters);
      setDetailId(res.qualification_id);
    } catch (err) {
      // 400 درس خالی / 404 معلم ناشناخته / 403 حوزه / 409 بانک سؤال خالی — همه فارسی‌اند
      toast(err instanceof Error ? err.message : "خطا در تخصیص آزمون", "error");
    } finally {
      setAssigning(false);
    }
  }

  async function openDetail(id: number) {
    setDetailId(id);
    setDetail(null);
    setDetailLoading(true);
    setIvNotes("");
    try {
      setDetail(await api<QualDetail>(`/district/teacher-qualifications/${id}`));
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در دریافت جزئیات", "error");
      setDetailId(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function refreshDetail(id: number) {
    try {
      setDetail(await api<QualDetail>(`/district/teacher-qualifications/${id}`));
    } catch {
      /* آخرین نمای موفق باقی می‌ماند */
    }
    await load(filters);
  }

  async function createIntervention() {
    if (detailId === null) return;
    setIvBusy(true);
    try {
      await api(`/district/teacher-qualifications/${detailId}/interventions`, {
        method: "POST",
        json: { type: ivType, notes: ivNotes.trim() || null },
      });
      toast(`اقدام «${INTERVENTION_FA[ivType] ?? ivType}» ثبت شد.`, "success");
      setIvNotes("");
      await refreshDetail(detailId);
    } catch (e) {
      // 409 یعنی وضعیت صلاحیت آزمایشی/بحرانی نیست
      toast(e instanceof Error ? e.message : "خطا در ثبت اقدام", "error");
    } finally {
      setIvBusy(false);
    }
  }

  async function setInterventionStatus(interventionId: number, status: string) {
    if (detailId === null) return;
    setIvBusy(true);
    try {
      await api(`/district/teacher-qualifications/${detailId}/interventions/${interventionId}/status`, {
        method: "POST",
        json: { status },
      });
      toast(`وضعیت اقدام: ${INTERVENTION_STATUS_FA[status] ?? status}`, "success");
      await refreshDetail(detailId);
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در به‌روزرسانی اقدام", "error");
    } finally {
      setIvBusy(false);
    }
  }

  const columns: Column<QualRow>[] = [
    {
      key: "teacher",
      header: "معلم",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.teacher_name ?? "—"}</p>
          <p className="text-[11px] text-ink-faint">{row.school_name ?? "—"}</p>
        </div>
      ),
    },
    {
      key: "subject",
      header: "درس / سال",
      align: "center",
      render: (row) => (
        <div className="space-y-1">
          <Badge tone="neutral">{row.subject_fa || subjectFa(row.subject)}</Badge>
          <p className="num text-[11px] text-ink-faint">{row.school_year}</p>
        </div>
      ),
    },
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
      key: "percent",
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
      render: (row) => (
        <span className={`num text-xs font-bold ${row.interventions_count > 0 ? "text-warning-600" : "text-ink-faint"}`}>
          {fa(row.interventions_count)}
        </span>
      ),
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (row) => (
        <Button size="sm" variant="soft" onClick={() => openDetail(row.id)}>
          جزئیات و اقدامات
        </Button>
      ),
    },
  ];

  const intervention = detail ? canIntervene(detail.qualification.status) : false;

  return (
    <Section
      title="صلاحیت معلم"
      subtitle="تخصیص سالانه دو آزمون (دانش درس + مدیریت کلاس)، پایش وضعیت و اقدام اصلاحی ناحیه."
      action={
        districtId !== null ? <Badge tone="accent">ناحیه {fa(districtId)}</Badge> : undefined
      }
    >
      {/* ---------- تخصیص آزمون ---------- */}
      <Card>
        <CardHeader
          title="تخصیص آزمون صلاحیت"
          subtitle="معلم باید همین درس را با تخصیص فعال در مدرسه‌ای از این ناحیه ارائه دهد؛ تخصیص تکراری همان رکورد را برمی‌گرداند."
          icon={<IconGraduation size={17} />}
        />
        {teachers.length === 0 ? (
          <EmptyState compact title="معلمی برای تخصیص یافت نشد" description="ابتدا در مدرسه‌های ناحیه تخصیص تدریس ثبت کنید." />
        ) : (
          <form onSubmit={assign} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="معلم" required>
              <Select value={teacherKey} onChange={(e) => {
                setTeacherKey(e.target.value);
                const parts = e.target.value.split("::");
                if (parts[1]) setAssignSubject(parts[1]);
              }}>
                <option value="">انتخاب معلم…</option>
                {teachers.map((t) => (
                  <option key={`${t.user_id}::${t.subject ?? ""}`} value={`${t.user_id}::${t.subject ?? ""}`}>
                    {t.full_name} — {subjectFa(t.subject)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="درس" required>
              <Select value={assignSubject} onChange={(e) => setAssignSubject(e.target.value)}>
                <option value="">انتخاب درس…</option>
                {Object.entries(SUBJECT_FA).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="سال تحصیلی" hint="خالی بگذارید تا سال جاری استفاده شود">
              <Input value={assignYear} onChange={(e) => setAssignYear(e.target.value)} placeholder="مثلاً 1405-1406" />
            </Field>
            <div className="flex items-end">
              <Button type="submit" loading={assigning} className="w-full" icon={<IconPlus size={15} />}>
                تخصیص دو آزمون
              </Button>
            </div>
          </form>
        )}
      </Card>

      {/* ---------- فیلترها ---------- */}
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          className="w-52"
          aria-label="فیلتر وضعیت"
        >
          <option value="">همه وضعیت‌ها</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {QUALIFICATION_STATUS_FA[s] ?? s}
            </option>
          ))}
        </Select>
        <Select
          value={filters.subject}
          onChange={(e) => setFilters({ ...filters, subject: e.target.value })}
          className="w-44"
          aria-label="فیلتر درس"
        >
          <option value="">همه درس‌ها</option>
          {Object.entries(SUBJECT_FA).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <Input
          value={filters.school_year}
          onChange={(e) => setFilters({ ...filters, school_year: e.target.value })}
          placeholder="سال تحصیلی (مثلاً 1405-1406)"
          className="w-56"
          aria-label="فیلتر سال تحصیلی"
        />
      </div>

      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={4} cols={6} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.id}
          empty={<EmptyState compact icon={<IconShield size={24} />} title="رکورد صلاحیتی ثبت نشده" description="با فرم بالا برای معلم‌ها آزمون تخصیص دهید." />}
        />
      )}

      {/* ---------- جزئیات ---------- */}
      <Modal
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        title={detail ? `جزئیات صلاحیت — ${detail.qualification.teacher_name ?? ""}` : "جزئیات صلاحیت"}
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
            {/* سربرگ رکورد */}
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={QUALIFICATION_STATUS_TONE[detail.qualification.status] ?? "neutral"} dot>
                {detail.qualification.status_fa || QUALIFICATION_STATUS_FA[detail.qualification.status]}
              </Badge>
              <Badge tone="neutral">{detail.qualification.subject_fa || subjectFa(detail.qualification.subject)}</Badge>
              <Badge tone="info">سال {detail.qualification.school_year}</Badge>
              <Badge tone="neutral">{detail.qualification.school_name ?? "—"}</Badge>
            </div>

            {detail.qualification.status_note && <Alert variant="info" title="شرح وضعیت">{detail.qualification.status_note}</Alert>}

            {/* آزمون‌ها */}
            <div className="space-y-2">
              <p className="text-xs font-bold text-ink">آزمون‌های تخصیص‌یافته</p>
              {detail.exams.map((ex) => (
                <div key={ex.id} className="rounded-xl border border-line bg-surface-sunken px-3.5 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-ink">{ex.title_fa}</p>
                      <p className="mt-0.5 text-[11px] text-ink-faint">
                        {ex.kind_fa} {ex.due_at ? `· مهلت: ${faDate(ex.due_at)}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={ex.status === "completed" ? "success" : ex.status === "expired" ? "danger" : ex.status === "in_progress" ? "info" : "neutral"}>
                        {EXAM_STATUS_FA[ex.status] ?? ex.status}
                      </Badge>
                      <span className="num w-14 text-left text-xs font-bold text-ink">
                        {ex.percent !== null ? `${fa(ex.percent)}٪` : "—"}
                      </span>
                    </div>
                  </div>
                  <ProgressBar
                    value={ex.percent ?? 0}
                    size="sm"
                    tone={ex.percent === null ? "primary" : ex.percent >= 65 ? "success" : ex.percent >= 50 ? "warning" : "danger"}
                    className="mt-2"
                  />
                </div>
              ))}
            </div>

            {/* تلاش‌ها */}
            <div className="space-y-2">
              <p className="text-xs font-bold text-ink">تلاش‌های ثبت‌شده</p>
              {detail.attempts.length === 0 ? (
                <p className="rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-faint">هنوز تلاشی ثبت نشده است.</p>
              ) : (
                <ul className="divide-y divide-line-soft rounded-xl border border-line">
                  {detail.attempts.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 text-xs">
                      <span className="font-semibold text-ink">{a.kind_fa ?? "—"}</span>
                      <span className="flex items-center gap-2 text-ink-faint">
                        <Badge tone={a.status === "graded" ? "success" : "info"}>{a.status === "graded" ? "تصحیح‌شده" : "در حال آزمون"}</Badge>
                        <span className="num">{a.percent !== null ? `${fa(a.percent)}٪` : "—"}</span>
                        <span className="num">{a.submitted_at ? faDate(a.submitted_at) : a.started_at ? faDate(a.started_at) : ""}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* اقدامات اصلاحی */}
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-bold text-ink">اقدام‌های اصلاحی</p>
                <Badge tone={QUALIFICATION_STATUS_TONE[detail.qualification.status] ?? "neutral"}>
                  {intervention ? "ثبت اقدام مجاز است" : "فقط برای آزمایشی/بحرانی"}
                </Badge>
              </div>

              {detail.interventions.length === 0 ? (
                <p className="rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-faint">اقدامی ثبت نشده است.</p>
              ) : (
                <ul className="space-y-2">
                  {detail.interventions.map((iv) => (
                    <li key={iv.id} className="rounded-xl border border-line bg-surface px-3.5 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-xs font-semibold text-ink">
                          <Badge tone="primary">{iv.type_fa || (INTERVENTION_FA[iv.type] ?? iv.type)}</Badge>
                          <Badge tone={INTERVENTION_STATUS_TONE[iv.status] ?? "neutral"}>
                            {INTERVENTION_STATUS_FA[iv.status] ?? iv.status}
                          </Badge>
                        </span>
                        <span className="num text-[11px] text-ink-faint">{faDate(iv.created_at)}</span>
                      </div>
                      {iv.notes && <p className="mt-1.5 text-[11px] leading-6 text-ink-muted">{iv.notes}</p>}
                      <div className="mt-2 flex flex-wrap gap-2">
                        {iv.status === "proposed" && (
                          <Button size="sm" variant="soft" loading={ivBusy} onClick={() => setInterventionStatus(iv.id, "scheduled")}>
                            زمان‌بندی کن
                          </Button>
                        )}
                        {(iv.status === "proposed" || iv.status === "scheduled") && (
                          <>
                            <Button size="sm" variant="success" loading={ivBusy} onClick={() => setInterventionStatus(iv.id, "done")}>
                              انجام شد
                            </Button>
                            <Button size="sm" variant="ghost" loading={ivBusy} onClick={() => setInterventionStatus(iv.id, "cancelled")}>
                              لغو
                            </Button>
                          </>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {!intervention && (
                <Alert variant="warning">
                  اقدام اصلاحی فقط برای صلاحیت در وضعیت «دوره الزامی (آزمایشی)» یا «بحرانی» مجاز است؛ برای سایر وضعیت‌ها سرور با 409 پاسخ می‌دهد.
                </Alert>
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Field label="نوع اقدام">
                  <Select value={ivType} onChange={(e) => setIvType(e.target.value)}>
                    {Object.entries(INTERVENTION_FA).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="توضیح (اختیاری)" className="sm:col-span-2">
                  <Textarea value={ivNotes} onChange={(e) => setIvNotes(e.target.value)} placeholder="شرح کوتاه اقدام، زمان و مسئول…" />
                </Field>
              </div>
              <Button
                variant={intervention ? "primary" : "outline"}
                loading={ivBusy}
                onClick={createIntervention}
                icon={<IconExam size={15} />}
                className="w-full sm:w-auto"
              >
                ثبت اقدام اصلاحی
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </Section>
  );
}

function faDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}
