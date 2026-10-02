"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SUBJECT_FA, fa, gradeFa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select } from "@/components/ui/forms";
import { SkeletonTable } from "@/components/ui/skeleton";
import { DataTable, type Column } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import { IconClock, IconPlus, IconRefresh, IconUsers } from "@/components/ui/icons";

type Shift = { id: number; name: string; start_time: string; end_time: string; order: number };

/** جلسهٔ برنامهٔ هفتگی — GET /admin/school/{school_id}/schedule */
type Entry = {
  id: number;
  day: number;
  day_name: string;
  start_time: string;
  end_time: string;
  subject: string;
  teacher_user_id: number | null;
  teacher_name: string | null;
};

type ClassSchedule = { class_id: number; class_name: string; grade: string; school_id: number; shifts: Shift[]; entries: Entry[] };

type ScheduleData = { school_id: number; shifts: Shift[]; classes: ClassSchedule[] };

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

type Sub = "shifts" | "schedule" | "staff";

/** سطر قابل‌ویرایش شیفت */
type ShiftRow = { name: string; start_time: string; end_time: string };

/** سطر پیش‌نویس برنامه (بدون id / day_name / teacher_name) */
type DraftRow = { day: number; start_time: string; end_time: string; subject: string; teacher_user_id: number | null };

/** پاسخ نرمِ 200: { ok:false, reason } */
type Soft = { ok?: boolean; reason?: string };

const DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"];
const SUBJECT_KEYS = Object.keys(SUBJECT_FA);

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message.trim()) return e.message;
  return fallback;
}

function toDraft(entries: Entry[]): DraftRow[] {
  return entries.map((e) => ({
    day: e.day,
    start_time: e.start_time,
    end_time: e.end_time,
    subject: e.subject,
    teacher_user_id: e.teacher_user_id,
  }));
}

/** نوار شیفت‌های مدرسه (در تب شیفت‌ها و کادر آموزشی). */
function ShiftBadges({ shifts }: { shifts: Shift[] }) {
  if (shifts.length === 0) return <span className="text-[11px] text-ink-faint">شیفتی ثبت نشده است.</span>;
  return (
    <div className="flex flex-wrap gap-2">
      {shifts.map((s) => (
        <Badge key={s.id} tone="primary">{`${s.name} · ${s.start_time}–${s.end_time}`}</Badge>
      ))}
    </div>
  );
}

/** ستون‌های جدول کادر آموزشی — بار هفتگی از برنامهٔ هفتگی است. */
const STAFF_COLUMNS: Column<StaffTeacher>[] = [
  {
    key: "name",
    header: "نام",
    render: (t) => (
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink">{t.full_name ?? "بدون نام"}</span>
        {t.has_schedule === false && <Badge tone="warning">بدون برنامه</Badge>}
      </span>
    ),
  },
  { key: "classes", header: "کلاس‌ها", align: "center", render: (t) => t.classes.join("، ") || "—" },
  { key: "subjects", header: "دروس", align: "center", render: (t) => t.subjects.map(subjectFa).join("، ") || "—" },
  {
    key: "shifts",
    header: "شیفت",
    align: "center",
    render: (t) =>
      t.shifts.length ? (
        <span className="flex flex-wrap items-center justify-center gap-1">
          {t.shifts.map((s) => <Badge tone="primary" key={s}>{s}</Badge>)}
        </span>
      ) : (
        "—"
      ),
  },
  { key: "sessions", header: "جلسات هفتگی", align: "center", render: (t) => <span className="num">{fa(t.weekly_sessions)}</span> },
  {
    key: "hours",
    header: "ساعت هفتگی",
    align: "center",
    render: (t) => (
      <span>
        <span className="num">{fa(t.weekly_hours, 1)}</span> ساعت
      </span>
    ),
  },
  { key: "days", header: "روزها", align: "center", render: (t) => t.day_names.join("، ") || "—" },
];

