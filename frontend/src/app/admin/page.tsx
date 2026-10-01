"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { CAUSE_SHORT, fa } from "@/lib/labels";

type Overview = {
  school: { id: number; name: string; type: string; ownership: string };
  students_count: number;
  avg_effective_mastery: number | null;
  needs_intervention: number;
  status_counts: Record<string, number>;
};

type CompareRow = {
  class_id: number;
  class_name: string;
  grade: string;
  teacher: { id: number; full_name: string } | null;
  avg_mastery: number | null;
  avg_retention: number | null;
  students_with_data: number;
  total_errors: number;
  gap_vs_school_avg: number | null;
  drop_flag: boolean;
  weak_topics: { topic_id: number; title: string; weak_students: number }[];
};

type CompareData = {
  subject: string;
  comparison_valid: boolean;
  min_group_note: string;
  rows: CompareRow[];
};

type Flag = {
  class_id: number;
  class_name: string;
  subject: string;
  teacher_name: string | null;
  flag_type: string;
  title_fa: string;
  evidence_fa: string;
  action_fa: string;
};

type TeacherProfile = {
  teacher_id: number;
  teacher_name: string | null;
  subject: string;
  class_id: number;
  class_name: string;
  students_count: number;
  class_mastery: number | null;
  class_retention: number | null;
  total_errors: number;
  platform: { exam_sessions_recorded: number; answers_recorded: number };
  note_fa: string;
};

