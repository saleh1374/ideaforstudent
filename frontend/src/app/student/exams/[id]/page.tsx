"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getToken, ExamItemOut } from "@/lib/api";
import { fa } from "@/lib/labels";

type Phase = "idle" | "running" | "done";

export default function ExamPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const examId = Number(params.id);

  const [phase, setPhase] = useState<Phase>("idle");
  const [items, setItems] = useState<ExamItemOut[]>([]);
  const [answers, setAnswers] = useState<Record<number, { selected: string; confidence: number; flagged_guess: boolean; time_spent_ms: number }>>({});
  const [startedAt, setStartedAt] = useState<number>(0);
  const [result, setResult] = useState<{ raw_score: number; percent: number } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
    }
  }, []);

  async function start() {
    try {
      const d = await api<{ attempt_id: number; items: ExamItemOut[] }>(`/student/exams/${examId}/start`, { method: "POST" });
      setItems(d.items);
      setStartedAt(Date.now());
      setPhase("running");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }

  function setAnswer(eid: number, patch: Partial<{ selected: string; confidence: number; flagged_guess: boolean }>) {
    setAnswers((prev) => {
      const current = prev[eid] ?? { selected: "", confidence: 3, flagged_guess: false, time_spent_ms: 0 };
      return { ...prev, [eid]: { ...current, ...patch } };
    });
  }

  async function submit() {
    try {
      const perItemMs = Math.floor((Date.now() - startedAt) / Math.max(items.length, 1));
      const payload = items.map((it) => ({
        exam_item_id: it.exam_item_id,
        ...(answers[it.exam_item_id] ?? {}),
        time_spent_ms: perItemMs,
      }));
      const res = await api<{ raw_score: number; percent: number }>(`/student/exams/${examId}/submit`, {
        method: "POST",
        json: { answers: payload },
      });
      setResult(res);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }

  if (phase === "done") {
    return (
      <main className="max-w-2xl mx-auto p-6">
        <div className="card text-center space-y-4">
          <h1 className="text-lg font-semibold">کارنامه آزمون</h1>
          <p className="text-4xl font-bold text-primary-600">{fa(result?.percent ?? 0, 1)}٪</p>
          <p className="text-sm text-slate-500">نمره: {fa(result?.raw_score ?? 0, 2)} — تحلیل خطاها وارد دفترچه خطا شد.</p>
          <div className="flex gap-2 justify-center">
            <button className="btn-primary" onClick={() => router.push("/student/errors")}>دفترچه خطا</button>
            <button className="btn-ghost" onClick={() => router.push("/student")}>خانه</button>
          </div>
        </div>
      </main>
    );
  }

  if (phase === "idle") {
    return (
      <main className="max-w-2xl mx-auto p-6">
        <div className="card space-y-4 text-center">
          <h1 className="text-lg font-semibold">آزمون آماده است</h1>
          <p className="text-sm text-slate-500">پاسخ‌ها و زمان پاسخ ذخیره می‌شود تا تحلیل دقیق‌تری داشته باشی.</p>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button className="btn-primary w-full" onClick={start}>شروع آزمون</button>
        </div>
      </main>
    );
  }

  const answeredCount = Object.values(answers).filter((a) => a.selected).length;

  return (
    <main className="max-w-2xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">در حال آزمون</h1>
        <span className="text-sm text-slate-500">{fa(answeredCount)} از {fa(items.length)}</span>
      </div>

      {items.map((it) => (
        <div key={it.exam_item_id} className="card space-y-3">
          <p className="font-medium">
            {fa(it.order)}. {it.body}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {Object.entries(it.options).map(([k, v]) => (
              <button
                key={k}
                className={`btn-justify justify-start text-right px-3 py-2 rounded-xl border text-sm transition ${
                  answers[it.exam_item_id]?.selected === k
                    ? "bg-primary-50 border-primary-500 text-primary-700"
                    : "border-slate-200 hover:bg-slate-50"
                }`}
                onClick={() => setAnswer(it.exam_item_id, { selected: k })}
              >
                <b>{k})</b> {v}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <label>میزان اطمینان:</label>
            {[1, 2, 3, 4, 5].map((c) => (
              <button
                key={c}
                className={`w-7 h-7 rounded-full border ${
                  answers[it.exam_item_id]?.confidence === c ? "bg-primary-600 text-white border-primary-600" : "border-slate-300"
                }`}
                onClick={() => setAnswer(it.exam_item_id, { confidence: c })}
              >
                {fa(c)}
              </button>
            ))}
            <label className="flex items-center gap-1 mr-auto">
              <input
                type="checkbox"
                checked={answers[it.exam_item_id]?.flagged_guess ?? false}
                onChange={(e) => setAnswer(it.exam_item_id, { flagged_guess: e.target.checked })}
              />
              حدس زدم
            </label>
          </div>
        </div>
      ))}

      {error && <p className="text-red-600 text-sm">{error}</p>}
      <button className="btn-primary w-full" onClick={submit} disabled={answeredCount === 0}>
        ثبت نهایی
      </button>
    </main>
  );
}
