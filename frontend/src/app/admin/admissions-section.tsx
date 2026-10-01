"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { ADMISSION_STATUS_FA, GRADE_OPTIONS, fa, gradeFa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconInbox, IconPlus, IconRefresh, IconUsers, IconX } from "@/components/ui/icons";

/** درخواست ثبت‌نام — GET /admin/admission-requests */
type AdmissionRequest = {
  id: number;
  full_name: string;
  username: string;
  grade: string;
  phone?: string | null;
  school_id: number;
  school_name?: string | null;
  status: string;
  created_at: string;
};

/** کلاس مدرسه — GET /admin/school/{school_id}/classes */
type SchoolClass = {
  id: number;
  name: string;
  grade: string;
  capacity: number;
  students_count: number;
};

type StatusFilter = "" | "pending" | "approved" | "rejected";

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "pending", label: "در انتظار" },
  { key: "approved", label: "تأییدشده" },
  { key: "rejected", label: "ردشده" },
  { key: "", label: "همه" },
];

/** نرمال‌سازی پاسخ لیست: آرایهٔ خام یا { total, requests: [...] }. */
function normalizeRequests(res: unknown): AdmissionRequest[] {
  if (Array.isArray(res)) return res as AdmissionRequest[];
  if (res && typeof res === "object") {
    const requests = (res as { requests?: unknown }).requests;
    if (Array.isArray(requests)) return requests as AdmissionRequest[];
  }
  return [];
}

/** نرمال‌سازی پاسخ کلاس‌ها: آرایهٔ خام یا { classes: [...] }. */
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

