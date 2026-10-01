"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { EMPLOYMENT_TYPE_FA, REQUEST_STATUS_FA, SUBJECT_FA, fa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, SearchInput, Select } from "@/components/ui/forms";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconInbox, IconPlus, IconRefresh, IconUsers, IconX } from "@/components/ui/icons";

type Assignment = { school_id: number; school_name?: string; role?: string; subject?: string | null };

/** ردیف فهرست معلمان — GET /admin/teachers-directory */
type DirectoryTeacher = {
  user_id: number;
  full_name: string;
  username?: string;
  subjects?: string[];
  active_assignments?: Assignment[];
  available?: boolean;
};

/** ردیف کارتابل استخدام — GET /admin/employment-requests */
type RequestRow = {
  id: number;
  school_id: number;
  full_name: string;
  employment_type: string;
  organization: string;
  subject: string | null;
  status: string;
  school_name?: string | null;
  created_at?: string;
};

/** پاسخ POST /admin/employment-requests — دفاعی (شکل دقیق هنوز قطعی نیست). */
type PostResult = {
  status?: string;
  ok?: boolean;
  reason?: string;
  detail?: string;
  message_fa?: string;
  policy?: unknown;
  policy_fa?: string;
  note_fa?: string;
};

/** نوع استخدام‌های سرویس استخدام مدرسه (مقادیر بزرگ‌نویس). */
const EMPLOYMENT_TYPES = ["FORMAL", "COOPERATIVE", "PART_TIME"] as const;

/** نرمال‌سازی پاسخ فهرست معلمان: آرایهٔ خام یا { total, teachers: [...] }. */
function normalizeTeachers(res: unknown): DirectoryTeacher[] {
  if (Array.isArray(res)) return res as DirectoryTeacher[];
  if (res && typeof res === "object") {
    const teachers = (res as { teachers?: unknown }).teachers;
    if (Array.isArray(teachers)) return teachers as DirectoryTeacher[];
  }
  return [];
}

/** نرمال‌سازی پاسخ کارتابل: آرایهٔ خام یا { requests: [...] }. */
function normalizeRequests(res: unknown): RequestRow[] {
  if (Array.isArray(res)) return res as RequestRow[];
  if (res && typeof res === "object") {
    const requests = (res as { requests?: unknown }).requests;
    if (Array.isArray(requests)) return requests as RequestRow[];
  }
  return [];
}

/** متن سیاست استخدام در صورت ارسال توسط سرور (تحلیل دفاعی). */
function policyText(res: PostResult | null): string | null {
  if (!res) return null;
  const direct = [res.policy_fa, res.note_fa].filter((x): x is string => typeof x === "string" && x.trim().length > 0);
  let fromPolicy: string[] = [];
  if (typeof res.policy === "string") fromPolicy = [res.policy];
  else if (res.policy && typeof res.policy === "object") {
    const p = res.policy as Record<string, unknown>;
    fromPolicy = [p.note_fa, p.text_fa, p.detail_fa, p.description_fa, p.rule_fa, p.message_fa].filter(
      (x): x is string => typeof x === "string" && x.trim().length > 0
    );
  }
  return direct[0] ?? fromPolicy[0] ?? null;
}

