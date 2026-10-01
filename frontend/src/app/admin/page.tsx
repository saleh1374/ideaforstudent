"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";

type Overview = {
  school: { id: number; name: string; type: string; ownership: string };
  students_count: number;
  avg_effective_mastery: number | null;
  needs_intervention: number;
  status_counts: Record<string, number>;
};

type Request = {
  id: number;
  school_id: number;
  full_name: string;
  employment_type: string;
  organization: string;
  subject: string | null;
  status: string;
};

const STATUS_FA: Record<string, string> = {
  pending: "در انتظار تأیید ناحیه",
  approved: "تأییدشده",
  rejected: "ردشده",
  auto_approved: "تأیید خودکار (سیاست)",
};

export default function AdminPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [requests, setRequests] = useState<Request[]>([]);
  const [msg, setMsg] = useState("");
  const [role, setRole] = useState<string>("");
  const [form, setForm] = useState({ employee_user_id: 6, full_name: "", employment_type: "contractual", subject: "math" });

  const load = useCallback(async () => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);
      const schoolId = me.role === "district_admin" ? 1 : 1;
      setOv(await api<Overview>(`/admin/school/${schoolId}/overview`));
      const r = await api<{ requests: Request[] }>("/admin/employment-requests");
      setRequests(r.requests);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function addTeacher(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      const res = await api<{ status: string; request_id: number }>("/admin/employment-requests", {
        method: "POST",
        json: form,
      });
      setMsg(
        res.status === "auto_approved"
          ? "✓ طبق سیاست استخدام، تأیید ناحیه لازم نبود — معلم فعال شد."
          : "درخواست ثبت شد و برای تأیید به ناحیه ارسال شد."
      );
      await load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  async function decide(id: number, approve: boolean) {
    setMsg("");
    try {
      await api(`/admin/employment-requests/${id}/decide`, { method: "POST", json: { approve } });
      await load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  if (msg && !ov) return <main className="p-6 text-red-600">{msg}</main>;
  if (!ov) return <main className="p-6 text-slate-400">در حال بارگذاری…</main>;

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{ov.school.name}</h1>
          <p className="text-xs text-slate-400">
            {role === "district_admin" ? "دید ناحیه" : "دید مدرسه"} — {ov.school.ownership === "public" ? "دولتی" : ov.school.ownership}
          </p>
        </div>
        <button
          className="btn-ghost text-xs"
          onClick={() => {
            localStorage.removeItem("daneshyar_token");
            window.location.href = "/login";
          }}
        >
          خروج
        </button>
      </header>

      {/* داشبورد کلان (سند مدیر مدرسه §2) */}
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="card text-center">
          <p className="text-xs text-slate-500">دانش‌آموزان</p>
          <p className="text-2xl font-bold mt-1">{fa(ov.students_count)}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500">میانگین تسلط مؤثر</p>
          <p className="text-2xl font-bold mt-1 text-emerald-600">{ov.avg_effective_mastery !== null ? `${fa(ov.avg_effective_mastery, 1)}٪` : "—"}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500">نیازمند مداخله</p>
          <p className="text-2xl font-bold mt-1 text-red-600">{fa(ov.needs_intervention)}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500">مسلط</p>
          <p className="text-2xl font-bold mt-1">{fa(ov.status_counts.mastered ?? 0)}</p>
        </div>
      </section>

      {msg && <div className="card border-primary-200 bg-primary-50 text-sm text-primary-700">{msg}</div>}

      {/* افزودن معلم — گردش کار درخواست (RBAC §5) */}
      <section className="card space-y-3">
        <h2 className="font-semibold">افزودن معلم (درخواست + سیاست استخدام)</h2>
        <form onSubmit={addTeacher} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input
            className="input"
            placeholder="نام معلم"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            required
          />
          <input
            className="input"
            placeholder="شناسه کاربر (۶ = newteacher)"
            type="number"
            value={form.employee_user_id}
            onChange={(e) => setForm({ ...form, employee_user_id: Number(e.target.value) })}
            required
          />
          <select className="input" value={form.employment_type} onChange={(e) => setForm({ ...form, employment_type: e.target.value })}>
            <option value="official">رسمی</option>
            <option value="contractual">قراردادی</option>
            <option value="part_time">پاره‌وقت</option>
            <option value="temporary">موقت</option>
          </select>
          <select className="input" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })}>
            <option value="math">ریاضی</option>
            <option value="physics">فیزیک</option>
            <option value="chemistry">شیمی</option>
          </select>
          <button className="btn-primary sm:col-span-2">ثبت درخواست</button>
        </form>
        <p className="text-xs text-slate-400">
          جدول سیاست: معلم رسمی در مدرسه دولتی → تأیید خودکار؛ قراردادی → نیاز به تأیید ناحیه.
        </p>
      </section>

      {/* کارتابل درخواست‌ها */}
      <section className="space-y-3">
        <h2 className="font-semibold">کارتابل درخواست‌های استخدام</h2>
        {requests.length === 0 && <div className="card text-sm text-slate-400">درخواستی ثبت نشده.</div>}
        {requests.map((r) => (
          <div key={r.id} className="card flex items-center justify-between">
            <div>
              <p className="font-medium">{r.full_name}</p>
              <p className="text-xs text-slate-500 mt-1">
                {r.employment_type} · {r.subject ?? "—"} · {STATUS_FA[r.status] ?? r.status}
              </p>
            </div>
            {r.status === "pending" && (
              <div className="flex gap-2">
                <button className="btn-primary text-xs" onClick={() => decide(r.id, true)}>تأیید</button>
                <button className="btn-ghost text-xs" onClick={() => decide(r.id, false)}>رد</button>
              </div>
            )}
          </div>
        ))}
      </section>
    </main>
  );
}