export function AdmissionsSection({ schoolId }: { schoolId: number | null }) {
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [rows, setRows] = useState<AdmissionRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // تصمیم‌گیری (تأیید با انتخاب کلاس / رد)
  const [deciding, setDeciding] = useState<AdmissionRequest | null>(null);
  const [mode, setMode] = useState<"approve" | "reject">("approve");
  const [classId, setClassId] = useState("");
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [classesLoading, setClassesLoading] = useState(false);
  const [classesError, setClassesError] = useState("");
  const [decideError, setDecideError] = useState("");
  const [decidingBusy, setDecidingBusy] = useState(false);

  // افزودن مستقیم دانش‌آموز
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ username: "", password: "", full_name: "", grade: "grade_7", class_id: "" });
  const [addErrors, setAddErrors] = useState<{ username?: string; password?: string; full_name?: string; class_id?: string; form?: string }>({});
  const [adding, setAdding] = useState(false);

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

  const loadClasses = useCallback(async (sid: number) => {
    setClassesLoading(true);
    setClassesError("");
    setClasses([]);
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
    setClassId("");
    setDecideError("");
    if (m === "approve") loadClasses(row.school_id);
  }

  async function confirmDecide() {
    if (!deciding) return;
    if (mode === "approve" && !classId) {
      setDecideError("برای تأیید، کلاس را انتخاب کنید.");
      return;
    }
    setDecidingBusy(true);
    setDecideError("");
    try {
      const json: { approve: boolean; class_id?: number } =
        mode === "approve" ? { approve: true, class_id: Number(classId) } : { approve: false };
      await api(`/admin/admission-requests/${deciding.id}/decide`, { method: "POST", json });
      toast(mode === "approve" ? "دانش‌آموز تأیید و فعال شد" : "درخواست ثبت‌نام رد شد", mode === "approve" ? "success" : "info");
      setDeciding(null);
      await load(filter);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 400) setDecideError(e.detail ?? "اطلاعات ارسالی معتبر نیست؛ کلاس را انتخاب کنید.");
        else if (e.status === 403) toast(e.detail ?? "تصمیم‌گیری در ثبت‌نام در حوزه دسترسی شما نیست", "error");
        else if (e.status === 409) toast(e.detail ?? "این درخواست قبلاً بررسی شده است", "error");
        else toast(e.message || "خطا در تصمیم‌گیری", "error");
      } else {
        toast(e instanceof Error ? e.message : "خطا در تصمیم‌گیری", "error");
      }
    } finally {
      setDecidingBusy(false);
    }
  }

  function openAdd() {
    setAddForm({ username: "", password: "", full_name: "", grade: "grade_7", class_id: "" });
    setAddErrors({});
    setAddOpen(true);
    if (schoolId !== null) loadClasses(schoolId);
  }

  async function submitAdd(e: React.FormEvent) {
    e.preventDefault();
    const errs: typeof addErrors = {};
    if (!addForm.username.trim()) errs.username = "نام کاربری الزامی است";
    if (addForm.password.length < 6) errs.password = "رمز عبور باید حداقل ۶ کاراکتر باشد";
    if (!addForm.full_name.trim()) errs.full_name = "نام کامل الزامی است";
    if (!addForm.class_id) errs.class_id = "انتخاب کلاس الزامی است";
    setAddErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setAdding(true);
    try {
      await api("/admin/students", {
        method: "POST",
        json: {
          username: addForm.username.trim(),
          password: addForm.password,
          full_name: addForm.full_name.trim(),
          grade: addForm.grade,
          class_id: Number(addForm.class_id),
        },
      });
      toast("دانش‌آموز ایجاد شد", "success");
      setAddOpen(false);
      await load(filter);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) setAddErrors({ username: "نام کاربری قبلاً استفاده شده" });
        else if (e.status === 400) setAddErrors({ form: e.detail ?? "اطلاعات واردشده معتبر نیست" });
        else if (e.status === 403) toast(e.detail ?? "افزودن دانش‌آموز در حوزه دسترسی شما نیست", "error");
        else toast(e.message || "خطا در ایجاد دانش‌آموز", "error");
      } else {
        toast(e instanceof Error ? e.message : "خطا در ایجاد دانش‌آموز", "error");
      }
    } finally {
      setAdding(false);
    }
  }

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
      render: (row) => <span className="text-xs">{row.school_name ?? `مدرسه #${row.school_id}`}</span>,
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

  return (
    <Section
      title="درخواست‌های ثبت‌نام دانش‌آموزان"
      subtitle="تأیید نهایی با انتخاب کلاس انجام می‌شود؛ دانش‌آموز بلافاصله فعال می‌شود."
      action={
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => load(filter)}>
            تازه‌سازی
          </Button>
          <Button size="sm" icon={<IconPlus size={14} />} onClick={openAdd} disabled={schoolId === null}>
            افزودن مستقیم دانش‌آموز
          </Button>
        </div>
      }
    >
      {/* فیلتر وضعیت */}
      <div className="flex flex-wrap gap-2">
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
              description="درخواست‌های جدید ثبت‌نام از دانش‌آموزان اینجا نمایش داده می‌شود."
            />
          }
        />
      )}

      {/* ——— مودال تصمیم (تأیید با کلاس / رد) ——— */}
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
                {gradeFa(deciding.grade)} · {deciding.school_name ?? `مدرسه #${deciding.school_id}`}
              </p>
            </div>

            {mode === "approve" && (
              <Field label="کلاس مقصد" required>
                {classesLoading ? (
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
                {!classesLoading && !classesError && classes.length === 0 && (
                  <span className="mt-1 block text-[11px] text-ink-faint">کلاسی برای این مدرسه ثبت نشده است.</span>
                )}
              </Field>
            )}

            {mode === "reject" && <Alert variant="warning">درخواست رد می‌شود و دانش‌آموز فعال نخواهد شد.</Alert>}
            {decideError && <Alert variant="danger">{decideError}</Alert>}
          </div>
        )}
      </Modal>

      {/* ——— مودال افزودن مستقیم دانش‌آموز ——— */}
      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="افزودن مستقیم دانش‌آموز"
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)} disabled={adding}>
              انصراف
            </Button>
            <Button type="submit" form="admission-add-form" loading={adding} icon={<IconPlus size={14} />}>
              ایجاد دانش‌آموز
            </Button>
          </>
        }
      >
        <form id="admission-add-form" onSubmit={submitAdd} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {schoolId === null && (
            <div className="sm:col-span-2">
              <Alert variant="warning" title="مدرسه‌ای شناسایی نشد">
                پیش از افزودن دانش‌آموز، اطلاعات مدرسه باید بارگذاری شود.
              </Alert>
            </div>
          )}
          <Field label="نام کامل" required>
            <Input
              value={addForm.full_name}
              onChange={(e) => setAddForm({ ...addForm, full_name: e.target.value })}
              placeholder="مثال: علی رضایی"
            />
            {addErrors.full_name && <span className="mt-1 block text-[11px] text-danger-600">{addErrors.full_name}</span>}
          </Field>
          <Field label="نام کاربری" required>
            <Input
              value={addForm.username}
              onChange={(e) => setAddForm({ ...addForm, username: e.target.value })}
              className="num"
              placeholder="username"
              autoComplete="off"
            />
            {addErrors.username && <span className="mt-1 block text-[11px] text-danger-600">{addErrors.username}</span>}
          </Field>
          <Field label="رمز عبور" required hint="حداقل ۶ کاراکتر">
            <Input
              type="password"
              value={addForm.password}
              onChange={(e) => setAddForm({ ...addForm, password: e.target.value })}
              autoComplete="new-password"
            />
            {addErrors.password && <span className="mt-1 block text-[11px] text-danger-600">{addErrors.password}</span>}
          </Field>
          <Field label="پایه تحصیلی" required>
            <Select value={addForm.grade} onChange={(e) => setAddForm({ ...addForm, grade: e.target.value })}>
              {GRADE_OPTIONS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="کلاس" required className="sm:col-span-2">
            {classesLoading ? (
              <Select disabled value="">
                <option>در حال بارگذاری کلاس‌ها…</option>
              </Select>
            ) : (
              <Select value={addForm.class_id} onChange={(e) => setAddForm({ ...addForm, class_id: e.target.value })}>
                <option value="">— انتخاب کلاس —</option>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {classLabel(c)}
                  </option>
                ))}
              </Select>
            )}
            {addErrors.class_id && <span className="mt-1 block text-[11px] text-danger-600">{addErrors.class_id}</span>}
            {!classesLoading && classes.length === 0 && schoolId !== null && (
              <span className="mt-1 block text-[11px] text-ink-faint">کلاسی برای این مدرسه ثبت نشده است.</span>
            )}
          </Field>
          {addErrors.form && (
            <div className="sm:col-span-2">
              <Alert variant="danger">{addErrors.form}</Alert>
            </div>
          )}
        </form>
      </Modal>

      <p className="flex items-center gap-1.5 text-[11px] leading-6 text-ink-faint">
        <IconUsers size={13} /> پس از تأیید، حساب دانش‌آموز فعال می‌شود و می‌تواند با نام کاربری و رمز خود وارد شود.
      </p>
    </Section>
  );
}
