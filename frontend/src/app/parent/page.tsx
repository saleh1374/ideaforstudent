"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { STATUS_FA, STATUS_COLOR, STATUS_ORDER, fa } from "@/lib/labels";

type Child = { id: number; full_name: string; grade: string | null; class_id: number | null };

type Overview = {
  student_id: number;
  progress_pct: number;
  mastery_pct: number;
  gap: number;
  gap_message: string | null;
  errors_total: number;
  errors_open: number;
  status_counts: Record<string, number>;
  weak_topics: { topic_id: number; title: string; status: string }[];
  note_fa: string;
};

export default function ParentPage() {
  const [children, setChildren] = useState<Child[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  const loadChildren = useCallback(async () => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    try {
      const d = await api<{ children: Child[] }>("/parent/children");
      setChildren(d.children);
      if (d.children.length > 0 && selected === null) setSelected(d.children[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }, [selected]);

  useEffect(() => {
    loadChildren();
  }, [loadChildren]);

  useEffect(() => {
    if (selected === null) return;
    setOv(null);
    api<Overview>(`/parent/children/${selected}/overview`)
      .then(setOv)
      .catch((e) => setError(e.message));
  }, [selected]);

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">پنل والدین</h1>
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

      {/* انتخاب فرزند */}
      <section className="flex flex-wrap gap-2">
        {children.length === 0 && (
          <div className="card text-sm text-slate-400">فرزندی به حساب شما متصل نیست.</div>
        )}
        {children.map((c) => (
          <button
            key={c.id}
            className={`btn text-sm ${selected === c.id ? "bg-primary-600 text-white" : "border border-slate-300 hover:bg-slate-50"}`}
            onClick={() => setSelected(c.id)}
          >
            {c.full_name}
          </button>
        ))}
      </section>

      {ov && (
        <>
          {/* دو شاخص جدا: پیشرفت برنامه ≠ تسلط واقعی */}
          <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="card text-center">
              <p className="text-sm text-slate-500">پیشرفت در برنامه</p>
              <p className="text-3xl font-bold text-primary-600 mt-2">{fa(ov.progress_pct, 1)}٪</p>
            </div>
            <div className="card text-center">
              <p className="text-sm text-slate-500">تسلط واقعی</p>
              <p className="text-3xl font-bold text-emerald-600 mt-2">{fa(ov.mastery_pct, 1)}٪</p>
            </div>
            <div className="card text-center">
              <p className="text-sm text-slate-500">خطاهای باز</p>
              <p className="text-3xl font-bold text-red-600 mt-2">
                {fa(ov.errors_open)} <span className="text-base text-slate-400">از {fa(ov.errors_total)}</span>
              </p>
            </div>
          </section>

          {ov.gap_message && (
            <div className="card border-amber-300 bg-amber-50 text-sm text-amber-800">
              {Math.abs(ov.gap) >= 15 && (
                <>
                  شکاف {fa(Math.abs(ov.gap), 1)} واحدی بین پیشرفت و تسلط —{" "}
                </>
              )}
              {ov.gap_message}
            </div>
          )}

          <section className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="card">
              <h2 className="font-semibold mb-3">وضعیت مباحث</h2>
              <div className="space-y-2">
                {STATUS_ORDER.map((s) => (
                  <div key={s} className="flex items-center justify-between text-sm">
                    <span className={`badge ${STATUS_COLOR[s]}`}>{STATUS_FA[s]}</span>
                    <span className="font-medium">{fa(ov.status_counts[s] ?? 0)} مبحث</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <h2 className="font-semibold mb-3">مباحث نیازمند توجه</h2>
              {ov.weak_topics.length === 0 ? (
                <p className="text-sm text-slate-400">مبحث ضعیفی دیده نمی‌شود.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {ov.weak_topics.map((t) => (
                    <li key={t.topic_id} className="flex items-center justify-between">
                      <span>{t.title}</span>
                      <span className={`badge ${STATUS_COLOR[t.status]}`}>{STATUS_FA[t.status]}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <p className="text-xs text-slate-400">{ov.note_fa}</p>
        </>
      )}
    </main>
  );
}
