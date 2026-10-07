"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  EMPLOYMENT_TYPE_FA,
  OWNERSHIP_FA,
  PERMISSION_FA,
  fa,
} from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconAlert,
  IconLock,
  IconPlus,
  IconRefresh,
  IconShield,
  IconUsers,
  IconX,
} from "@/components/ui/icons";

/* ——— انواع پاسخ سرور ——— */

type Catalog = {
  permissions: { id: number; key: string; title_fa: string }[];
  roles: { id: number; key: string; title_fa: string; permissions: string[] }[];
  scope_types: string[];
  note_fa: string;
};

type Assignment = {
  id: number;
  user_id: number;
  user_name: string;
  username: string | null;
  permission: string | null;
  permission_fa: string | null;
  role: string | null;
  role_fa: string | null;
  scope_type: string;
  scope_id: number;
  delegated_by_name: string | null;
  valid_from: string | null;
  valid_until: string | null;
  is_active: boolean;
  created_at: string | null;
};

type Mine = { permissions: string[]; scopes: [string, number][] };

type Deputy = {
  id: number;
  school_id: number;
  title_fa: string;
  permission_keys: string[];
  is_active: boolean;
  assigned_users: { user_id: number; full_name: string; title_fa: string | null; assignment_id: number }[];
};

type PolicyRule = {
  id: number;
  school_ownership: string;
  employment_type: string;
  requires_district_approval: boolean;
  note: string | null;
};

type AuditRow = {
  id: number;
  actor_name: string | null;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  detail: string | null;
  created_at: string | null;
};

type Candidate = { user_id: number; full_name: string; username?: string | null };

const SCOPE_FA: Record<string, string> = {
  province: "استان",
  district: "ناحیه",
  school: "مدرسه",
  class: "کلاس",
  student: "دانش‌آموز",
  national: "کشور",
};

const POLICY_OWNERSHIPS = ["public", "non_profit", "private"] as const;
const POLICY_TYPES = ["official", "contractual", "part_time", "temporary"] as const;

function faDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fa-IR");
}

function activeTone(a: Assignment): Tone {
  if (!a.is_active) return "neutral";
  if (a.valid_until && new Date(a.valid_until).getTime() < Date.now()) return "warning";
  return "success";
}

/**
 * تب «دسترسی‌ها»: مجوزهای من + واگذاری/لغو مجوز (قاعدهٔ طلایی در سرور)،
 * نقش‌های معاون با چک‌لیست مجوز (RBAC §6)، جدول سیاست استخدام (§5) و لاگ ممیزی (§17).
 * سه سرویس بک‌اند (`permissions_catalog` / `permission_assignments` / `audit_logs`)
 * پیش‌تر بدون endpoint بودند و اکنون از همین‌جا خوانده می‌شوند.
 */
