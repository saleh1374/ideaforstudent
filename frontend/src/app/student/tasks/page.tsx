"use client";

import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { TASK_TYPE_FA, fa } from "@/lib/labels";

type Task = {
  id: number;
  type: string;
  topic_id: number | null;
  for_date: string;
  priority: number;
  status: string;
  payload: Record<string, unknown>;
};

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ tasks: Task[] }>("/student/tasks").then((d) => setTasks(d.tasks)).catch((e) => setError(e.message));
  }, []);

  async function complete(t: Task, minicheck: boolean) {
    setMsg("");
    try {
      await api(`/student/tasks/${t.id}/complete`, { method: "POST", json: { minicheck_passed: minicheck } });
      setTasks((prev) => prev.map((x) => (x.id === t.id ? { ...x, status: "done" } : x)));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  const pending = tasks.filter((t) => t.status === "pending");
  const done = tasks.filter((t) => t.status === "done");

  return (
    <main className="max-w-3xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">برنامه امروز</h1>
        <a href="/student" className="btn-ghost text-xs">بازگشت</a>
      </div>

      {msg && <div className="card border-amber-300 bg-amber-50 text-sm text-amber-800">{msg}</div>}

      {pending.length === 0 && <div className="card text-sm text-slate-400">کار در صفی نیست. 🎉</div>}

      {pending.map((t) => (
        <div key={t.id} className="card flex items-center justify-between">
          <div>
            <p className="font-medium">{TASK_TYPE_FA[t.type] ?? t.type}</p>
            <p className="text-xs text-slate-400 mt-1">اولویت: {fa(t.priority, 2)}</p>
          </div>
          <div className="flex gap-2">
            {t.type === "lesson" ? (
              <button className="btn-primary text-xs" onClick={() => complete(t, true)}>
                آزمونک دادم ✓
              </button>
            ) : (
              <button className="btn-primary text-xs" onClick={() => complete(t, false)}>
                انجام شد
              </button>
            )}
          </div>
        </div>
      ))}

      {done.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-slate-500 mt-6">انجام‌شده‌ها</h2>
          {done.map((t) => (
            <div key={t.id} className="card flex items-center justify-between opacity-60">
              <span className="text-sm line-through">{TASK_TYPE_FA[t.type] ?? t.type}</span>
              <span className="badge bg-emerald-100 text-emerald-700">✓</span>
            </div>
          ))}
        </>
      )}
    </main>
  );
}
