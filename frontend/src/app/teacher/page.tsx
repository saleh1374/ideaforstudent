"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { NEED_FA, NEED_COLOR, CAUSE_SHORT, STATUS_FA, STATUS_COLOR, fa } from "@/lib/labels";

type ClassInfo = {
  class_id: number;
  name: string;
  grade: string;
  subject: string;
  school_name: string | null;
  students_count: number;
};

type RadarRow = {
  topic_id: number;
  title: string;
  avg_mastery: number;
  avg_retention: number;
  status: string;
  weak_count: number;
  students_with_data: number;
  total_students: number;
  error_causes: Record<string, number>;
  prereq_weak: boolean;
};

type RootCause = {
  topic: { topic_id: number; title: string; mastery: number | null };
  chain: { topic_id: number; title: string; mastery: number | null }[];
  root: { topic_id: number; title: string; mastery: number | null };
  root_reason: string;
  diagnosis: string;
};

type Group = {
  need: string;
  label: string;
  action: string;
  students: {
    student_id: number;
    full_name: string;
    mastery: number;
    retention: number;
    progress_pct: number | null;
    repeat_errors: number;
    prereq_weak: boolean;
  }[];
};

export default function TeacherPage() {
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [activeClass, setActiveClass] = useState<number | null>(null);
  const [radar, setRadar] = useState<RadarRow[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [rootCause, setRootCause] = useState<RootCause | null>(null);
  const [msg, setMsg] = useState("");

  const loadClass = useCallback(async (cid: number) => {
    setActiveClass(cid);
    setRootCause(null);
    try {
      const r = await api<{ rows: RadarRow[] }>(`/teacher/classes/${cid}/radar`);
      setRadar(r.rows);
      const g = await api<{ groups: Group[] }>(`/teacher/classes/${cid}/groups`);
      setGroups(g.groups.filter((x) => x.students.length > 0));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ classes: ClassInfo[] }>("/teacher/me/classes")
      .then((d) => {
        setClasses(d.classes);
        if (d.classes.length > 0) loadClass(d.classes[0].class_id);
      })
      .catch((e) => setMsg(e instanceof Error ? e.message : "خطا"));
  }, [loadClass]);

  async function openRootCause(topicId: number) {
    if (!activeClass) return;
    setRootCause(null);
    try {
      setRootCause(await api<RootCause>(`/teacher/classes/${activeClass}/root-cause/${topicId}`));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  if (msg && classes.length === 0) return <main className="p-6 text-red-600">{msg}</main>;
  if (classes.length === 0) return <main className="p-6 text-slate-400">کلاسی به شما تخصیص نیافته است.</main>;

  return (
    <main className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">پنل معلم — هوش کلاس</h1>
        <div className="flex items-center gap-2">
          {classes.map((c) => (
            <button
              key={c.class_id}
              className={`btn text-xs ${activeClass === c.class_id ? "bg-primary-600 text-white" : "border border-slate-300"}`}
              onClick={() => loadClass(c.class_id)}
            >
              کلاس {c.name} ({c.subject}) — {fa(c.students_count)} نفر
            </button>
          ))}
          <button
            className="btn-ghost text-xs"
            onClick={() => {
              localStorage.removeItem("daneshyar_token");
              window.location.href = "/login";
            }}
          >
            خروج
          </button>
        </div>
      </header>

      {msg && <div className="card border-amber-300 bg-amber-50 text-sm text-amber-800">{msg}</div>}

      {/* رادار مباحث (سند معلم §3) */}
      <section className="card space-y-3">
        <h2 className="font-semibold">رادار مباحث کلاس — مرتب بر اساس ضعف</h2>
        <p className="text-xs text-slate-400">روی هر ردیف کلیک کنید تا ریشه ضعف با گراف پیش‌نیاز باز شود.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 text-xs border-b border-slate-100">
                <th className="text-right py-2">مبحث</th>
                <th className="py-2">تسلط</th>
                <th className="py-2">ماندگاری</th>
                <th className="py-2">وضعیت</th>
                <th className="py-2">نیازمند توجه</th>
                <th className="py-2">علت خطاها</th>
              </tr>
            </thead>
            <tbody>
              {radar.map((row) => (
                <tr
                  key={row.topic_id}
                  className="border-b border-slate-50 hover:bg-primary-50/40 cursor-pointer"
                  onClick={() => openRootCause(row.topic_id)}
                >
                  <td className="py-2 text-right font-medium">
                    {row.title}
                    {row.prereq_weak && (
                      <span className="badge bg-orange-100 text-orange-700 mr-2" title="پیش‌نیاز این مبحث ضعیف است">
                        ⚠ پیش‌نیاز
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-center font-semibold">{fa(row.avg_mastery)}٪</td>
                  <td className="py-2 text-center">{fa(row.avg_retention * 100)}٪</td>
                  <td className="py-2 text-center">
                    <span className={`badge ${STATUS_COLOR[row.status] ?? STATUS_COLOR.unknown}`}>{STATUS_FA[row.status]}</span>
                  </td>
                  <td className="py-2 text-center">
                    <span className={row.weak_count > 0 ? "text-red-600 font-medium" : "text-slate-300"}>
                      {fa(row.weak_count)} / {fa(row.total_students)}
                    </span>
                  </td>
                  <td className="py-2 text-center">
                    <div className="flex flex-wrap justify-center gap-1">
                      {Object.entries(row.error_causes).map(([c, n]) => (
                        <span key={c} className="badge bg-slate-100 text-slate-600 text-[10px]">
                          {CAUSE_SHORT[c] ?? c}: {fa(n)}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {radar.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-6">
                    هنوز داده‌ای برای این کلاس ثبت نشده.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ریشه‌یابی (سند معلم §4) */}
      {rootCause && (
        <section className="card space-y-3 border-primary-200">
          <h2 className="font-semibold">
            ریشه‌یابی: {rootCause.topic.title} <span className="text-slate-400 text-sm">({fa(rootCause.topic.mastery)}٪)</span>
          </h2>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {rootCause.chain.map((step, i) => (
              <span key={step.topic_id} className="flex items-center gap-2">
                {i > 0 && <span className="text-slate-300">←</span>}
                <span
                  className={`badge ${
                    i === rootCause.chain.length - 1 && rootCause.root_reason === "prerequisite"
                      ? "bg-red-100 text-red-700"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {step.title} — {step.mastery !== null ? `${fa(step.mastery)}٪` : "بدون داده"}
                </span>
              </span>
            ))}
          </div>
          <div className={`rounded-xl p-3 text-sm ${rootCause.root_reason === "prerequisite" ? "bg-orange-50 text-orange-800" : "bg-sky-50 text-sky-800"}`}>
            {rootCause.diagnosis}
          </div>
        </section>
      )}

      {/* گروه‌بندی پنج‌گانه نیاز (سند معلم §6) */}
      <section className="space-y-3">
        <h2 className="font-semibold">گروه‌بندی نیاز — نه رتبه</h2>
        <p className="text-xs text-slate-400">دو دانش‌آموز با نمره یکسان می‌توانند نیاز کاملاً متفاوت داشته باشند.</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {groups.map((g) => (
            <div key={g.need} className="card space-y-2">
              <div className="flex items-center justify-between">
                <span className={`badge ${NEED_COLOR[g.need]}`}>{NEED_FA[g.need]}</span>
                <span className="text-xs text-slate-400">{fa(g.students.length)} نفر</span>
              </div>
              <p className="text-xs text-slate-500">اقدام پیشنهادی: {g.action}</p>
              <ul className="space-y-1 text-sm">
                {g.students.map((s) => (
                  <li key={s.student_id} className="flex items-center justify-between">
                    <span>
                      {s.full_name}
                      {s.prereq_weak && <span className="text-orange-500 text-xs"> ⚠</span>}
                    </span>
                    <span className="text-xs text-slate-400">
                      تسلط {fa(s.mastery)}٪ · ماندگاری {fa(s.retention * 100)}٪
                      {s.repeat_errors > 0 && <span className="text-red-500"> · {fa(s.repeat_errors)} خطای باز</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {groups.length === 0 && <div className="card text-sm text-slate-400 md:col-span-2">هنوز گروهی تشکیل نشده — داده کافی نیست.</div>}
        </div>
      </section>
    </main>
  );
}