export function AccessSection({ schoolId, role }: { schoolId: number; role: string }) {
  const [mine, setMine] = useState<Mine | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [deputies, setDeputies] = useState<Deputy[]>([]);
  const [policy, setPolicy] = useState<PolicyRule[]>([]);
  const [logs, setLogs] = useState<AuditRow[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [problems, setProblems] = useState<string[]>([]);

  // ویرایش سیاست فقط سطح ناحیه/استان/کشور (سرور هم چک می‌کند)
  const canPolicy = role === "district_admin" || role === "province_admin" || role === "platform_admin" || role === "ministry";

  const loadAssignments = useCallback(async () => {
    try {
      const res = await api<{ assignments: Assignment[] }>("/admin/permissions/assignments");
      setAssignments(res.assignments);
    } catch {
      /* با بقیه بخش‌ها مدیریت می‌شود */
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const fails: string[] = [];
    const parts = await Promise.allSettled([
      api<Mine>("/admin/permissions/mine"),
      api<Catalog>("/admin/permissions/catalog"),
      api<{ assignments: Assignment[] }>("/admin/permissions/assignments"),
      api<{ deputies: Deputy[] }>(`/admin/schools/${schoolId}/deputies`),
      api<{ rules: PolicyRule[] }>("/admin/employment-policy"),
      api<{ logs: AuditRow[] }>("/admin/audit-logs?limit=50"),
      api<{ teachers: { user_id: number; full_name: string; username: string }[] }>("/admin/teachers-directory"),
      api<{ teachers: { user_id: number; full_name: string | null }[] }>(`/admin/school/${schoolId}/staff`),
    ]);

    if (parts[0].status === "fulfilled") setMine(parts[0].value);
    else fails.push("مجوزهای من");

    if (parts[1].status === "fulfilled") setCatalog(parts[1].value);
    else fails.push("فهرست مجوزها (مدیریت دسترسی)");

    if (parts[2].status === "fulfilled") setAssignments(parts[2].value.assignments);
    else fails.push("دسترسی‌های واگذارشده");

    if (parts[3].status === "fulfilled") setDeputies(parts[3].value.deputies);
    else fails.push("معاونان مدرسه");

    if (parts[4].status === "fulfilled") setPolicy(parts[4].value.rules);
    else fails.push("سیاست استخدام");

    if (parts[5].status === "fulfilled") setLogs(parts[5].value.logs);
    else fails.push("لاگ ممیزی");

    // فهرست انتخابِ گیرندهٔ مجوز: معلمان مدرسه + طرح کلی معلمان (هر دو اختیاری)
    const seen = new Map<number, Candidate>();
    if (parts[6].status === "fulfilled") {
      for (const t of parts[6].value.teachers) seen.set(t.user_id, { user_id: t.user_id, full_name: t.full_name, username: t.username });
    }
    if (parts[7].status === "fulfilled") {
      for (const t of parts[7].value.teachers) {
        if (!seen.has(t.user_id) && t.full_name) seen.set(t.user_id, { user_id: t.user_id, full_name: t.full_name });
      }
    }
    setCandidates(Array.from(seen.values()).sort((a, b) => a.full_name.localeCompare(b.full_name, "fa")));

    setProblems(fails);
    setLoading(false);
  }, [schoolId]);

  useEffect(() => {
    load();
  }, [load]);

  /* ——————— واگذاری مجوز ——————— */
  const [grantOpen, setGrantOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [grant, setGrant] = useState({
    grantee_user_id: 0,
    role_id: 0,
    permission_id: 0,
    scope_type: "school",
    scope_id: schoolId,
    valid_from: "",
    valid_until: "",
  });

  async function submitGrant() {
    if (!grant.grantee_user_id || !grant.role_id || !grant.permission_id) {
      toast("گیرنده، نقش و مجوز را انتخاب کنید.", "error");
      return;
    }
    setBusy(true);
    try {
      await api("/admin/permissions/grant", {
        method: "POST",
        json: {
          grantee_user_id: grant.grantee_user_id,
          role_id: grant.role_id,
          permission_id: grant.permission_id,
          scope_type: grant.scope_type,
          scope_id: Number(grant.scope_id) || 0,
          ...(grant.valid_from ? { valid_from: grant.valid_from } : {}),
          ...(grant.valid_until ? { valid_until: grant.valid_until } : {}),
        },
      });
      toast("مجوز واگذار شد.", "success");
      setGrantOpen(false);
      await Promise.all([loadAssignments(), load()]);
    } catch (e) {
      // 403 سرور = نقض قاعدهٔ طلایی؛ پیام فارسی خودِ سرور نمایش داده می‌شود
      toast(e instanceof Error ? e.message : "خطا در واگذاری مجوز", "error");
    } finally {
      setBusy(false);
    }
  }

  const [revokeId, setRevokeId] = useState<number | null>(null);
  async function submitRevoke() {
    if (revokeId === null) return;
    setBusy(true);
    try {
      await api(`/admin/permissions/${revokeId}/revoke`, { method: "POST" });
      toast("مجوز لغو شد.", "success");
      setRevokeId(null);
      await loadAssignments();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در لغو مجوز", "error");
    } finally {
      setBusy(false);
    }
  }

  /* ——————— معاونان ——————— */
  const [deputyModal, setDeputyModal] = useState<"create" | Deputy | null>(null);
  const [deputyForm, setDeputyForm] = useState<{ title_fa: string; permission_keys: string[] }>({ title_fa: "", permission_keys: [] });
  const [assignTarget, setAssignTarget] = useState<Deputy | null>(null);
  const [assignUserId, setAssignUserId] = useState<number>(0);

  function openDeputy(d: Deputy | null) {
    setDeputyForm(d ? { title_fa: d.title_fa, permission_keys: [...d.permission_keys] } : { title_fa: "", permission_keys: [] });
    setDeputyModal(d ?? "create");
  }

  function toggleKey(key: string) {
    setDeputyForm((f) => ({
      ...f,
      permission_keys: f.permission_keys.includes(key) ? f.permission_keys.filter((k) => k !== key) : [...f.permission_keys, key],
    }));
  }

  async function saveDeputy() {
    if (!deputyForm.title_fa.trim()) {
      toast("عنوان معاون الزامی است.", "error");
      return;
    }
    setBusy(true);
    try {
      if (deputyModal === "create") {
        await api(`/admin/schools/${schoolId}/deputies`, {
          method: "POST",
          json: { title_fa: deputyForm.title_fa.trim(), permission_keys: deputyForm.permission_keys },
        });
        toast("نقش معاون ساخته شد.", "success");
      } else if (deputyModal) {
        await api(`/admin/schools/${schoolId}/deputies/${deputyModal.id}`, {
          method: "PATCH",
          json: { title_fa: deputyForm.title_fa.trim(), permission_keys: deputyForm.permission_keys },
        });
        toast("چک‌لیست مجوزها به‌روزرسانی شد.", "success");
      }
      setDeputyModal(null);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ذخیره نقش معاون", "error");
    } finally {
      setBusy(false);
    }
  }

  async function deactivateDeputy(d: Deputy) {
    try {
      await api(`/admin/schools/${schoolId}/deputies/${d.id}`, { method: "DELETE" });
      toast("نقش معاون غیرفعال شد؛ تاریخچه ممیزی حفظ می‌ماند.", "success");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا", "error");
    }
  }

  async function assignUser() {
    if (!assignTarget || !assignUserId) return;
    setBusy(true);
    try {
      await api(`/admin/schools/${schoolId}/deputies/${assignTarget.id}/assign-user`, {
        method: "POST",
        json: { user_id: assignUserId },
      });
      toast("کاربر به نقش معاون متصل شد و مجوزها با حوزهٔ مدرسه واگذار گردید.", "success");
      setAssignTarget(null);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در اتصال کاربر", "error");
    } finally {
      setBusy(false);
    }
  }

  /* ——————— سیاست استخدام ——————— */
  const [policyOpen, setPolicyOpen] = useState(false);
  const [policyForm, setPolicyForm] = useState({
    school_ownership: "public" as string,
    employment_type: "contractual" as string,
    requires_district_approval: true,
    note: "",
  });

  function openPolicyFor(row: PolicyRule | null) {
    setPolicyForm(
      row
        ? {
            school_ownership: row.school_ownership,
            employment_type: row.employment_type,
            requires_district_approval: row.requires_district_approval,
            note: row.note ?? "",
          }
        : { school_ownership: "public", employment_type: "contractual", requires_district_approval: true, note: "" }
    );
    setPolicyOpen(true);
  }

  async function savePolicy() {
    setBusy(true);
    try {
      await api("/admin/employment-policy", {
        method: "POST",
        json: {
          school_ownership: policyForm.school_ownership,
          employment_type: policyForm.employment_type,
          requires_district_approval: policyForm.requires_district_approval,
          note: policyForm.note || null,
        },
      });
      toast("قانون سیاست استخدام ذخیره شد.", "success");
      setPolicyOpen(false);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ذخیره سیاست", "error");
    } finally {
      setBusy(false);
    }
  }

  /* ——————— جدول‌ها ——————— */
  const assignmentCols: Column<Assignment>[] = [
    {
      key: "user",
      header: "گیرنده",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{r.user_name}</p>
          <p className="num text-[11px] text-ink-faint">{r.username ?? `#${r.user_id}`}</p>
        </div>
      ),
    },
    {
      key: "perm",
      header: "مجوز",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="text-xs font-semibold text-ink">{r.permission_fa ?? (r.permission ? permLabel(r.permission) : "—")}</p>
          <p className="num text-[10px] text-ink-faint">{r.permission}</p>
        </div>
      ),
    },
    {
      key: "scope",
      header: "حوزه",
      align: "center",
      render: (r) => (
        <Badge tone="accent">
          {SCOPE_FA[r.scope_type] ?? r.scope_type} {fa(r.scope_id)}
        </Badge>
      ),
    },
    {
      key: "valid",
      header: "اعتبار",
      align: "center",
      render: (r) => (
        <span className="num text-xs">
          {faDate(r.valid_from)} → {r.valid_until ? faDate(r.valid_until) : "نامحدود"}
        </span>
      ),
    },
    {
      key: "by",
      header: "واگذارکننده",
      render: (r) => <span className="text-xs">{r.delegated_by_name ?? "—"}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (r) => <Badge tone={activeTone(r)} dot>{r.is_active ? "فعال" : "لغوشده"}</Badge>,
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (r) =>
        r.is_active ? (
          <Button size="sm" variant="ghost" icon={<IconX size={14} />} onClick={() => setRevokeId(r.id)}>
            لغو
          </Button>
        ) : null,
    },
  ];

  const deputyCols: Column<Deputy>[] = [
    {
      key: "title",
      header: "نقش معاون",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{r.title_fa}</p>
          <p className="num text-[11px] text-ink-faint">شناسه {fa(r.id)}</p>
        </div>
      ),
    },
    {
      key: "keys",
      header: "چک‌لیست مجوزها",
      render: (r) => (
        <div className="flex flex-wrap gap-1.5">
          {r.permission_keys.length === 0 && <span className="text-xs text-ink-faint">بدون مجوز</span>}
          {r.permission_keys.map((k) => (
            <Badge key={k} tone="primary">
              {permLabel(k)}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      key: "users",
      header: "متصل‌شده‌ها",
      render: (r) =>
        r.assigned_users.length === 0 ? (
          <span className="text-xs text-ink-faint">هنوز کاربری متصل نشده</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {r.assigned_users.map((u) => (
              <Badge key={u.user_id} tone="info">
                {u.full_name}
              </Badge>
            ))}
          </div>
        ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (r) => (
        <Badge tone={r.is_active ? "success" : "neutral"} dot>
          {r.is_active ? "فعال" : "غیرفعال"}
        </Badge>
      ),
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (r) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="soft" onClick={() => setAssignTarget(r)}>
            اتصال کاربر
          </Button>
          <Button size="sm" variant="ghost" onClick={() => openDeputy(r)}>
            ویرایش
          </Button>
          {r.is_active && (
            <Button size="sm" variant="ghost" onClick={() => deactivateDeputy(r)}>
              غیرفعال
            </Button>
          )}
        </div>
      ),
    },
  ];

  const policyCols: Column<PolicyRule>[] = [
    { key: "own", header: "مالکیت مدرسه", render: (r) => <span className="text-xs font-semibold text-ink">{OWNERSHIP_FA[r.school_ownership] ?? r.school_ownership}</span> },
    { key: "type", header: "نوع استخدام", render: (r) => <span className="text-xs">{EMPLOYMENT_TYPE_FA[r.employment_type] ?? r.employment_type}</span> },
    {
      key: "appr",
      header: "تأیید ناحیه",
      align: "center",
      render: (r) => (
        <Badge tone={r.requires_district_approval ? "warning" : "success"} dot>
          {r.requires_district_approval ? "لازم است" : "خودکار (بدون تأیید)"}
        </Badge>
      ),
    },
    { key: "note", header: "توضیح", render: (r) => <span className="text-xs text-ink-muted">{r.note ?? "—"}</span> },
    {
      key: "act",
      header: "",
      align: "end",
      render: (r) =>
        canPolicy ? (
          <Button size="sm" variant="ghost" onClick={() => openPolicyFor(r)}>
            ویرایش
          </Button>
        ) : null,
    },
  ];

  const logCols: Column<AuditRow>[] = [
    {
      key: "time",
      header: "زمان",
      width: "150px",
      render: (r) => <span className="num text-[11px] text-ink-faint">{r.created_at ? new Date(r.created_at).toLocaleString("fa-IR") : "—"}</span>,
    },
    { key: "actor", header: "عامل", render: (r) => <span className="text-xs font-semibold text-ink">{r.actor_name ?? "سیستم"}</span> },
    {
      key: "action",
      header: "رویداد",
      render: (r) => (
        <span className="num text-[11px] text-primary-700" dir="ltr">
          {r.action}
        </span>
      ),
    },
    {
      key: "entity",
      header: "شیء",
      align: "center",
      render: (r) => (
        <span className="num text-[11px]">
          {r.entity_type ?? "—"}
          {r.entity_id ? ` #${r.entity_id}` : ""}
        </span>
      ),
    },
    { key: "detail", header: "جزئیات", render: (r) => <span className="text-[11px] leading-5 text-ink-muted">{r.detail ?? "—"}</span> },
  ];

  const perms = catalog?.permissions ?? [];
  const scopes = mine?.scopes ?? [];
  // برچسب فارسی مجوز: اول title_fa کاتالوگ سرور، بعد برچسب‌های محلی labels.ts
  const permLabel = useCallback(
    (key: string) => catalog?.permissions.find((p) => p.key === key)?.title_fa ?? PERMISSION_FA[key] ?? key,
    [catalog]
  );

  return (
    <div className="space-y-8">
      {problems.length > 0 && (
        <Alert variant="warning" title="برخی بخش‌ها بر اساس حوزهٔ دسترسی شما نمایش داده نشدند">
          {problems.join("، ")}
        </Alert>
      )}

      {/* ——— مجوزهای من ——— */}
      <Section title="مجوزهای مؤثر من" subtitle="حوزه‌های دید شما و مجوزهایی که مستقیم یا از طریق نقش دارید.">
        {loading && !mine ? (
          <SkeletonTable rows={2} cols={3} />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              {(mine?.permissions ?? []).map((p) => (
                <Badge key={p} tone="primary">
                  {permLabel(p)}
                </Badge>
              ))}
              {(mine?.permissions ?? []).length === 0 && <span className="text-xs text-ink-faint">مجوز فعالی ثبت نشده است.</span>}
            </div>
            <div className="flex flex-wrap gap-2">
              {scopes.map(([t, id]) => (
                <Badge key={`${t}-${id}`} tone="accent">
                  {SCOPE_FA[t] ?? t} {fa(id)}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* ——— واگذاری مجوز ——— */}
      <Section
        title="دسترسی‌های واگذارشده"
        subtitle="قاعدهٔ طلایی در سرور اعمال می‌شود: «هیچ‌کس بیشتر از دسترسی خودش تفویض نمی‌کند» — هر رد با لاگ ممیزی ثبت می‌شود."
        action={
          <Button size="sm" icon={<IconPlus size={15} />} onClick={() => setGrantOpen(true)}>
            واگذاری مجوز
          </Button>
        }
      >
        <Alert variant="info">{catalog?.note_fa ?? "فهرست مجوزها و نقش‌ها از سرور خوانده می‌شود."}</Alert>
        <DataTable columns={assignmentCols} rows={assignments} keyOf={(r) => r.id} loading={loading} />
      </Section>

      {/* ——— معاونان ——— */}
      <Section
        title="نقش‌های معاون مدرسه"
        subtitle="هر معاون چک‌لیست مجوزِ خودش را دارد؛ اتصال کاربر همه کلیدها را با حوزهٔ همین مدرسه واگذار می‌کند (RBAC §6)."
        action={
          <Button size="sm" variant="soft" icon={<IconPlus size={15} />} onClick={() => openDeputy(null)}>
            افزودن نقش معاون
          </Button>
        }
      >
        <DataTable
          columns={deputyCols}
          rows={deputies}
          keyOf={(r) => r.id}
          loading={loading}
          empty={
            <EmptyState
              compact
              icon={<IconUsers size={24} />}
              title="نقش معاونی تعریف نشده"
              description="مثلاً «معاون آموزشی» یا «معاون اجرایی» بسازید و بعد کاربر را به آن متصل کنید."
            />
          }
        />
      </Section>

      {/* ——— سیاست استخدام ——— */}
      <Section
        title="جدول سیاست استخدام"
        subtitle="سیاست، جدول است نه منطق سخت‌کدشده: (مالکیت × نوع استخدام) → آیا تأیید ناحیه لازم است؟"
        action={
          canPolicy ? (
            <Button size="sm" variant="ghost" icon={<IconPlus size={15} />} onClick={() => openPolicyFor(null)}>
              افزودن/ویرایش قانون
            </Button>
          ) : undefined
        }
      >
        {!canPolicy && (
          <Alert variant="info">
            ویرایش سیاست فقط در سطح ناحیه، استان یا کشور مجاز است — شما فقط می‌خوانید.
          </Alert>
        )}
        <DataTable columns={policyCols} rows={policy} keyOf={(r) => r.id} loading={loading} />
      </Section>

      {/* ——— لاگ ممیزی ——— */}
      <Section
        title="لاگ ممیزی"
        subtitle="فقط‌خواندنی و فقط در حوزهٔ دید شما — هر واگذاری، لغو، انتقال و بازدید حساس اینجا ثبت می‌شود."
        action={
          <Button size="sm" variant="ghost" icon={<IconRefresh size={15} />} onClick={() => load()}>
            تازه‌سازی
          </Button>
        }
      >
        <DataTable
          columns={logCols}
          rows={logs}
          keyOf={(r) => r.id}
          loading={loading}
          empty={<EmptyState compact icon={<IconShield size={24} />} title="رویدادی ثبت نشده" description="با انجام عملیات مجوز، رویدادها اینجا ظاهر می‌شوند." />}
        />
      </Section>

      {/* ——— مودال واگذاری مجوز ——— */}
      <Modal
        open={grantOpen}
        onClose={() => setGrantOpen(false)}
        title="واگذاری مجوز"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setGrantOpen(false)}>
              انصراف
            </Button>
            <Button onClick={submitGrant} loading={busy} icon={<IconLock size={15} />}>
              واگذاری
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="گیرنده" required hint="فهرست معلمان/کادر در دید شما">
              <Select value={grant.grantee_user_id || ""} onChange={(e) => setGrant({ ...grant, grantee_user_id: Number(e.target.value) })}>
                <option value="">— انتخاب کنید —</option>
                {candidates.map((c) => (
                  <option key={c.user_id} value={c.user_id}>
                    {c.full_name} {c.username ? `(${c.username})` : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="نقش" required hint="برچسب مجوزهای پیش‌فرض نقش را ببینید">
              <Select value={grant.role_id || ""} onChange={(e) => setGrant({ ...grant, role_id: Number(e.target.value) })}>
                <option value="">— انتخاب کنید —</option>
                {(catalog?.roles ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title_fa} ({r.permissions.length} مجوز)
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="مجوز" required>
              <Select value={grant.permission_id || ""} onChange={(e) => setGrant({ ...grant, permission_id: Number(e.target.value) })}>
                <option value="">— انتخاب کنید —</option>
                {perms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title_fa}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="حوزه" required hint="حوزهٔ مجوز هرگز بزرگ‌تر از حوزهٔ خودتان نمی‌شود">
              <Select
                value={grant.scope_type}
                onChange={(e) => setGrant({ ...grant, scope_type: e.target.value, scope_id: e.target.value === "school" ? schoolId : grant.scope_id })}
              >
                {(catalog?.scope_types ?? ["school"]).map((s) => (
                  <option key={s} value={s}>
                    {SCOPE_FA[s] ?? s}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="شناسه حوزه" required hint={grant.scope_type === "school" ? "پیش‌فرض: مدرسه جاری" : "شناسه استان/ناحیه/کلاس/دانش‌آموز"}>
              <Input type="number" value={grant.scope_id || ""} onChange={(e) => setGrant({ ...grant, scope_id: Number(e.target.value) })} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="از تاریخ" hint="اختیاری">
                <Input type="date" value={grant.valid_from} onChange={(e) => setGrant({ ...grant, valid_from: e.target.value })} />
              </Field>
              <Field label="تا تاریخ" hint="خالی = نامحدود">
                <Input type="date" value={grant.valid_until} onChange={(e) => setGrant({ ...grant, valid_until: e.target.value })} />
              </Field>
            </div>
          </div>
          <Alert variant="info">
            دسترسی موقت با تاریخ پایان، خودکار منقضی می‌شود؛ هر واگذاری و هر رد در لاگ ممیزی ثبت می‌گردد.
          </Alert>
        </div>
      </Modal>

      {/* ——— تأیید لغو ——— */}
      <Modal
        open={revokeId !== null}
        onClose={() => setRevokeId(null)}
        title="لغو مجوز"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevokeId(null)}>
              انصراف
            </Button>
            <Button variant="danger" loading={busy} onClick={submitRevoke}>
              لغو مجوز
            </Button>
          </>
        }
      >
        مجوز انتخاب‌شده لغو می‌شود؟ تاریخچهٔ ممیزی حفظ می‌ماند و اگر کاربر از همان مجوز استفاده کرده باشد در لاگ باقی می‌ماند.
      </Modal>

      {/* ——— مودال معاون ——— */}
      <Modal
        open={deputyModal !== null}
        onClose={() => setDeputyModal(null)}
        title={deputyModal === "create" ? "افزودن نقش معاون" : "ویرایش چک‌لیست معاون"}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeputyModal(null)}>
              انصراف
            </Button>
            <Button onClick={saveDeputy} loading={busy}>
              ذخیره
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="عنوان معاون" required hint="مثلاً معاون آموزشی، معاون اجرایی">
            <Input value={deputyForm.title_fa} onChange={(e) => setDeputyForm({ ...deputyForm, title_fa: e.target.value })} placeholder="معاون آموزشی" />
          </Field>
          <div className="rounded-xl border border-line bg-surface-sunken p-3.5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-bold text-ink">چک‌لیست مجوزها</p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setDeputyForm((f) => ({ ...f, permission_keys: perms.map((p) => p.key) }))}
                >
                  همه
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setDeputyForm((f) => ({ ...f, permission_keys: [] }))}>
                  هیچ
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {perms.map((p) => (
                <label key={p.key} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-muted transition hover:bg-white/70">
                  <input
                    type="checkbox"
                    checked={deputyForm.permission_keys.includes(p.key)}
                    onChange={() => toggleKey(p.key)}
                    className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                  />
                  {p.title_fa}
                </label>
              ))}
              {perms.length === 0 && <span className="text-xs text-ink-faint">فهرست مجوزها بارگذاری نشد.</span>}
            </div>
          </div>
        </div>
      </Modal>

      {/* ——— اتصال کاربر به معاون ——— */}
      <Modal
        open={assignTarget !== null}
        onClose={() => setAssignTarget(null)}
        title={`اتصال کاربر به «${assignTarget?.title_fa ?? ""}»`}
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAssignTarget(null)}>
              انصراف
            </Button>
            <Button onClick={assignUser} loading={busy} disabled={!assignUserId}>
              اتصال و واگذاری
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="کاربر" required hint="همه کلیدهای چک‌لیست با حوزهٔ همین مدرسه واگذار می‌شوند">
            <Select value={assignUserId || ""} onChange={(e) => setAssignUserId(Number(e.target.value))}>
              <option value="">— انتخاب کنید —</option>
              {candidates.map((c) => (
                <option key={c.user_id} value={c.user_id}>
                  {c.full_name} {c.username ? `(${c.username})` : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Alert variant="warning">
            اگر خودِ شما آن مجوز را در این حوزه نداشته باشید، سرور با پیام فارسی رد می‌کند (قاعدهٔ طلایی).
          </Alert>
        </div>
      </Modal>

      {/* ——— مودال سیاست ——— */}
      <Modal
        open={policyOpen}
        onClose={() => setPolicyOpen(false)}
        title="قانون سیاست استخدام"
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPolicyOpen(false)}>
              انصراف
            </Button>
            <Button onClick={savePolicy} loading={busy}>
              ذخیره قانون
            </Button>
          </>
        }
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="مالکیت مدرسه" required>
            <Select value={policyForm.school_ownership} onChange={(e) => setPolicyForm({ ...policyForm, school_ownership: e.target.value })}>
              {POLICY_OWNERSHIPS.map((o) => (
                <option key={o} value={o}>
                  {OWNERSHIP_FA[o] ?? o}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="نوع استخدام" required>
            <Select value={policyForm.employment_type} onChange={(e) => setPolicyForm({ ...policyForm, employment_type: e.target.value })}>
              {POLICY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {EMPLOYMENT_TYPE_FA[t] ?? t}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="تأیید ناحیه" required hint="روشن = تأیید ناحیه لازم؛ خاموش = تأیید خودکار">
            <Select
              value={policyForm.requires_district_approval ? "1" : "0"}
              onChange={(e) => setPolicyForm({ ...policyForm, requires_district_approval: e.target.value === "1" })}
            >
              <option value="1">لازم است</option>
              <option value="0">خودکار (بدون تأیید)</option>
            </Select>
          </Field>
          <Field label="توضیح" hint="اختیاری — حداکثر ۲۰۰ نویسه">
            <Input value={policyForm.note} onChange={(e) => setPolicyForm({ ...policyForm, note: e.target.value })} placeholder="مثلاً طبق مصوبه هیئت‌امور…" />
          </Field>
        </div>
        {!canPolicy && (
          <div className="mt-4">
            <Alert variant="danger" title="دسترسی ناکافی">
              <span className="flex items-center gap-1.5">
                <IconAlert size={14} /> ویرایش سیاست فقط در سطح ناحیه/استان/کشور مجاز است.
              </span>
            </Alert>
          </div>
        )}
      </Modal>
    </div>
  );
}
