"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { GRADE_OPTIONS, STATUS_FA, SUBJECT_FA, fa, gradeFa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { StatCard } from "@/components/ui/stat";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconPlus, IconRefresh, IconSchool, IconUsers, IconX } from "@/components/ui/icons";

/** دانش‌آموز — GET /admin/school/{school_id}/roster */
type StudentRow = { user_id: number; full_name: string | null; username: string | null; grade: string; status: string; class_id: number | null };

/** کلاس همراه با اعضایش */
type RosterClass = { id: number; name: string; grade: string; capacity: number; students_count: number; students: StudentRow[] };

type Roster = { school_id: number; total_students: number; unassigned_students: StudentRow[]; classes: RosterClass[] };

type Shift = { id: number; name: string; start_time: string; end_time: string; order: number };

/** کادر آموزشی — GET /admin/school/{school_id}/staff */
type StaffTeacher = {
  user_id: number;
  full_name: string | null;
  classes: string[];
  subjects: string[];
  shifts: string[];
  has_schedule: boolean;
  weekly_sessions: number;
  weekly_hours: number;
  days: number[];
  day_names: string[];
};

type Staff = { school_id: number; shifts: Shift[]; teachers: StaffTeacher[] };

/** تخصیص معلم به کلاس — GET /admin/classes/{class_id}/teachers */
type ClassTeacher = { assignment_id: number; teacher_user_id: number; full_name: string | null; subject: string | null; start_date: string | null };

/** پاسخ نرمِ 200: { ok:false, reason } */
type Soft = { ok?: boolean; reason?: string };

const SUBJECT_KEYS = Object.keys(SUBJECT_FA);

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message.trim()) return e.message;
  return fallback;
}

/** یک سطر دانش‌آموز در کارت کلاس / لیست «بدون کلاس». */
function StudentLine({ s, onMove }: { s: StudentRow; onMove: (s: StudentRow) => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface-sunken px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-xs font-bold text-ink">{s.full_name ?? "بدون نام"}</p>
        <p className="num truncate text-[11px] text-ink-faint">{s.username ? `@${s.username}` : "—"}</p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <Badge tone="neutral">{gradeFa(s.grade)}</Badge>
        <Badge tone={statusTone(s.status)}>{STATUS_FA[s.status] ?? s.status}</Badge>
        <Button size="sm" variant="ghost" onClick={() => onMove(s)}>انتقال</Button>
      </div>
    </div>
  );
}

