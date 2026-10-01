"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa, EMPLOYMENT_TYPE_FA, PERMISSION_FA, STAFF_ROLE_FA } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconPlus, IconUsers } from "@/components/ui/icons";

type StaffRow = {
  user_id: number;
  username: string;
  full_name: string;
  system_role: string;
  is_active: boolean;
  employment: { type: string; organization: string; status: string; start_date: string | null };
};

/** نقش‌های مجاز هنگام ساخت کارمند ناحیه (STAFF_ROLES سرور). */
const STAFF_ROLE_OPTIONS = ["district_admin", "district_staff", "teacher"] as const;

const PERMISSION_KEYS = Object.keys(PERMISSION_FA);

export function StaffSection() {
  const [rows, setRows] = useState<StaffRow[]>([]);
  const [districtId, setDistrictId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", full_name: "", role: "district_staff" });
  // پیش‌فرض با سرور یکی است: district_admin بسته کامل می‌گیرد، سایر نقش‌ها بدون مجوز اضافه
  const [perms, setPerms] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<{ district_id: number; staff: StaffRow[] }>("/district/staff");
      setRows(res.staff);
      setDistrictId(res.district_id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت کارکنان");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function changeRole(role: string) {
    setForm((f) => ({ ...f, role }));
    // مدیر ناحیه بسته کامل می‌گیرد؛ سایر نقش‌ها بدون مجوز اضافه ساخته می‌شوند
    setPerms(role === "district_admin" ? PERMISSION_KEYS : []);
  }

  function togglePerm(key: string) {
    setPerms((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  }

  async function createStaff(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api<{ ok: boolean; user_id: number; granted: string[] }>("/district/staff", {
        method: "POST",
        json: {
          username: form.username.trim(),
          password: form.password,
          full_name: form.full_name.trim(),
          role: form.role,
          permission_keys: perms,
        },
      });
      toast(`کارمند «${form.full_name}» ساخته شد${res.granted.length ? ` — ${fa(res.granted.length)} مجوز اعطا شد` : ""}.`, "success");
      setOpen(false);
      setForm({ username: "", password: "", full_name: "", role: "district_staff" });
      setPerms([]);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ساخت کارمند", "error");
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<StaffRow>[] = [
    {
      key: "name",
      header: "کارمند",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.full_name}</p>
          <p className="num text-[11px] text-ink-faint">
            {row.username} · #{row.user_id}
          </p>
        </div>
      ),
    },
    {
      key: "role",
      header: "نقش سامانه",
      align: "center",
      render: (row) => <Badge tone="primary">{STAFF_ROLE_FA[row.system_role] ?? row.system_role}</Badge>,
    },
    {
      key: "employment",
      header: "نوع استخدام",
      align: "center",
      render: (row) => (
        <span className="text-xs">
          {EMPLOYMENT_TYPE_FA[row.employment.type] ?? row.employment.type}
          <span className="text-ink-faint"> · {row.employment.organization}</span>
        </span>
      ),
    },
    {
      key: "start",
      header: "از تاریخ",
      align: "center",
      render: (row) => <span className="num text-xs">{row.employment.start_date ? faDate(row.employment.start_date) : "—"}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <div className="flex flex-wrap justify-center gap-1.5">
          <Badge tone={row.is_active ? "success" : "danger"} dot>
            {row.is_active ? "فعال" : "غیرفعال"}
          </Badge>
          <Badge tone={row.employment.status === "active" ? "info" : "neutral"}>
            استخدام {row.employment.status === "active" ? "جاری" : row.employment.status}
          </Badge>
        </div>
      ),
    },
  ];

  return (
    <Section
      title="کارکنان اداری ناحیه"
      subtitle="کارکنان دارای استخدام در خودِ ناحیه (organization=district)."
      action={
        <Button size="sm" icon={<IconPlus size={15} />} onClick={() => setOpen(true)}>
          افزودن کارمند
        </Button>
      }
    >
      {districtId !== null && (
        <Alert variant="info">
          ناحیه فعال: شناسه {fa(districtId)} — همه کارکنان ساخته‌شده در حوزه همین ناحیه مجوز می‌گیرند.
        </Alert>
      )}

      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={4} cols={5} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.user_id}
          empty={<EmptyState compact icon={<IconUsers size={24} />} title="کارمندی ثبت نشده" description="با دکمه «افزودن کارمند» اولین کارمند ناحیه را بسازید." />}
        />
      )}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="افزودن کارمند ناحیه"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              انصراف
            </Button>
            <Button onClick={createStaff} loading={busy} icon={<IconPlus size={15} />}>
              ساخت کارمند
            </Button>
          </>
        }
      >
        <form onSubmit={createStaff} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="نام کامل" required>
              <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="نام و نام خانوادگی" required />
            </Field>
            <Field label="نام کاربری" required hint="برای ورود به سامانه">
              <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="مثلاً staff1" required />
            </Field>
            <Field label="رمز عبور" required hint="حداقل ۶ نویسه">
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="••••••" required />
            </Field>
            <Field label="نقش" required>
              <Select value={form.role} onChange={(e) => changeRole(e.target.value)}>
                {STAFF_ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {STAFF_ROLE_FA[r] ?? r}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <div className="rounded-xl border border-line bg-surface-sunken p-3.5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-bold text-ink">بسته مجوزها (اختیاری)</p>
              <div className="flex gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => setPerms(PERMISSION_KEYS)}>
                  همه
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setPerms([])}>
                  هیچ
                </Button>
              </div>
            </div>
            <p className="mb-2 text-[11px] leading-5 text-ink-faint">
              مجوزها با حوزه «ناحیه» تفویض می‌شوند؛ تفویض خارج از حوزه فعلی شما با خطای سرور رد می‌شود.
            </p>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {PERMISSION_KEYS.map((key) => (
                <label key={key} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-muted transition hover:bg-white/70">
                  <input
                    type="checkbox"
                    checked={perms.includes(key)}
                    onChange={() => togglePerm(key)}
                    className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                  />
                  {PERMISSION_FA[key]}
                </label>
              ))}
            </div>
          </div>

          {/* ارسال صریح فرم با دکمه پایین مودال؛ این دکمه مخفی برای Enter است */}
          <button type="submit" className="hidden" aria-hidden="true" tabIndex={-1} />
        </form>
      </Modal>
    </Section>
  );
}

function faDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fa-IR");
}