type Diagnosis = {
  class_id: number;
  class_mastery: number | null;
  error_causes: Record<string, number>;
  total_errors: number;
  weak_topics: { topic_id: number; title: string; weak_students: number }[];
  grounded_actions_fa: string[];
  note_fa: string;
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

const REQ_STATUS_FA: Record<string, string> = {
  pending: "در انتظار تأیید ناحیه",
  approved: "تأییدشده",
  rejected: "ردشده",
  auto_approved: "تأیید خودکار (سیاست)",
};

const FLAG_ICON: Record<string, string> = {
  low_mastery_majority: "🔴",
  high_repeats: "🟠",
  ineffective_intervention: "🟣",
  low_platform_usage: "⚪",
};

type Tab = "compare" | "flags" | "teachers";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("compare");
  const [ov, setOv] = useState<Overview | null>(null);
  const [cmp, setCmp] = useState<CompareData | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [profiles, setProfiles] = useState<TeacherProfile[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [requests, setRequests] = useState<Request[]>([]);
  const [msg, setMsg] = useState("");
  const [role, setRole] = useState("");
  const [form, setForm] = useState({ employee_user_id: 7, full_name: "", employment_type: "contractual", subject: "math" });

  const loadAll = useCallback(async () => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);
      setOv(await api<Overview>("/admin/school/1/overview"));
      setCmp(await api<CompareData>("/admin/school/1/classes-compare/math"));
      setFlags((await api<{ flags: Flag[] }>("/admin/school/1/attention-flags")).flags);
      setProfiles((await api<{ profiles: TeacherProfile[] }>("/admin/school/1/teachers")).profiles);
      setRequests((await api<{ requests: Request[] }>("/admin/employment-requests")).requests);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function openDiagnosis(classId: number) {
    setDiagnosis(null);
    try {
      setDiagnosis(await api<Diagnosis>(`/admin/classes/${classId}/diagnosis`));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  async function addTeacher(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      const res = await api<{ status: string }>("/admin/employment-requests", { method: "POST", json: form });
      setMsg(
        res.status === "auto_approved"
          ? "✓ طبق سیاست استخدام، تأیید ناحیه لازم نبود — معلم فعال شد."
          : "درخواست ثبت شد و برای تأیید به ناحیه ارسال شد."
      );
      await loadAll();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  async function decide(id: number, approve: boolean) {
    setMsg("");
    try {
      await api(`/admin/employment-requests/${id}/decide`, { method: "POST", json: { approve } });
      await loadAll();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  if (msg && !ov) return <main className="p-6 text-red-600">{msg}</main>;
  if (!ov) return <main className="p-6 text-slate-400">در حال بارگذاری…</main>;

  return (
    <main className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
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

      {/* داشبورد کلان (§2) */}
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="card text-center">
          <p className="text-xs text-slate-500">دانش‌آموزان</p>
          <p className="text-2xl font-bold mt-1">{fa(ov.students_count)}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500">میانگین تسلط مؤثر</p>
          <p className="text-2xl font-bold mt-1 text-emerald-600">
            {ov.avg_effective_mastery !== null ? `${fa(ov.avg_effective_mastery, 1)}٪` : "—"}
          </p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500">نیازمند مداخله</p>
          <p className="text-2xl font-bold mt-1 text-red-600">{fa(ov.needs_intervention)}</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-slate-500">مباحث بحرانی/ضعیف</p>
          <p className="text-2xl font-bold mt-1">{fa((ov.status_counts.critical ?? 0) + (ov.status_counts.weak ?? 0))}</p>
        </div>
      </section>

      {msg && <div className="card border-primary-200 bg-primary-50 text-sm text-primary-700">{msg}</div>}

      {/* تب‌های تحلیلی */}
      <nav className="flex gap-2">
        {(
          [
            ["compare", "مقایسه کلاس‌ها"],
            ["flags", `نیازمند بررسی (${flags.length})`],
            ["teachers", "نمایه معلمان"],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button
            key={k}
            className={`btn text-sm ${tab === k ? "bg-primary-600 text-white" : "border border-slate-300 hover:bg-slate-50"}`}
            onClick={() => setTab(k)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* §7 مقایسه کلاس‌ها */}
      {tab === "compare" && cmp && (
        <section className="space-y-3">
          {!cmp.comparison_valid && (
            <div className="card border-amber-200 bg-amber-50 text-xs text-amber-800">{cmp.min_group_note}</div>
          )}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b border-slate-100">
                  <th className="text-right py-2">کلاس</th>
                  <th className="py-2">معلم</th>
                  <th className="py-2">تسلط</th>
                  <th className="py-2">ماندگاری</th>
                  <th className="py-2">اختلاف با میانگین</th>
                  <th className="py-2">خطاها</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {cmp.rows.map((row) => (
                  <tr key={row.class_id} className="border-b border-slate-50">
                    <td className="py-2 text-right font-medium">
                      {row.class_name}
                      {row.drop_flag && <span className="badge bg-red-100 text-red-700 mr-2">کلاس دارای افت</span>}
                    </td>
                    <td className="py-2 text-center">{row.teacher?.full_name ?? "—"}</td>
                    <td className="py-2 text-center font-semibold">{row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}</td>
                    <td className="py-2 text-center">{row.avg_retention !== null ? `${fa(row.avg_retention * 100)}٪` : "—"}</td>
                    <td className={`py-2 text-center ${row.drop_flag ? "text-red-600 font-semibold" : ""}`}>
                      {row.gap_vs_school_avg !== null ? `${row.gap_vs_school_avg > 0 ? "+" : ""}${fa(row.gap_vs_school_avg)} واحد` : "—"}
                    </td>
                    <td className="py-2 text-center">{fa(row.total_errors)}</td>
                    <td className="py-2 text-center">
                      <button className="btn-ghost text-xs" onClick={() => openDiagnosis(row.class_id)}>
                        تشخیص ضعف
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400">
            پرچم «کلاس دارای افت» یعنی اختلاف ≥ ۱۰ واحد با میانگین هم‌درس‌ها — فقط پرچم است، نه حکم درباره معلم.
          </p>
        </section>
      )}

      {/* §5 سامانه نیازمند بررسی */}
      {tab === "flags" && (
        <section className="space-y-3">
          <div className="card border-slate-200 bg-slate-50 text-xs text-slate-600">
            این موارد هشدار هستند، نه ارزیابی قطعی از معلم. (سند مدیر مدرسه §5)
          </div>
          {flags.length === 0 && <div className="card text-sm text-slate-400">هیچ مورد نیازمند بررسی فعلاً وجود ندارد.</div>}
          {flags.map((f, i) => (
            <div key={i} className="card space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {FLAG_ICON[f.flag_type]} {f.title_fa}
                </span>
                <span className="text-xs text-slate-400">
                  کلاس {f.class_name} · {f.subject} · {f.teacher_name ?? "—"}
                </span>
              </div>
              <p className="text-sm text-slate-600">{f.evidence_fa}</p>
              <p className="text-xs text-primary-700">اقدام: {f.action_fa}</p>
              <button className="btn-ghost text-xs mt-1" onClick={() => openDiagnosis(f.class_id)}>
                تشخیص چندعاملی این کلاس
              </button>
            </div>
          ))}
        </section>
      )}

      {/* §4 نمایه سبک معلمان */}
      {tab === "teachers" && (
        <section className="space-y-3">
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b border-slate-100">
                  <th className="text-right py-2">معلم</th>
                  <th className="py-2">درس / کلاس</th>
                  <th className="py-2">دانش‌آموز</th>
                  <th className="py-2">تسلط کلاس</th>
                  <th className="py-2">ماندگاری</th>
                  <th className="py-2">آزمون ثبت‌شده</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p, i) => (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="py-2 text-right font-medium">{p.teacher_name}</td>
                    <td className="py-2 text-center">{p.subject} · کلاس {p.class_name}</td>
                    <td className="py-2 text-center">{fa(p.students_count)}</td>
                    <td className="py-2 text-center font-semibold">{p.class_mastery !== null ? `${fa(p.class_mastery)}٪` : "—"}</td>
                    <td className="py-2 text-center">{p.class_retention !== null ? `${fa(p.class_retention * 100)}٪` : "—"}</td>
                    <td className="py-2 text-center">{fa(p.platform.exam_sessions_recorded)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400">
            شاخص عینی کلاس هر معلم است؛ بدون امتیاز عددی کلی. قضاوت نیاز به بررسی زمینه‌ای دارد (§4 و §8).
          </p>
        </section>
      )}

      {/* §6 تشخیص چندعاملی */}
      {diagnosis && (
        <section className="card space-y-3 border-primary-200">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">تشخیص چندعاملی — کلاس {diagnosis.class_id}</h2>
            <button className="btn-ghost text-xs" onClick={() => setDiagnosis(null)}>بستن</button>
          </div>
          <p className="text-sm">
            تسلط کلاس: <b>{diagnosis.class_mastery !== null ? `${fa(diagnosis.class_mastery)}٪` : "—"}</b> · تعداد خطا: {fa(diagnosis.total_errors)}
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(diagnosis.error_causes).map(([c, n]) => (
              <span key={c} className="badge bg-slate-100 text-slate-600">
                {CAUSE_SHORT[c] ?? c}: {fa(n)}
              </span>
            ))}
          </div>
          <ul className="text-sm space-y-1 list-disc pr-5">
            {diagnosis.grounded_actions_fa.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
          <p className="text-xs text-slate-400">{diagnosis.note_fa}</p>
        </section>
      )}

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
            placeholder="شناسه کاربر معلم جدید"
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
                {r.employment_type} · {r.subject ?? "—"} · {REQ_STATUS_FA[r.status] ?? r.status}
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
