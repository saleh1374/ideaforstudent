"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, getToken, ExamSummary } from "@/lib/api";
import { EXAM_TYPE_FA } from "@/lib/labels";

export default function ExamsPage() {
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ exams: ExamSummary[] }>("/student/exams").then((d) => setExams(d.exams)).catch((e) => setError(e.message));
  }, []);

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  return (
    <main className="max-w-3xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">آزمون‌ها</h1>
        <a href="/student" className="btn-ghost text-xs">بازگشت</a>
      </div>

      {exams.length === 0 && <div className="card text-slate-400 text-sm">آزمونی در دسترس نیست.</div>}

      {exams.map((e) => (
        <div key={e.id} className="card flex items-center justify-between">
          <div>
            <p className="font-semibold">{e.title}</p>
            <p className="text-xs text-slate-500 mt-1">
              {EXAM_TYPE_FA[e.type] ?? e.type} · {e.item_count} سؤال
            </p>
          </div>
          <Link href={`/student/exams/${e.id}`} className="btn-primary text-xs">شروع</Link>
        </div>
      ))}
    </main>
  );
}