export function ScheduleSection({ schoolId }: { schoolId: number | null }) {
  const [sub, setSub] = useState<Sub>("shifts");
  const [data, setData] = useState<ScheduleData | null>(null);
  const [staff, setStaff] = useState<Staff | null>(null);
  const [loading, setLoading] = useState(true);

  // ویرایشگر شیفت‌ها
  const [rows, setRows] = useState<ShiftRow[]>([]);
  const [savingShifts, setSavingShifts] = useState(false);

  // برنامهٔ هفتگی
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DraftRow[]>([]);
  const [savingDraft, setSavingDraft] = useState(false);

  const load = useCallback(async (sid: number) => {
    setLoading(true);
    try {
      const [s, st] = await Promise.all([
        api<ScheduleData>(`/admin/school/${sid}/schedule`),
        api<Staff>(`/admin/school/${sid}/staff`),
      ]);
      setData(s);
      setStaff(st);
    } catch (e) {
      toast(errMsg(e, "خطا در دریافت برنامه مدرسه"), "error");
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

  // همگام‌سازی فرم شیفت‌ها با دادهٔ تازه (پس از هر بارگذاری)
  useEffect(() => {
    setRows((data?.shifts ?? []).map((s) => ({ name: s.name, start_time: s.start_time, end_time: s.end_time })));
    setEditing(false);
  }, [data]);

  function updateRow(i: number, patch: Partial<ShiftRow>) {
    setRows((prev) => prev.map((r, x) => (x === i ? { ...r, ...patch } : r)));
  }

  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, x) => x !== i));
  }

  function addRow() {
    setRows((prev) => [...prev, { name: `شیفت ${prev.length + 1}`, start_time: "08:00", end_time: "12:00" }]);
  }

  async function saveShifts() {
    if (schoolId === null) return;
    setSavingShifts(true);
    try {
      const res = await api<Soft>(`/admin/school/${schoolId}/shifts`, {
        method: "PUT",
        json: { shifts: rows.map((r) => ({ name: r.name.trim(), start_time: r.start_time, end_time: r.end_time })) },
      });
      if (res && res.ok === false) return toast(res.reason ?? "شیفت‌ها ذخیره نشد", "error");
      toast("شیفت‌ها ذخیره شد", "success");
      await load(schoolId);
    } catch (e) {
      toast(errMsg(e, "خطا در ذخیره شیفت‌ها"), "error");
    } finally {
      setSavingShifts(false);
    }
  }

  // ——— ویرایش برنامهٔ هفتگی ———
  const classes = data?.classes ?? [];
  const selected = classes.find((c) => c.class_id === selectedId) ?? classes[0] ?? null;
  const teacherOptions = staff?.teachers ?? [];

  function startEdit() {
    if (!selected) return;
    setDraft(toDraft(selected.entries));
    setEditing(true);
  }

  function cancelEdit() {
    if (selected) setDraft(toDraft(selected.entries));
    setEditing(false);
  }

  function updateDraft(i: number, patch: Partial<DraftRow>) {
    setDraft((prev) => prev.map((r, x) => (x === i ? { ...r, ...patch } : r)));
  }

  function removeSession(i: number) {
    setDraft((prev) => prev.filter((_, x) => x !== i));
  }

  function addSession() {
    setDraft((prev) => [
      ...prev,
      { day: 0, start_time: "08:00", end_time: "09:00", subject: SUBJECT_KEYS[0] ?? "", teacher_user_id: null },
    ]);
  }

  async function saveDraft() {
    if (!selected || schoolId === null) return;
    setSavingDraft(true);
    try {
      await api(`/admin/classes/${selected.class_id}/schedule`, { method: "PUT", json: { entries: draft } });
      toast("برنامه هفتگی ذخیره شد", "success");
      setEditing(false);
      await load(schoolId);
    } catch (e) {
      toast(errMsg(e, "خطا در ذخیره برنامه هفتگی"), "error");
    } finally {
      setSavingDraft(false);
    }
  }

  if (schoolId === null) return null;

  return (
    <Section
      title="برنامه‌ریزی مدرسه"
      subtitle="شیفت‌ها، برنامه هفتگی کلاس‌ها و کادر آموزشی از یک منبع حقیقت"
      action={
        <Button size="sm" variant="soft" onClick={reload} loading={loading} icon={<IconRefresh size={15} />}>به‌روزرسانی</Button>
      }
    >
      <Tabs
        items={[
          { key: "shifts", label: "شیفت‌ها" },
          { key: "schedule", label: "برنامه هفتگی" },
          { key: "staff", label: "کادر آموزشی" },
        ]}
        value={sub}
        onChange={(k) => setSub(k as Sub)}
      />

      {loading && !data ? (
        <SkeletonTable rows={5} cols={5} />
      ) : sub === "shifts" ? (
        /* ——————— تب شیفت‌ها ——————— */
        <Section title="شیفت‌های مدرسه" subtitle="تک‌شیفت یا دوشیفت با بازهٔ ساعتی مشخص">
          <Alert variant="info">
            برای مدرسه تک‌شیفت یک بازه (مثلاً ۰۸:۰۰–۱۵:۰۰) و برای دوشیفت دو بازه (۰۸:۰۰–۱۲:۰۰ و ۱۲:۰۰–۱۸:۰۰) تعریف کنید.
            ساعت‌ها باید بدون تداخل باشند.
          </Alert>

          <div className="space-y-3">
            {rows.map((r, i) => (
              <Card key={i} className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                <Field label="نام شیفت" required>
                  <Input value={r.name} onChange={(e) => updateRow(i, { name: e.target.value })} placeholder="شیفت صبح" />
                </Field>
                <Field label="شروع" required>
                  <Input type="time" className="num" value={r.start_time} onChange={(e) => updateRow(i, { start_time: e.target.value })} />
                </Field>
                <Field label="پایان" required>
                  <Input type="time" className="num" value={r.end_time} onChange={(e) => updateRow(i, { end_time: e.target.value })} />
                </Field>
                <div className="flex items-end">
                  <Button size="sm" variant="ghost" disabled={rows.length <= 1} onClick={() => removeRow(i)}>حذف</Button>
                </div>
              </Card>
            ))}
            {rows.length === 0 && <EmptyState compact title="شیفتی ثبت نشده" description="برای شروع یک شیفت اضافه کنید." />}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="soft" icon={<IconPlus size={14} />} disabled={rows.length >= 3} onClick={addRow}>
              افزودن شیفت
            </Button>
            <span className="text-[11px] text-ink-faint">حداکثر ۳ شیفت</span>
            <Button onClick={saveShifts} loading={savingShifts} disabled={rows.length === 0} icon={<IconClock size={15} />}>
              ذخیره شیفت‌ها
            </Button>
          </div>

          <p className="text-[11px] leading-6 text-ink-faint">
            اگر برنامه هفتگی جلسه‌ای خارج از شیفت جدید دارد، ابتدا آن جلسه را اصلاح کنید.
          </p>
        </Section>
      ) : sub === "schedule" ? (
        /* ——————— تب برنامه هفتگی ——————— */
        <Section
          title="برنامه هفتگی کلاس‌ها"
          subtitle="هر ستون یک روز هفته است؛ جلسات بر اساس ساعت شروع مرتب شده‌اند."
          action={selected && !editing ? <Button size="sm" variant="soft" onClick={startEdit}>ویرایش برنامه</Button> : undefined}
        >
          {classes.length === 0 ? (
            <EmptyState title="کلاسی ثبت نشده" description="پیش از تدوین برنامه هفتگی، کلاسی برای مدرسه بسازید." />
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-[220px] flex-1">
                  <Select
                    value={selected ? String(selected.class_id) : ""}
                    onChange={(e) => {
                      setSelectedId(Number(e.target.value));
                      setEditing(false);
                    }}
                  >
                    {classes.map((c) => (
                      <option key={c.class_id} value={c.class_id}>
                        {c.class_name} — {gradeFa(c.grade)}
                      </option>
                    ))}
                  </Select>
                </div>
                {selected && <Badge tone="primary">{fa(selected.entries.length)} جلسه</Badge>}
              </div>

              <ShiftBadges shifts={data?.shifts ?? []} />

              {selected && (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-7">
                  {DAYS.map((dayName, dayIdx) => {
                    const list = selected.entries
                      .filter((e) => e.day === dayIdx)
                      .sort((a, b) => a.start_time.localeCompare(b.start_time));
                    return (
                      <div key={dayName} className="overflow-hidden rounded-xl border border-line bg-surface">
                        <div className="bg-surface-sunken px-2 py-1.5 text-center text-[11px] font-bold text-ink-muted">{dayName}</div>
                        <div className="space-y-1.5 p-1.5">
                          {list.length === 0 ? (
                            <p className="py-3 text-center text-[11px] text-ink-faint">—</p>
                          ) : (
                            list.map((e) => (
                              <div key={e.id} className="space-y-0.5 rounded-lg border border-line-soft bg-surface-sunken p-2">
                                <p className="num text-[11px] font-bold text-ink">
                                  {e.start_time}–{e.end_time}
                                </p>
                                <p className="text-[11px] font-semibold text-primary-700">{subjectFa(e.subject)}</p>
                                <p className="truncate text-[10px] text-ink-faint">{e.teacher_name ?? "بدون معلم"}</p>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* ویرایشگر برنامهٔ هفتگی */}
              {editing && selected && (
                <Card className="space-y-3">
                  <Alert variant="warning">ذخیره، کل برنامه هفتگی این کلاس را جایگزین می‌کند.</Alert>

                  <div className="space-y-2">
                    {draft.map((row, i) => (
                      <div key={i} className="grid grid-cols-1 gap-2 rounded-xl border border-line bg-surface-sunken p-3 sm:grid-cols-6">
                        <Field label="روز">
                          <Select value={String(row.day)} onChange={(e) => updateDraft(i, { day: Number(e.target.value) })}>
                            {DAYS.map((d, idx) => <option key={d} value={idx}>{d}</option>)}
                          </Select>
                        </Field>
                        <Field label="شروع">
                          <Input type="time" className="num" value={row.start_time} onChange={(e) => updateDraft(i, { start_time: e.target.value })} />
                        </Field>
                        <Field label="پایان">
                          <Input type="time" className="num" value={row.end_time} onChange={(e) => updateDraft(i, { end_time: e.target.value })} />
                        </Field>
                        <Field label="درس">
                          <Select value={row.subject} onChange={(e) => updateDraft(i, { subject: e.target.value })}>
                            {SUBJECT_KEYS.map((k) => <option key={k} value={k}>{subjectFa(k)}</option>)}
                          </Select>
                        </Field>
                        <Field label="معلم">
                          <Select
                            value={row.teacher_user_id === null ? "" : String(row.teacher_user_id)}
                            onChange={(e) => updateDraft(i, { teacher_user_id: e.target.value === "" ? null : Number(e.target.value) })}
                          >
                            <option value="">بدون معلم</option>
                            {teacherOptions.map((t) => (
                              <option key={t.user_id} value={t.user_id}>{t.full_name ?? `معلم #${t.user_id}`}</option>
                            ))}
                          </Select>
                        </Field>
                        <div className="flex items-end">
                          <Button size="sm" variant="ghost" onClick={() => removeSession(i)}>حذف</Button>
                        </div>
                      </div>
                    ))}
                    {draft.length === 0 && <EmptyState compact title="جلسه‌ای ثبت نشده" description="برای شروع یک جلسه اضافه کنید." />}
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" variant="soft" icon={<IconPlus size={14} />} onClick={addSession}>افزودن جلسه</Button>
                    <Button size="sm" onClick={saveDraft} loading={savingDraft}>ذخیره</Button>
                    <Button size="sm" variant="ghost" onClick={cancelEdit} disabled={savingDraft}>انصراف</Button>
                  </div>
                </Card>
              )}
            </div>
          )}
        </Section>
      ) : (
        /* ——————— تب کادر آموزشی ——————— */
        <Section title="کادر آموزشی" subtitle="بار هفتگی هر معلم از برنامه هفتگی استخراج شده است.">
          <Card>
            <CardHeader title="شیفت‌های مدرسه" subtitle="همان تعریف‌های تب «شیفت‌ها» — فقط خواندنی." icon={<IconClock size={16} />} />
            <ShiftBadges shifts={data?.shifts ?? []} />
          </Card>

          <p className="flex items-center gap-1.5 text-xs font-bold text-ink">
            <IconUsers size={15} /> معلمان و کادر آموزشی
          </p>

          <DataTable
            columns={STAFF_COLUMNS}
            rows={teacherOptions}
            keyOf={(t) => t.user_id}
            empty={<EmptyState compact title="کادر آموزشی ثبت نشده" />}
          />

          <p className="text-[11px] leading-6 text-ink-faint">بار هفتگی از همان برنامه هفتگی محاسبه می‌شود — یک منبع حقیقت.</p>
        </Section>
      )}
    </Section>
  );
}
