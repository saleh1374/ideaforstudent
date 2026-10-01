"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { ADMISSION_STATUS_FA, fa, gradeFa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconInbox, IconRefresh, IconSchool, IconUsers, IconX } from "@/components/ui/icons";

/**
 * درخواست ثبت‌نام — GET /admin/admission-requests
 * درخواست‌های «بدون مدرسه» (school_id = null) فقط در سطح ناحیه و بالاتر دیده
 * می‌شوند؛ تأیید آن‌ها ملزم به تعیین مدرسه است (decide با school_id).
 */
type AdmissionRequest = {
  id: number;
  full_name: string;
  username: string;
  grade: string;
  phone?: string | null;
  school_id: number | null;
  school_name?: string | null;
  status: string;
  created_at: string;
};

/** مدرسه ناحیه — GET /district/me/schools */
type DistrictSchool = { id: number; name: string; school_code: string; status: string };

/** کلاس مدرسه — GET /admin/school/{school_id}/classes */
type SchoolClass = { id: number; name: string; grade: string; capacity: number; students_count: number };

type StatusFilter = "" | "pending" | "approved" | "rejected";

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "pending", label: "در انتظار" },
  { key: "approved", label: "تأییدشده" },
  { key: "rejected", label: "ردشده" },
  { key: "", label: "همه" },
];

function normalizeRequests(res: unknown): AdmissionRequest[] {
  if (Array.isArray(res)) return res as AdmissionRequest[];
  if (res && typeof res === "object") {
    const requests = (res as { requests?: unknown }).requests;
    if (Array.isArray(requests)) return requests as AdmissionRequest[];
  }
  return [];
}

function normalizeSchools(res: unknown): DistrictSchool[] {
  if (res && typeof res === "object") {
    const schools = (res as { schools?: unknown }).schools;
    if (Array.isArray(schools)) return schools as DistrictSchool[];
  }
  return [];
}

function normalizeClasses(res: unknown): SchoolClass[] {
  if (Array.isArray(res)) return res as SchoolClass[];
  if (res && typeof res === "object") {
    const classes = (res as { classes?: unknown }).classes;
    if (Array.isArray(classes)) return classes as SchoolClass[];
  }
  return [];
}

function faDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fa-IR", { dateStyle: "short" });
}

