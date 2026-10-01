"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";

type Overview = {
  scope: string;
  province_id: number | null;
  schools_count: number;
  students_count: number;
  avg_mastery: number | null;
  suppressed: boolean;
  min_group: number;
  worst_topics: { topic_id: number; subject: string | null; students_count: number; avg_mastery: number | null; weak_ratio: number | null }[];
  note_fa: string;
};

type TopicRow = {
  topic_id: number;
  subject: string | null;
  students_count: number;
  avg_mastery: number | null;
  avg_retention: number | null;
  weak_ratio: number | null;
  suppressed: boolean;
};

type Tab = "province" | "national";

export default function GeoPage() {
  const [tab, setTab] = useState<Tab>("province");
  const [ov, setOv] = useState<Overview | null>(null);
  const [rows, setRows] = useState<TopicRow[]>([]);
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  const [refreshMsg, setRefreshMsg] = useState("");

  const load = useCallback(async (t: Tab) => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setOv(null);
    setRefreshMsg("");
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);
      const base = t === "province" ? "/geo/province/1" : "/geo/national";
      const [o, s] = await Promise.all([
        api<Overview>(`${base}/overview`),
        api<{ rows: TopicRow[] }>(`${base}/topics`),
      ]);
      setOv(o);
      setRows(s.rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  async function refresh() {
    setRefreshMsg("");
    try {
      const res = await api<{ national: { written: number; suppressed: number } }>("/geo/national/refresh", { method: "POST" });
      setRefreshMsg(`✓ بازمحاسبه شد: ${fa(res.national.written)} مبحث (${fa(res.national.suppressed)} سرکوب‌شده)`);
      await load(tab);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  const title = tab === "province" ? "مدیر کل استان" : "وزارت / سطح ملی";

  return (
    <main className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">{title}</h1>
          <p className="text-xs text-slate-400">تجمیع‌های province / national_topic_stats — عددها تابع حداقل جمعیت ۱۰</p>
        </div>
        <div className="flex gap-2">
          {(role === "ministry" || role === "province_admin") && (
            <button className="btn-ghost text-xs" onClick={refresh}>
              بازمحاسبه تجمیع‌ها
            </button>
          )}
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

      <nav className="flex gap-2">
        {(["province", "national"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`btn text-sm ${tab === t ? "bg-primary-600 text-white" : "border border-slate-300 hover:bg-slate-50"}`}
            onClick={() => setTab(t)}
          >
            {t === "province" ? "دید استان" : "دید کشور"}
          </button>
        ))}
      </nav>

      {refreshMsg && <div className="card border-primary-200 bg-primary-50 text-sm text-primary-700">{refreshMsg}</div>}

      {ov && (
        <>
          <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="card text-center">
              <p className="text-xs text-slate-500">مدارس</p>
              <p className="text-2xl font-bold mt-1">{fa(ov.schools_count)}</p>
            </div>
            <div className="card text-center">
              <p className="text-xs text-slate-500">دانش‌آموزان دارای داده</p>
              <p className="text-2xl font-bold mt-1">{fa(ov.students_count)}</p>
            </div>
            <div className="card text-center">
              <p className="text-xs text-slate-500">میانگین تسلط</p>
              <p className="text-2xl font-bold mt-1 text-emerald-600">
                {ov.suppressed ? <span className="text-slate-400 text-base">زیر حد نصاب</span> : `${fa(ov.avg_mastery)}٪`}
              </p>
            </div>
            <div className="card text-center">
              <p className="text-xs text-slate-500">مباحث نیازمند برنامه</p>
              <p className="text-2xl font-bold mt-1 text-red-600">{fa(ov.worst_topics.length)}</p>
            </div>
          </section>

          <div className="card border-slate-200 bg-slate-50 text-xs text-slate-600">{ov.note_fa}</div>

          <section className="card overflow-x-auto">
            <h2 className="font-semibold mb-3">مباحث با کمترین تسط (تجمیع ملی/استانی)</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b border-slate-100">
                  <th className="text-right py-2">مبحث</th>
                  <th className="py-2">درس</th>
                  <th className="py-2">دانش‌آموز</th>
                  <th className="py-2">تسط</th>
                  <th className="py-2">ماندگاری</th>
                  <th className="py-2">سهم ضعیف</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.topic_id} className="border-b border-slate-50">
                    <td className="py-2 text-right">#{r.topic_id}</td>
                    <td className="py-2 text-center">{r.subject ?? "—"}</td>
                    <td className="py-2 text-center">{fa(r.students_count)}</td>
                    <td className="py-2 text-center font-semibold">
                      {r.suppressed ? <span className="text-slate-400 text-xs">زیر حد نصاب</span> : `${fa(r.avg_mastery)}٪`}
                    </td>
                    <td className="py-2 text-center">
                      {r.suppressed || r.avg_retention === null ? "—" : `${fa(r.avg_retention * 100)}٪`}
                    </td>
                    <td className="py-2 text-center">
                      {r.suppressed || r.weak_ratio === null ? "—" : `${fa(r.weak_ratio * 100)}٪`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </main>
  );
}