export function EmploymentSection({ canDecide = false, onChanged }: { canDecide?: boolean; onChanged?: () => void }) {
  const [teachers, setTeachers] = useState<DirectoryTeacher[]>([]);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [directoryError, setDirectoryError] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [employmentType, setEmploymentType] = useState<string>(EMPLOYMENT_TYPES[0]);
  const [subject, setSubject] = useState<string>("math");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [policy, setPolicy] = useState<string | null>(null);

  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadDirectory = useCallback(async () => {
    setDirectoryLoading(true);
    setDirectoryError("");
    try {
      setTeachers(normalizeTeachers(await api<unknown>("/admin/teachers-directory")));
    } catch (e) {
      setTeachers([]);
      setDirectoryError(e instanceof Error ? e.message : "خطا در دریافت فهرست معلمان");
    } finally {
      setDirectoryLoading(false);
    }
  }, []);

  const loadRequests = useCallback(async () => {
    setRequestsLoading(true);
    try {
      setRequests(normalizeRequests(await api<unknown>("/admin/employment-requests")));
    } catch {
      setRequests([]);
    } finally {
      setRequestsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDirectory();
    loadRequests();
  }, [loadDirectory, loadRequests]);

  const selected = teachers.find((t) => t.user_id === selectedId) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return teachers;
    return teachers.filter((t) =>
      [t.full_name, t.username ?? "", ...(t.subjects ?? [])].some((s) => String(s).toLowerCase().includes(q))
    );
  }, [teachers, query]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    if (!selected) {
      setFormError("برای ثبت درخواست، ابتدا یک معلم را از فهرست انتخاب کنید.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await api<PostResult>("/admin/employment-requests", {
        method: "POST",
        json: { teacher_user_id: selected.user_id, employment_type: employmentType, subject },
      });
      if (res && res.ok === false) {
        toast(res.reason ?? res.detail ?? "این درخواست قابل ثبت نیست", "error");
      } else if (res?.status === "auto_approved") {
        toast("درخواست به‌صورت خودکار تأیید و فعال شد", "success");
      } else {
        toast("درخواست ثبت شد و برای تأیید به ناحیه ارسال شد", "success");
      }
      setPolicy(policyText(res));
      setSelectedId(null);
      await loadRequests();
      onChanged?.();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          toast(err.detail ?? "این معلم هم‌اکنون در این مدرسه شاغل است", "error");
        } else if (err.status === 400 || err.status === 404) {
          toast("معلم انتخاب‌شده معتبر نیست", "error");
        } else if (err.status === 403) {
          toast(err.detail ?? "ثبت این درخواست در حوزه دسترسی شما نیست", "error");
        } else {
          toast(err.message || "خطا در ثبت درخواست", "error");
        }
      } else {
        toast(err instanceof Error ? err.message : "خطا در ثبت درخواست", "error");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function decide(row: RequestRow, approve: boolean) {
    setBusyId(row.id);
    try {
      const res = await api<{ ok?: boolean; reason?: string }>(`/admin/employment-requests/${row.id}/decide`, {
        method: "POST",
        json: { approve },
      });
      if (res && res.ok === false) {
        toast(res.reason ?? "این درخواست قابل تصمیم‌گیری نیست", "warning");
      } else {
        toast(approve ? "درخواست تأیید شد." : "درخواست رد شد.", approve ? "success" : "info");
        onChanged?.();
      }
      await loadRequests();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در تصمیم‌گیری", "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      {/* ——— ویزارد استخدام معلم ——— */}
      <Card>
        <CardHeader
          title="درخواست استخدام معلم"
          subtitle="معلم را از فهرست انتخاب کنید؛ نوع استخدام و درس را تعیین کنید تا سیاست استخدام بررسی شود."
          icon={<IconPlus size={17} />}
          action={
            <Button variant="ghost" size="sm" icon={<IconRefresh size={14} />} onClick={loadDirectory} loading={directoryLoading}>
              تازه‌سازی
            </Button>
          }
        />

        {policy && (
          <div className="mb-4">
            <Alert variant="info" title="سیاست استخدام">
              طبق سیاست استخدام مدرسه: {policy}
            </Alert>
          </div>
        )}

        {directoryError && (
          <div className="mb-4">
            <Alert variant="danger" title="فهرست معلمان بارگذاری نشد">
              {directoryError}
            </Alert>
          </div>
        )}

        {/* انتخاب معلم */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs font-bold text-ink">انتخاب معلم</span>
            <SearchInput value={query} onChange={setQuery} placeholder="جستجو بر اساس نام، نام کاربری یا درس…" className="w-full sm:w-72" />
          </div>

          {directoryLoading ? (
            <SkeletonTable rows={3} cols={3} />
          ) : teachers.length === 0 ? (
            <EmptyState
              icon={<IconUsers size={26} />}
              title="هنوز معلمی در فهرست نیست"
              description="برای ثبت درخواست استخدام، ابتدا باید اکانت معلمی در سامانه ساخته شود. پس از فعال‌شدن، نام او در این فهرست ظاهر می‌شود."
            />
          ) : filtered.length === 0 ? (
            <EmptyState compact title="معلمی با این جستجو پیدا نشد" description="عبارت دیگری امتحان کنید یا جستجو را خالی بگذارید." />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {filtered.map((t) => {
                const available = t.available !== false;
                const isSelected = t.user_id === selectedId;
                return (
                  <button
                    key={t.user_id}
                    type="button"
                    disabled={!available}
                    aria-pressed={isSelected}
                    onClick={() => setSelectedId(isSelected ? null : t.user_id)}
                    className={[
                      "rounded-2xl border p-4 text-right transition",
                      !available
                        ? "cursor-not-allowed border-line bg-surface-sunken opacity-60"
                        : isSelected
                          ? "border-primary-400 bg-primary-50/70 ring-2 ring-primary-200"
                          : "border-line bg-surface hover:border-primary-300 hover:shadow-soft",
                    ].join(" ")}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-ink">{t.full_name}</p>
                        {t.username && <p className="num truncate text-[11px] text-ink-faint">@{t.username}</p>}
                      </div>
                      <Badge tone={available ? "success" : "warning"} dot>
                        {available ? "در دسترس" : "شاغل"}
                      </Badge>
                    </div>
                    {(t.subjects ?? []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {(t.subjects ?? []).map((s) => (
                          <Badge key={s} tone="neutral">
                            {subjectFa(s)}
                          </Badge>
                        ))}
                      </div>
                    )}
                    <p className="mt-2 text-[11px] leading-5 text-ink-muted">
                      {(t.active_assignments ?? []).length > 0
                        ? `مدرسه(ها): ${(t.active_assignments ?? []).map((a) => a.school_name ?? `مدرسه #${a.school_id}`).join("، ")}`
                        : "بدون تخصیص فعال"}
                    </p>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* مشخصات درخواست */}
        <form onSubmit={submit} className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="معلم انتخاب‌شده" required hint={selected ? `شناسه: ${fa(selected.user_id)}` : "از فهرست بالا انتخاب کنید"}>
            <Select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">— انتخاب معلم —</option>
              {filtered.map((t) => (
                <option key={t.user_id} value={t.user_id} disabled={t.available === false}>
                  {t.full_name}
                  {t.available === false ? " (شاغل)" : ""}
                </option>
              ))}
              {selected && !filtered.some((t) => t.user_id === selected.user_id) && (
                <option value={selected.user_id}>{selected.full_name}</option>
              )}
            </Select>
          </Field>
          <Field label="نوع استخدام" required>
            <Select value={employmentType} onChange={(e) => setEmploymentType(e.target.value)}>
              {EMPLOYMENT_TYPES.map((v) => (
                <option key={v} value={v}>
                  {EMPLOYMENT_TYPE_FA[v] ?? v}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="درس" required>
            <Select value={subject} onChange={(e) => setSubject(e.target.value)}>
              {Object.keys(SUBJECT_FA).map((k) => (
                <option key={k} value={k}>
                  {SUBJECT_FA[k]}
                </option>
              ))}
            </Select>
          </Field>
          {formError && (
            <div className="sm:col-span-3">
              <Alert variant="warning">{formError}</Alert>
            </div>
          )}
          <div className="sm:col-span-3">
            <Button type="submit" loading={submitting} icon={<IconPlus size={15} />}>
              ثبت درخواست استخدام
            </Button>
          </div>
        </form>
      </Card>

      {/* ——— کارتابل درخواست‌ها ——— */}
      <Section
        title="کارتابل درخواست‌های استخدام"
        subtitle="درخواست‌های در انتظار، برای تأیید ناحیه ارسال می‌شوند."
        action={
          <Button variant="ghost" size="sm" icon={<IconRefresh size={14} />} onClick={loadRequests} loading={requestsLoading}>
            تازه‌سازی
          </Button>
        }
      >
        {requestsLoading ? (
          <SkeletonTable rows={3} cols={4} />
        ) : requests.length === 0 ? (
          <EmptyState icon={<IconInbox size={26} />} title="درخواستی ثبت نشده" description="درخواست‌های جدید استخدام اینجا نمایش داده می‌شود." />
        ) : (
          <div className="space-y-3">
            {requests.map((r) => (
              <Card key={r.id} className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                    <IconUsers size={17} />
                  </span>
                  <div>
                    <p className="text-sm font-bold text-ink">{r.full_name}</p>
                    <p className="num mt-0.5 text-[11px] text-ink-muted">
                      {EMPLOYMENT_TYPE_FA[r.employment_type] ?? r.employment_type} · {r.subject ? subjectFa(r.subject) : "—"} ·{" "}
                      {r.school_name ?? r.organization}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={statusTone(r.status)} dot>
                    {REQUEST_STATUS_FA[r.status] ?? r.status}
                  </Badge>
                  {r.status === "pending" &&
                    (canDecide ? (
                      <>
                        <Button size="sm" variant="success" loading={busyId === r.id} onClick={() => decide(r, true)} icon={<IconCheckCircle size={14} />}>
                          تأیید
                        </Button>
                        <Button size="sm" variant="ghost" loading={busyId === r.id} onClick={() => decide(r, false)} icon={<IconX size={14} />}>
                          رد
                        </Button>
                      </>
                    ) : (
                      <span className="text-[11px] text-ink-muted">در انتظار تصمیم ناحیه</span>
                    ))}
                </div>
              </Card>
            ))}
          </div>
        )}
        {!canDecide && requests.some((r) => r.status === "pending") && (
          <p className="text-[11px] leading-6 text-ink-faint">تأیید/رد نهایی با ناحیه است؛ مدیر مدرسه فقط درخواست را ثبت می‌کند.</p>
        )}
      </Section>
    </>
  );
}