export function AdmissionsSection({ onChanged }: { onChanged?: () => void }) {
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [rows, setRows] = useState<AdmissionRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // مدارس ناحیه (برای تعیین مدرسه درخواست‌های بدون مدرسه)
  const [schools, setSchools] = useState<DistrictSchool[]>([]);
  const [schoolsLoaded, setSchoolsLoaded] = useState(false);

  // تصمیم‌گیری (تأیید با تعیین مدرسه (در صورت نیاز) + انتخاب کلاس / رد)
  const [deciding, setDeciding] = useState<AdmissionRequest | null>(null);
  const [mode, setMode] = useState<"approve" | "reject">("approve");
  const [schoolId, setSchoolId] = useState("");
  const [classId, setClassId] = useState("");
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [classesLoading, setClassesLoading] = useState(false);
  const [classesError, setClassesError] = useState("");
  const [decideError, setDecideError] = useState("");
  const [decidingBusy, setDecidingBusy] = useState(false);

  const load = useCallback(async (st: StatusFilter) => {
    setLoading(true);
    setError("");
    try {
      const res = await api<unknown>(`/admin/admission-requests${st ? `?status=${encodeURIComponent(st)}` : ""}`);
      setRows(normalizeRequests(res));
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : "خطا در دریافت درخواست‌ها");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filter);
  }, [filter, load]);

  // بارگذاری یک‌باره مدارس ناحیه (تنبل — فقط وقتی لازم شود)
  const loadSchools = useCallback(async () => {
    if (schoolsLoaded) return;
    try {
      setSchools(normalizeSchools(await api<unknown>("/district/me/schools?status=active")));
      setSchoolsLoaded(true);
    } catch {
      /* در مودال خطای جدا نمایش داده می‌شود */
    }
  }, [schoolsLoaded]);

  const loadClasses = useCallback(async (sid: number) => {
    setClassesLoading(true);
    setClassesError("");
    setClasses([]);
    setClassId("");
    try {
      setClasses(normalizeClasses(await api<unknown>(`/admin/school/${sid}/classes`)));
    } catch (e) {
      setClassesError(e instanceof Error ? e.message : "خطا در دریافت کلاس‌ها");
    } finally {
      setClassesLoading(false);
    }
  }, []);

  function openDecide(row: AdmissionRequest, m: "approve" | "reject") {
    setDeciding(row);
    setMode(m);
    setSchoolId("");
    setClassId("");
    setClasses([]);
    setClassesError("");
    setDecideError("");
    if (m !== "approve") return;
    if (row.school_id !== null) {
      loadClasses(row.school_id);
    } else {
      // درخواست بدون مدرسه → نخست مدرسه ناحیه انتخاب می‌شود
      void loadSchools();
    }
  }

  function onSchoolChange(sid: string) {
    setSchoolId(sid);
    if (sid) loadClasses(Number(sid));
    else {
      setClasses([]);
      setClassId("");
      setClassesError("");
    }
  }

  async function confirmDecide() {
    if (!deciding) return;
    const needsSchool = deciding.school_id === null;
    if (mode === "approve" && needsSchool && !schoolId) {
      setDecideError("برای تأیید این درخواست، ابتدا مدرسه مقصد را تعیین کنید.");
      return;
    }
    if (mode === "approve" && !classId) {
      setDecideError("برای تأیید، کلاس را انتخاب کنید.");
      return;
    }
    setDecidingBusy(true);
    setDecideError("");
    try {
      const json: { approve: boolean; class_id?: number; school_id?: number } =
        mode === "approve"
          ? {
              approve: true,
              class_id: Number(classId),
              ...(needsSchool ? { school_id: Number(schoolId) } : {}),
            }
          : { approve: false };
      await api(`/admin/admission-requests/${deciding.id}/decide`, { method: "POST", json });
      toast(mode === "approve" ? "دانش‌آموز تأیید و فعال شد" : "درخواست ثبت‌نام رد شد", mode === "approve" ? "success" : "info");
      setDeciding(null);
      await load(filter);
      onChanged?.();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 400) setDecideError(e.detail ?? "مدرسه و کلاس مقصد را انتخاب کنید.");
        else if (e.status === 403) toast(e.detail ?? "تصمیم‌گیری در ثبت‌نام در حوزه دسترسی شما نیست", "error");
        else if (e.status === 409) {
          toast(e.detail ?? "این درخواست قبلاً بررسی شده است", "error");
          setDeciding(null);
          await load(filter);
        } else toast(e.message || "خطا در تصمیم‌گیری", "error");
      } else {
        toast(e instanceof Error ? e.message : "خطا در تصمیم‌گیری", "error");
      }
    } finally {
      setDecidingBusy(false);
    }
  }

  const needsSchoolCount = rows.filter((r) => r.status === "pending" && r.school_id === null).length;
  const classLabel = (c: SchoolClass) => `${c.name} — ${gradeFa(c.grade)} (${fa(c.students_count)}/${fa(c.capacity)})`;

  const columns: Column<AdmissionRequest>[] = [
    {
      key: "name",
      header: "نام",
      render: (row) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{row.full_name}</p>
        </div>
      ),
    },
    { key: "username", header: "نام کاربری", align: "center", render: (row) => <span className="num text-xs">{row.username}</span> },
    { key: "grade", header: "پایه", align: "center", render: (row) => <Badge tone="neutral">{gradeFa(row.grade)}</Badge> },
    { key: "phone", header: "تلفن", align: "center", render: (row) => <span className="num text-xs">{row.phone ?? "—"}</span> },
    {
      key: "school",
      header: "مدرسه",
      align: "center",
      render: (row) =>
        row.school_id === null ? (
          <Badge tone="warning" dot>
            بدون مدرسه — تعیین لازم
          </Badge>
        ) : (
          <span className="text-xs">{row.school_name ?? `مدرسه #${row.school_id}`}</span>
        ),
    },
    { key: "created", header: "تاریخ ثبت", align: "center", render: (row) => <span className="num text-xs">{faDate(row.created_at)}</span> },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={statusTone(row.status)} dot>
          {ADMISSION_STATUS_FA[row.status] ?? row.status}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (row) =>
        row.status === "pending" ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="sm" variant="success" onClick={() => openDecide(row, "approve")} icon={<IconCheckCircle size={14} />}>
              تأیید
            </Button>
            <Button size="sm" variant="ghost" onClick={() => openDecide(row, "reject")} icon={<IconX size={14} />}>
              رد
            </Button>
          </div>
        ) : (
          <span className="text-[11px] text-ink-faint">بررسی‌شده</span>
        ),
    },
  ];

  const decidingNeedsSchool = deciding !== null && deciding.school_id === null;

  return (
    <Section
      title="درخواست‌های ثبت‌نام دانش‌آموزان"
      subtitle="درخواست‌های بدون مدرسه فقط این‌جا دیده می‌شوند؛ تأیید نهایی با تعیین مدرسه و انتخاب کلاس انجام می‌شود."
      action={
        <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => load(filter)}>
          تازه‌سازی
        </Button>
      }
    >
      {/* فیلتر وضعیت */}
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key || "all"}
            type="button"
            onClick={() => setFilter(f.key)}
            className={[
              "rounded-full border px-3.5 py-1.5 text-[11px] font-bold transition",
              filter === f.key
                ? "border-primary-300 bg-primary-50 text-primary-700"
                : "border-line bg-surface text-ink-muted hover:border-primary-300 hover:text-primary-700",
            ].join(" ")}
          >
            {f.label}
          </button>
        ))}
        {needsSchoolCount > 0 && (
          <Badge tone="warning" dot>
            {fa(needsSchoolCount)} درخواست بدون مدرسه
          </Badge>
        )}
      </div>

      {error && (
        <Alert variant="danger" title="خطا در دریافت درخواست‌ها">
          {error}
        </Alert>
      )}

      {loading ? (
        <SkeletonTable rows={5} cols={6} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.id}
          empty={
            <EmptyState
              compact
              icon={<IconInbox size={24} />}
              title="درخواستی در این وضعیت نیست"
              description="درخواست‌های جدید ثبت‌نام (با یا بدون مدرسه) اینجا نمایش داده می‌شود."
            />
          }
        />
      )}

      {/* ——— مودال تصمیم (تعیین مدرسه (در صورت نیاز) + انتخاب کلاس / رد) ——— */}
      <Modal
        open={deciding !== null}
        onClose={() => setDeciding(null)}
        title={mode === "approve" ? `تأیید ثبت‌نام «${deciding?.full_name ?? ""}»` : `رد ثبت‌نام «${deciding?.full_name ?? ""}»`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeciding(null)} disabled={decidingBusy}>
              انصراف
            </Button>
            <Button
              variant={mode === "approve" ? "success" : "danger"}
              loading={decidingBusy}
              onClick={confirmDecide}
              icon={mode === "approve" ? <IconCheckCircle size={14} /> : <IconX size={14} />}
            >
              {mode === "approve" ? "تأیید و فعال‌سازی" : "رد درخواست"}
            </Button>
          </>
        }
      >
        {deciding && (
          <div className="space-y-3">
            <div className="rounded-xl bg-surface-sunken p-3 text-xs leading-6">
              <p>
                <b className="text-ink">{deciding.full_name}</b> — <span className="num">@{deciding.username}</span>
              </p>
              <p className="text-ink-muted">
                {gradeFa(deciding.grade)} ·{" "}
                {deciding.school_id === null ? (
                  <span className="text-warning-600">بدون مدرسه — تعیین مدرسه الزامی است</span>
                ) : (
                  (deciding.school_name ?? `مدرسه #${deciding.school_id}`)
                )}
              </p>
            </div>

            {mode === "approve" && decidingNeedsSchool && (
              <Field label="مدرسه مقصد" required>
                <Select value={schoolId} onChange={(e) => onSchoolChange(e.target.value)}>
                  <option value="">— انتخاب مدرسه —</option>
                  {schools.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
                {!schoolsLoaded && schools.length === 0 && (
                  <span className="mt-1 block text-[11px] text-ink-faint">در حال بارگذاری مدارس ناحیه…</span>
                )}
                {schoolsLoaded && schools.length === 0 && (
                  <span className="mt-1 block text-[11px] text-ink-faint">مدرسه فعالی در این ناحیه ثبت نشده است؛ نخست از تب «مدارس ناحیه» مدرسه ثبت کنید.</span>
                )}
              </Field>
            )}

            {mode === "approve" && (
              <Field label="کلاس مقصد" required>
                {decidingNeedsSchool && !schoolId ? (
                  <Select disabled value="">
                    <option>ابتدا مدرسه را انتخاب کنید</option>
                  </Select>
                ) : classesLoading ? (
                  <Select disabled value="">
                    <option>در حال بارگذاری کلاس‌ها…</option>
                  </Select>
                ) : (
                  <Select value={classId} onChange={(e) => setClassId(e.target.value)}>
                    <option value="">— انتخاب کلاس —</option>
                    {classes.map((c) => (
                      <option key={c.id} value={c.id}>
                        {classLabel(c)}
                      </option>
                    ))}
                  </Select>
                )}
                {classesError && <span className="mt-1 block text-[11px] text-danger-600">{classesError}</span>}
                {!classesLoading && !classesError && schoolId !== "" && classes.length === 0 && (
                  <span className="mt-1 block text-[11px] text-ink-faint">کلاسی برای این مدرسه ثبت نشده است.</span>
                )}
              </Field>
            )}

            {mode === "reject" && <Alert variant="warning">درخواست رد می‌شود و دانش‌آموز فعال نخواهد شد.</Alert>}
            {decideError && <Alert variant="danger">{decideError}</Alert>}
          </div>
        )}
      </Modal>

      <p className="flex items-center gap-1.5 text-[11px] leading-6 text-ink-faint">
        <IconSchool size={13} /> پس از تأیید، حساب دانش‌آموز با مدرسه و کلاس انتخاب‌شده فعال می‌شود؛ درخواست‌های بدون مدرسه در سطح مدرسه دیده نمی‌شوند.
      </p>
      <p className="flex items-center gap-1.5 text-[11px] leading-6 text-ink-faint">
        <IconUsers size={13} /> ردِ درخواست فقط وضعیت را تغییر می‌دهد و کاربری ساخته نمی‌شود.
      </p>
    </Section>
  );
}
