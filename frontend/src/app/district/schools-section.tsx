"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { fa, OWNERSHIP_FA, SCHOOL_TYPE_FA } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, SearchInput, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconPlus, IconSchool, IconSearch, IconX } from "@/components/ui/icons";

type SchoolRow = {
  id: number;
  name: string;
  school_code: string;
  school_type: string;
  ownership_type: string;
  status: string;
  principal: { user_id: number; full_name: string } | null;
  students_count: number;
  students_with_data: number;
  avg_mastery: number | null;
  weak_count: number | null;
  status_counts: Record<string, number> | null;
  suppressed: boolean;
  min_group: number;
};

type Candidate = { user_id: number; full_name: string; hint: string };

const SCHOOL_STATUS_TONE: Record<string, Tone> = { active: "success", inactive: "neutral" };
const SCHOOL_STATUS_FA: Record<string, string> = { active: "فعال", inactive: "غیرفعال" };

export function SchoolsSection({ onChanged }: { onChanged?: () => void }) {
  const [rows, setRows] = useState<SchoolRow[]>([]);
  const [districtName, setDistrictName] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // مودال ایجاد مدرسه
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", school_code: "", school_type: "high_school", ownership_type: "public", address: "" });

  // مودال تغییر وضعیت
  const [statusTarget, setStatusTarget] = useState<SchoolRow | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);

  // مودال تغییر مدیر مدرسه
  const [principalTarget, setPrincipalTarget] = useState<SchoolRow | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [principalUserId, setPrincipalUserId] = useState("");
  const [principalBusy, setPrincipalBusy] = useState(false);

  const load = useCallback(async (st: string, q: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (st) params.set("status", st);
      if (q.trim()) params.set("search", q.trim());
      const res = await api<{ district: { id: number; name: string | null }; total: number; schools: SchoolRow[] }>(
        `/district/me/schools${params.toString() ? `?${params.toString()}` : ""}`
      );
      setRows(res.schools);
      setDistrictName(res.district.name);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت مدارس");
    } finally {
      setLoading(false);
    }
  }, []);

  // بارگذاری اولیه بی‌درنگ؛ تغییر فیلتر/جست‌وجو با تأخیر کوتاه (debounce)
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      load(status, search);
      return;
    }
    const t = window.setTimeout(() => {
      load(status, search);
    }, 350);
    return () => window.clearTimeout(t);
  }, [status, search, load]);

  async function createSchool(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await api("/district/schools", { method: "POST", json: { ...form, address: form.address.trim() || null } });
      toast(`مدرسه «${form.name}» ثبت شد.`, "success");
      setCreateOpen(false);
      setForm({ name: "", school_code: "", school_type: "high_school", ownership_type: "public", address: "" });
      await load(status, search);
      onChanged?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ثبت مدرسه", "error");
    } finally {
      setCreating(false);
    }
  }

  async function toggleStatus() {
    if (!statusTarget) return;
    const next = statusTarget.status === "active" ? "inactive" : "active";
    setStatusBusy(true);
    try {
      await api(`/district/schools/${statusTarget.id}`, { method: "PATCH", json: { status: next } });
      toast(`وضعیت «${statusTarget.name}» ${next === "active" ? "فعال" : "غیرفعال"} شد.`, "success");
      setStatusTarget(null);
      await load(status, search);
      onChanged?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در تغییر وضعیت", "error");
    } finally {
      setStatusBusy(false);
    }
  }

  async function openPrincipal(row: SchoolRow) {
    setPrincipalTarget(row);
    setPrincipalUserId(row.principal ? String(row.principal.user_id) : "");
    setCandidateQuery("");
    setCandidates([]);
    try {
      const [teachers, staff] = await Promise.allSettled([
        api<{ teachers: { user_id: number; full_name: string; school_name: string | null }[] }>("/district/teachers"),
        api<{ staff: { user_id: number; full_name: string; username: string; system_role: string }[] }>("/district/staff"),
      ]);
      const list: Candidate[] = [];
      if (teachers.status === "fulfilled") {
        for (const t of teachers.value.teachers) {
          list.push({ user_id: t.user_id, full_name: t.full_name, hint: `معلم · ${t.school_name ?? "—"}` });
        }
      }
      if (staff.status === "fulfilled") {
        for (const s of staff.value.staff) {
          list.push({ user_id: s.user_id, full_name: s.full_name, hint: `کارمند ناحیه · ${s.username}` });
        }
      }
      const seen = new Set<number>();
      const unique: Candidate[] = [];
      for (const c of list) {
        if (!seen.has(c.user_id)) {
          seen.add(c.user_id);
          unique.push(c);
        }
      }
      setCandidates(unique);
    } catch {
      setCandidates([]); // ورود دستی شناسه همیشه ممکن است
    }
  }

  async function appointPrincipal() {
    if (!principalTarget) return;
    const userId = Number(principalUserId);
    if (!Number.isFinite(userId) || userId <= 0) {
      toast("شناسه کاربر معتبر وارد کنید.", "warning");
      return;
    }
    setPrincipalBusy(true);
    try {
      const res = await api<{ ok: boolean; changed: boolean }>(`/district/schools/${principalTarget.id}/principal`, {
        method: "POST",
        json: { user_id: userId },
      });
      if (res.changed) toast(`مدیر مدرسه «${principalTarget.name}» تغییر کرد.`, "success");
      else toast("این کاربر از قبل مدیر همین مدرسه است.", "info");
      setPrincipalTarget(null);
      await load(status, search);
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در انتصاب مدیر", "error");
    } finally {
      setPrincipalBusy(false);
    }
  }

  const filteredCandidates = candidates.filter(
    (c) => !candidateQuery.trim() || c.full_name.includes(candidateQuery.trim()) || String(c.user_id) === candidateQuery.trim()
  );

  const columns: Column<SchoolRow>[] = [
    {
      key: "name",
      header: "مدرسه",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.name}</p>
          <p className="num text-[11px] text-ink-faint">
            {row.school_code} · {SCHOOL_TYPE_FA[row.school_type] ?? row.school_type} · {OWNERSHIP_FA[row.ownership_type] ?? row.ownership_type}
          </p>
        </div>
      ),
    },
    {
      key: "principal",
      header: "مدیر مدرسه",
      render: (row) =>
        row.principal ? (
          <span className="font-semibold text-ink">{row.principal.full_name}</span>
        ) : (
          <span className="text-[11px] text-ink-faint">انتصاب نشده</span>
        ),
    },
    {
      key: "students",
      header: "دانش‌آموز",
      align: "center",
      render: (row) => (
        <span className="num text-xs">
          {fa(row.students_count)}
          <span className="text-ink-faint"> / {fa(row.students_with_data)} دارای داده</span>
        </span>
      ),
    },
    {
      key: "mastery",
      header: "تسط / ضعف",
      align: "center",
      render: (row) =>
        row.suppressed ? (
          <span className="text-[11px] text-ink-faint">زیر حد نصاب ({fa(row.min_group)} نفر)</span>
        ) : (
          <span className="num text-xs font-bold text-ink">
            {row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}
            {row.weak_count !== null && <span className="mr-1 font-normal text-danger-600">· {fa(row.weak_count)} ضعیف</span>}
          </span>
        ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={SCHOOL_STATUS_TONE[row.status] ?? "neutral"} dot>
          {SCHOOL_STATUS_FA[row.status] ?? row.status}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (row) => (
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="soft" onClick={() => setStatusTarget(row)}>
            {row.status === "active" ? "غیرفعال کردن" : "فعال کردن"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => openPrincipal(row)}>
            تغییر مدیر
          </Button>
        </div>
      ),
    },
  ];

  return (
    <Section
      title={`مدارس ناحیه${districtName ? ` ${districtName}` : ""}`}
      subtitle="جست‌وجو و فیلتر وضعیت روی سمت سرور انجام می‌شود؛ اعداد زیر حداقل جمعیت سرکوب می‌شوند."
      action={
        <Button size="sm" icon={<IconPlus size={15} />} onClick={() => setCreateOpen(true)}>
          ثبت مدرسه جدید
        </Button>
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
          <option value="">همه وضعیت‌ها</option>
          <option value="active">فعال</option>
          <option value="inactive">غیرفعال</option>
        </Select>
        <SearchInput value={search} onChange={setSearch} placeholder="جست‌وجو بر اساس نام یا کد مدرسه…" className="w-full sm:w-72" />
      </div>

      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={5} cols={5} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.id}
          empty={<EmptyState compact icon={<IconSchool size={24} />} title="مدرسه‌ای یافت نشد" description="فیلتر را تغییر دهید یا مدرسه جدیدی ثبت کنید." />}
        />
      )}

      {/* ---------- ایجاد مدرسه ---------- */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="ثبت مدرسه جدید"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              انصراف
            </Button>
            <Button onClick={createSchool} loading={creating} icon={<IconPlus size={15} />}>
              ثبت مدرسه
            </Button>
          </>
        }
      >
        <form onSubmit={createSchool} className="space-y-3">
          <Field label="نام مدرسه" required>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="مثلاً دبیرستان شهید بهشتی" required />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="کد مدرسه" required hint="کد باید یکتا باشد">
              <Input value={form.school_code} onChange={(e) => setForm({ ...form, school_code: e.target.value })} placeholder="S-1003" required />
            </Field>
            <Field label="نوع مدرسه">
              <Select value={form.school_type} onChange={(e) => setForm({ ...form, school_type: e.target.value })}>
                {Object.entries(SCHOOL_TYPE_FA).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="نوع مالکیت">
              <Select value={form.ownership_type} onChange={(e) => setForm({ ...form, ownership_type: e.target.value })}>
                {Object.entries(OWNERSHIP_FA).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="نشانی (اختیاری)">
              <Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="نشانی مدرسه" />
            </Field>
          </div>
        </form>
      </Modal>

      {/* ---------- تغییر وضعیت ---------- */}
      <Modal
        open={statusTarget !== null}
        onClose={() => setStatusTarget(null)}
        title="تغییر وضعیت مدرسه"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setStatusTarget(null)}>
              انصراف
            </Button>
            <Button
              variant={statusTarget?.status === "active" ? "danger" : "success"}
              loading={statusBusy}
              onClick={toggleStatus}
              icon={statusTarget?.status === "active" ? <IconX size={15} /> : <IconCheckCircle size={15} />}
            >
              {statusTarget?.status === "active" ? "غیرفعال کردن" : "فعال کردن"}
            </Button>
          </>
        }
      >
        {statusTarget && (
          <p className="leading-7">
            مدرسه <b className="text-ink">{statusTarget.name}</b> ({statusTarget.school_code}){" "}
            {statusTarget.status === "active" ? "غیرفعال" : "فعال"} شود؟ وضعیت غیرفعال روی ثبت‌نام و گزارش‌ها اثر می‌گذارد.
          </p>
        )}
      </Modal>

      {/* ---------- تغییر مدیر مدرسه ---------- */}
      <Modal
        open={principalTarget !== null}
        onClose={() => setPrincipalTarget(null)}
        title={principalTarget ? `مدیر مدرسه — ${principalTarget.name}` : ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPrincipalTarget(null)}>
              انصراف
            </Button>
            <Button loading={principalBusy} onClick={appointPrincipal} icon={<IconCheckCircle size={15} />}>
              ثبت انتصاب
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert variant="info">
            مدیر قبلی به‌صورت خودکار بسته می‌شود. کاربر باید فعال باشد؛ می‌توانید از فهرست زیر انتخاب کنید یا شناسه را دستی وارد کنید.
          </Alert>

          {candidates.length > 0 && (
            <div className="space-y-2">
              <Field label="جست‌وجو در معلمان و کارکنان">
                <SearchInput value={candidateQuery} onChange={setCandidateQuery} placeholder="نام یا شناسه…" />
              </Field>
              <ul className="max-h-44 divide-y divide-line-soft overflow-y-auto rounded-xl border border-line bg-surface">
                {filteredCandidates.length === 0 && (
                  <li className="px-3.5 py-3 text-xs text-ink-faint">موردی با این عبارت پیدا نشد.</li>
                )}
                {filteredCandidates.map((c) => {
                  const selected = String(c.user_id) === principalUserId;
                  return (
                    <li key={c.user_id}>
                      <button
                        type="button"
                        onClick={() => setPrincipalUserId(String(c.user_id))}
                        className={`flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-right text-xs transition ${
                          selected ? "bg-primary-50 text-primary-800" : "hover:bg-surface-sunken"
                        }`}
                      >
                        <span className="font-semibold">{c.full_name}</span>
                        <span className="num text-[11px] text-ink-faint">
                          #{c.user_id} · {c.hint}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <Field label="شناسه کاربر مدیر" required hint="شناسه عددی کاربر در سامانه (ID)">
            <Input
              type="number"
              min={1}
              value={principalUserId}
              onChange={(e) => setPrincipalUserId(e.target.value)}
              placeholder="مثلاً 5"
            />
          </Field>
          {candidates.length === 0 && (
            <p className="flex items-center gap-1.5 text-[11px] text-ink-faint">
              <IconSearch size={13} /> فهرست پیشنهادی در دسترس نیست — شناسه را دستی وارد کنید.
            </p>
          )}
        </div>
      </Modal>
    </Section>
  );
}
