"use client";

import { useEffect, useState } from "react";
import { api, getToken, ErrorOut } from "@/lib/api";
import { CAUSE_FA, fa } from "@/lib/labels";

const STATUS_FA: Record<string, string> = {
  open: "باز",
  in_remediation: "در حال ترمیم",
  resolved: "رفع‌شده",
  relapsed: "بازگشته",
};

type RetestPlan = {
  targets: { topic_id: number; title: string; causes: Record<string, number>; error_ids: number[] }[];
  can_build: boolean;
  note_fa: string;
};

export default function ErrorNotebookPage() {
  const [errors, setErrors] = useState<ErrorOut[]>([]);
  const [byCause, setByCause] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<string>("all");
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<RetestPlan | null>(null);
  const [building, setBuilding] = useState(false);
  const [msg, setMsg] = useState("");

  async function loadPlan() {
    try {
      setPlan(await api<RetestPlan>("/student/retest/plan"));
    } catch {
      /* بی‌رابط */
    }
  }

  async function buildRetest() {
    setBuilding(true);
    setMsg("");
    try {
      const out = await api<{ exam_id: number }>("/student/retest/build", { method: "POST" });
      setMsg(`✓ بازآزمون ترمیمی ساخته شد — از بخش آزمون‌ها ادامه دهید.`);
      await loadPlan();
      // هدایت به آزمون ساخته‌شده
      window.location.href = `/student/exams/${out.exam_id}`;
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
      setBuilding(false);
    }
  }

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ errors: ErrorOut[]; by_cause: Record<string, number> }>("/student/errors")
      .then((d) => {
        setErrors(d.errors);
        setByCause(d.by_cause);
      })
      .catch((e) => setError(e.message));
    loadPlan();
  }, []);

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  const visible = filter === "all" ? errors : errors.filter((e) => e.cause === filter);

  return (
    <main className="max-w-3xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">دفترچه خطا</h1>
        <a href="/student" className="btn-ghost text-xs">بازگشت</a>
      </div>

      {/* چرخه ترمیم/بازآزمون (فاز ۴) */}
      {plan && plan.can_build && (
        <div className="card space-y-3 border-primary-200 bg-primary-50">
          <div>
            <h2 className="font-semibold text-sm text-primary-800">بازآزمون ترمیمی پیشنهادی</h2>
            <p className="text-xs text-primary-700 mt-1">{plan.note_fa}</p>
          </div>
          <ul className="text-sm space-y-1">
            {plan.targets.map((t) => (
              <li key={t.topic_id} className="flex items-center justify-between">
                <span>{t.title}</span>
                <span className="badge bg-white border border-primary-200 text-primary-700">
                  {Object.entries(t.causes)
                    .map(([c, n]) => `${CAUSE_FA[c] ?? c}: ${n}`)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
          <button className="btn-primary text-sm" onClick={buildRetest} disabled={building}>
            {building ? "در حال ساخت…" : "ساخت و شروع بازآزمون"}
          </button>
          {msg && <p className="text-xs text-primary-700">{msg}</p>}
        </div>
      )}

      {/* توزیع علت خطاها */}
      <div className="card space-y-2">
        <h2 className="text-sm font-semibold text-slate-600">توزیع علت خطاها</h2>
        <div className="flex flex-wrap gap-2">
          {Object.entries(byCause).map(([c, n]) => (
            <button
              key={c}
              onClick={() => setFilter(filter === c ? "all" : c)}
              className={`badge cursor-pointer ${
                filter === c ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {CAUSE_FA[c] ?? c}: {fa(n)}
            </button>
          ))}
          {Object.keys(byCause).length === 0 && <span className="text-xs text-slate-400">هنوز خطایی ثبت نشده.</span>}
        </div>
      </div>

      {visible.map((e) => (
        <div key={e.id} className={`card space-y-2 ${e.status === "relapsed" ? "border-red-300 bg-red-50" : ""}`}>
          <div className="flex items-center justify-between text-xs">
            <span className="badge bg-slate-100 text-slate-600">{CAUSE_FA[e.cause] ?? e.cause}</span>
            <span className={e.status === "relapsed" ? "text-red-600 font-medium" : "text-slate-400"}>
              {STATUS_FA[e.status] ?? e.status}
            </span>
          </div>
          <p className="text-sm font-medium">{e.item?.body}</p>
          <p className="text-xs text-slate-400">
            پاسخ درست: <b>{e.item?.correct}</b>
          </p>
        </div>
      ))}
    </main>
  );
}