export function RosterSection({ schoolId }: { schoolId: number | null }) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [staff, setStaff] = useState<Staff | null>(null);
  const [loading, setLoading] = useState(true);

  // افزودن / ویرایش کلاس
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ name: "", grade: "grade_7", capacity: "30" });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<RosterClass | null>(null);
  const [editForm, setEditForm] = useState({ name: "", capacity: "" });
  const [editingBusy, setEditingBusy] = useState(false);

  // جابه‌جایی دانش‌آموز
  const [moving, setMoving] = useState<StudentRow | null>(null);
  const [moveClass, setMoveClass] = useState("");
  const [movingBusy, setMovingBusy] = useState(false);

  // معلمان کلاس
  const [teachersFor, setTeachersFor] = useState<RosterClass | null>(null);
  const [classTeachers, setClassTeachers] = useState<ClassTeacher[]>([]);
  const [teachersLoading, setTeachersLoading] = useState(false);
  const [assignForm, setAssignForm] = useState({ teacher: "", subject: SUBJECT_KEYS[0] ?? "" });
  const [assignBusy, setAssignBusy] = useState(false);

  const load = useCallback(async (sid: number) => {
    setLoading(true);
    try {
      const [r, s] = await Promise.all([api<Roster>(`/admin/school/${sid}/roster`), api<Staff>(`/admin/school/${sid}/staff`)]);
      setRoster(r);
      setStaff(s);
    } catch (e) {
      toast(errMsg(e, "خطا در دریافت رکورد دانش‌آموزان"), "error");
    } finally {
      setLoading(false);
    }
  }, []);

  const reload = useCallback(() => {
    if (schoolId !== null) load(schoolId);
  }, [schoolId, load]);

  useEffect(() => {
    if (schoolId !== null) load(schoolId);
  }, [schoolId, load]);

  // ——— افزودن کلاس ———
  async function submitAdd(e: React.FormEvent) {
    e.preventDefault();
    if (schoolId === null) return;
    const name = addForm.name.trim();
    if (!name) return toast("نام کلاس الزامی است", "error");
    setAdding(true);
    try {
      const res = await api<Soft>(`/admin/school/${schoolId}/classes`, {
        method: "POST",
        json: { name, grade: addForm.grade, capacity: Number(addForm.capacity) || 30 },
      });
      if (res && res.ok === false) return toast(res.reason ?? "کلاس ایجاد نشد", "error");
      toast("کلاس ایجاد شد", "success");
      setAddOpen(false);
      setAddForm({ name: "", grade: "grade_7", capacity: "30" });
      await load(schoolId);
    } catch (e) {
      toast(errMsg(e, "خطا در ایجاد کلاس"), "error");
    } finally {
      setAdding(false);
    }
  }

  // ——— جابه‌جایی دانش‌آموز ———
  function openMove(s: StudentRow) {
    setMoving(s);
    setMoveClass(s.class_id === null ? "" : String(s.class_id));
  }

  async function submitMove() {
    if (!moving || schoolId === null) return;
    setMovingBusy(true);
    try {
      const res = await api<Soft & { class_id?: number | null; unchanged?: boolean }>(
        `/admin/school/${schoolId}/students/${moving.user_id}`,
        { method: "PATCH", json: { class_id: moveClass === "" ? null : Number(moveClass) } }
      );
      if (res && res.ok === false) return toast(res.reason ?? "جابه‌جایی انجام نشد", "error");
      const unchanged = res?.unchanged === true;
      toast(unchanged ? "تغییری اعمال نشد" : "جابه‌جایی انجام شد", unchanged ? "info" : "success");
      setMoving(null);
      await load(schoolId);
    } catch (e) {
      toast(errMsg(e, "خطا در جابه‌جایی دانش‌آموز"), "error");
    } finally {
      setMovingBusy(false);
    }
  }

  // ——— ویرایش کلاس ———
  function openEdit(c: RosterClass) {
    setEditing(c);
    setEditForm({ name: c.name, capacity: String(c.capacity) });
  }

  async function submitEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditingBusy(true);
    try {
      const res = await api<Soft>(`/admin/classes/${editing.id}`, {
        method: "PATCH",
        json: { name: editForm.name.trim(), capacity: Number(editForm.capacity) || editing.capacity },
      });
      if (res && res.ok === false) return toast(res.reason ?? "ذخیره کلاس انجام نشد", "error");
      toast("کلاس به‌روزرسانی شد", "success");
      setEditing(null);
      reload();
    } catch (e) {
      toast(errMsg(e, "خطا در ویرایش کلاس"), "error");
    } finally {
      setEditingBusy(false);
    }
  }

  // ——— معلمان کلاس ———
  const loadClassTeachers = useCallback(async (classId: number) => {
    setTeachersLoading(true);
    try {
      const res = await api<{ teachers?: ClassTeacher[] }>(`/admin/classes/${classId}/teachers`);
      setClassTeachers(res && Array.isArray(res.teachers) ? res.teachers : []);
    } catch (e) {
      setClassTeachers([]);
      toast(errMsg(e, "خطا در دریافت معلمان کلاس"), "error");
    } finally {
      setTeachersLoading(false);
    }
  }, []);

  function openTeachers(c: RosterClass) {
    setTeachersFor(c);
    setClassTeachers([]);
    setAssignForm({ teacher: "", subject: SUBJECT_KEYS[0] ?? "" });
    loadClassTeachers(c.id);
  }

  async function submitAssign() {
    if (!teachersFor) return;
    if (!assignForm.teacher || !assignForm.subject) return toast("معلم و درس را انتخاب کنید", "error");
    setAssignBusy(true);
    try {
      const res = await api<Soft>(`/admin/classes/${teachersFor.id}/teachers`, {
        method: "POST",
        json: { teacher_user_id: Number(assignForm.teacher), subject: assignForm.subject },
      });
      if (res && res.ok === false) return toast(res.reason ?? "تخصیص انجام نشد", "error");
      toast("معلم به کلاس تخصیص یافت", "success");
      await loadClassTeachers(teachersFor.id);
      reload();
    } catch (e) {
      toast(errMsg(e, "خطا در تخصیص معلم"), "error");
    } finally {
      setAssignBusy(false);
    }
  }

  async function removeTeacher(assignmentId: number) {
    if (!teachersFor) return;
    try {
      const res = await api<Soft>(`/admin/classes/${teachersFor.id}/teachers/${assignmentId}`, { method: "DELETE" });
      if (res && res.ok === false) return toast(res.reason ?? "تخصیص خاتمه نیافت", "error");
      toast("تخصیص خاتمه یافت", "success");
      await loadClassTeachers(teachersFor.id);
      reload();
    } catch (e) {
      toast(errMsg(e, "خطا در خاتمه تخصیص"), "error");
    }
  }

  if (schoolId === null) return null;

  const classes = roster?.classes ?? [];
  const unassigned = roster?.unassigned_students ?? [];
  const staffTeachers = staff?.teachers ?? [];

  return (
    <Section
      title="رکورد دانش‌آموزان"
      subtitle="همه دانش‌آموزان با جایگاه کلاسی، ساخت و ویرایش کلاس و تخصیص معلم"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="soft" onClick={reload} loading={loading} icon={<IconRefresh size={15} />}>به‌روزرسانی</Button>
          <Button size="sm" onClick={() => setAddOpen(true)} icon={<IconPlus size={15} />}>افزودن کلاس</Button>
        </div>
      }
    >
      {loading && !roster ? (
        <SkeletonTable rows={6} cols={4} />
      ) : (
        <>
          {/* آمار کلی */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="تعداد کلاس‌ها" value={fa(classes.length)} icon={<IconSchool size={20} />} hint="کلاس‌های این مدرسه" />
            <StatCard label="دانش‌آموزان" value={fa(roster?.total_students ?? 0)} tone="primary" icon={<IconUsers size={20} />} hint="ثبت‌شده در مدرسه" />
            <StatCard label="بدون کلاس" value={fa(unassigned.length)} tone="warning" icon={<IconAlert size={20} />} hint="نیازمند جایگزینی" />
          </div>

          {/* کارت کلاس‌ها */}
          {classes.length === 0 ? (
            <EmptyState
              icon={<IconSchool size={26} />}
              title="کلاسی ثبت نشده"
              description="برای شروع، از دکمهٔ «افزودن کلاس» اولین کلاس مدرسه را بسازید."
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {classes.map((c) => (
                <Card key={c.id} className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-ink">{c.name}</span>
                    <Badge tone="neutral">{gradeFa(c.grade)}</Badge>
                    <Badge tone={c.students_count >= c.capacity ? "danger" : "primary"}>{`${fa(c.students_count)}/${fa(c.capacity)}`}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="soft" onClick={() => openEdit(c)}>ویرایش</Button>
                    <Button size="sm" variant="soft" onClick={() => openTeachers(c)}>معلمان</Button>
                  </div>
                  <div className="space-y-2">
                    {c.students.length === 0 ? (
                      <EmptyState compact title="دانش‌آموزی ندارد" />
                    ) : (
                      c.students.map((s) => <StudentLine key={s.user_id} s={s} onMove={openMove} />)
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}

          {/* دانش‌آموزان بدون کلاس */}
          {unassigned.length > 0 && (
            <Card>
              <CardHeader title="بدون کلاس" subtitle="این دانش‌آموزان هنوز در هیچ کلاسی جایگذاری نشده‌اند." icon={<IconAlert size={16} />} />
              <div className="space-y-2">
                {unassigned.map((s) => <StudentLine key={s.user_id} s={s} onMove={openMove} />)}
              </div>
            </Card>
          )}
        </>
      )}

      {/* ——— مودال افزودن کلاس ——— */}
      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="افزودن کلاس"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)} disabled={adding}>انصراف</Button>
            <Button type="submit" form="roster-add-form" loading={adding} icon={<IconPlus size={14} />}>ایجاد کلاس</Button>
          </>
        }
      >
        <form id="roster-add-form" onSubmit={submitAdd} className="space-y-3">
          <Field label="نام کلاس" required>
            <Input value={addForm.name} onChange={(e) => setAddForm({ ...addForm, name: e.target.value })} placeholder="۱۰۳" autoComplete="off" />
          </Field>
          <Field label="پایه تحصیلی" required>
            <Select value={addForm.grade} onChange={(e) => setAddForm({ ...addForm, grade: e.target.value })}>
              {GRADE_OPTIONS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
            </Select>
          </Field>
          <Field label="ظرفیت" required hint="حداکثر ۱۰۰ نفر">
            <Input type="number" min={1} max={100} className="num" value={addForm.capacity} onChange={(e) => setAddForm({ ...addForm, capacity: e.target.value })} />
          </Field>
        </form>
      </Modal>

      {/* ——— مودال جابه‌جایی دانش‌آموز ——— */}
      <Modal
        open={moving !== null}
        onClose={() => setMoving(null)}
        title={`جابه‌جایی ${moving?.full_name ?? ""}`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setMoving(null)} disabled={movingBusy}>انصراف</Button>
            <Button loading={movingBusy} onClick={submitMove}>انتقال</Button>
          </>
        }
      >
        {moving && (
          <div className="space-y-3">
            <div className="rounded-xl bg-surface-sunken p-3 text-xs leading-6">
              <p className="font-bold text-ink">{moving.full_name ?? "بدون نام"}</p>
              <p className="num text-ink-faint">{moving.username ? `@${moving.username}` : "—"}</p>
            </div>
            <Field label="کلاس مقصد" required>
              <Select value={moveClass} onChange={(e) => setMoveClass(e.target.value)}>
                <option value="">بدون کلاس</option>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} — {fa(c.students_count)}/{fa(c.capacity)}
                  </option>
                ))}
              </Select>
            </Field>
            <p className="text-[11px] leading-6 text-ink-faint">ظرفیت تکمیل باشد انتقال انجام نمی‌شود و پیام خطا نمایش داده می‌شود.</p>
          </div>
        )}
      </Modal>

      {/* ——— مودال ویرایش کلاس ——— */}
      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={`ویرایش کلاس ${editing?.name ?? ""}`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)} disabled={editingBusy}>انصراف</Button>
            <Button type="submit" form="roster-edit-form" loading={editingBusy}>ذخیره</Button>
          </>
        }
      >
        <form id="roster-edit-form" onSubmit={submitEdit} className="space-y-3">
          <Field label="نام کلاس" required>
            <Input value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} autoComplete="off" />
          </Field>
          <Field label="ظرفیت" required hint="کمتر از تعداد ثبت‌شده پذیرفته نمی‌شود.">
            <Input type="number" min={1} max={100} className="num" value={editForm.capacity} onChange={(e) => setEditForm({ ...editForm, capacity: e.target.value })} />
          </Field>
        </form>
      </Modal>

      {/* ——— مودال معلمان کلاس ——— */}
      <Modal
        open={teachersFor !== null}
        onClose={() => setTeachersFor(null)}
        title={`معلمان کلاس ${teachersFor?.name ?? ""}`}
        size="md"
        footer={<Button variant="ghost" onClick={() => setTeachersFor(null)}>بستن</Button>}
      >
        {teachersFor && (
          <div className="space-y-4">
            {teachersLoading ? (
              <SkeletonTable rows={3} cols={3} />
            ) : classTeachers.length === 0 ? (
              <EmptyState compact title="معلمی به این کلاس تخصیص ندارد" />
            ) : (
              <div className="space-y-2">
                {classTeachers.map((t) => (
                  <div key={t.assignment_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface-sunken px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold text-ink">{t.full_name ?? "بدون نام"}</span>
                      <Badge tone="primary">{subjectFa(t.subject)}</Badge>
                      {t.start_date && <span className="num text-[11px] text-ink-faint">از {t.start_date}</span>}
                    </div>
                    <Button size="sm" variant="ghost" icon={<IconX size={13} />} onClick={() => removeTeacher(t.assignment_id)}>خاتمه تخصیص</Button>
                  </div>
                ))}
              </div>
            )}

            {staffTeachers.length === 0 ? (
              <EmptyState compact title="معلمی در مدرسه ثبت نشده" />
            ) : (
              <Card variant="sunken" className="space-y-3">
                <p className="text-xs font-bold text-ink">افزودن معلم</p>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="معلم" required>
                    <Select value={assignForm.teacher} onChange={(e) => setAssignForm({ ...assignForm, teacher: e.target.value })}>
                      <option value="">— انتخاب معلم —</option>
                      {staffTeachers.map((t) => (
                        <option key={t.user_id} value={t.user_id}>{t.full_name ?? `معلم #${t.user_id}`}</option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="درس" required>
                    <Select value={assignForm.subject} onChange={(e) => setAssignForm({ ...assignForm, subject: e.target.value })}>
                      {SUBJECT_KEYS.map((k) => <option key={k} value={k}>{subjectFa(k)}</option>)}
                    </Select>
                  </Field>
                </div>
                <Button size="sm" loading={assignBusy} onClick={submitAssign} icon={<IconPlus size={14} />}>تخصیص معلم</Button>
              </Card>
            )}
          </div>
        )}
      </Modal>
    </Section>
  );
}
