"use client";

import { useEffect, useState } from "react";
import { api, getToken, HomeData } from "@/lib/api";
import { STATUS_FA, STATUS_COLOR, STATUS_ORDER, fa } from "@/lib/labels";
import Link from "next/link";

export default function StudentHome() {
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<HomeData>("/student/home").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <main className="p-6 text-red-600">{error}</main>;
  if (!data) return <main className="p-6 text-slate-400">در حال بارگذاری…</main>;

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">خانه — وضعیت امروز</h1>
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

      {/* سه شاخص اصلی (سند دانش‌آموز §7) */}
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card text-center">
          <p className="text-sm text-slate-500">پیشرفت در برنامه</p>
          <p className="text-3xl font-bold text-primary-600 mt-2">{fa(data.progress_pct, 1)}٪</p>
        </div>
        <div className="card text-center">
          <p className="text-sm text-slate-500">تسلط واقعی</p>
          <p className="text-3xl font-bold text-emerald-600 mt-2">{fa(data.mastery_pct, 1)}٪</p>
        </div>
        <div className="card text-center">
          <p className="text-sm text-slate-500">خطاهای رفع‌شده</p>
          <p className="text-3xl font-bold mt-2">
            {fa(data.errors_resolved)} <span className="text-base text-slate-400">از {fa(data.errors_total)}</span>
          </p>
        </div>
      </section>

      {Math.abs(data.gap) >= 15 && (
        <div className="card border-amber-300 bg-amber-50 text-sm text-amber-800">
          شکاف {fa(Math.abs(data.gap), 1)} واحدی بین پیشرفت و تسلط —{" "}
          {data.gap > 0 ? "«خوانده اما جا نیفتاده»؛ مرور و ترمیم اولویت دارد." : "«تسلط بالا، عقبی در برنامه»؛ سرعت درس جدید را بررسی کن."}
        </div>
      )}

      <section className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="card">
          <h2 className="font-semibold mb-3">وضعیت مباحث</h2>
          <div className="space-y-2">
            {STATUS_ORDER.map((s) => (
              <div key={s} className="flex items-center justify-between text-sm">
                <span className={`badge ${STATUS_COLOR[s]}`}>{STATUS_FA[s]}</span>
                <span className="font-medium">{fa(data.status_counts[s] ?? 0)} مبحث</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card space-y-4">
          <h2 className="font-semibold">دسترسی سریع</h2>
          {data.next_exam && (
            <div className="text-sm">
              <p className="text-slate-500">آزمون بعدی</p>
              <p className="font-medium">{data.next_exam.title}</p>
              <Link href={`/student/exams/${data.next_exam.id}`} className="btn-primary mt-2 w-full">
                رفتن به آزمون
              </Link>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Link href="/student/books" className="btn-ghost text-sm">کتاب‌های من</Link>
            <Link href="/student/errors" className="btn-ghost text-sm">دفترچه خطا</Link>
            <Link href="/student/exams" className="btn-ghost text-sm">آزمون‌ها</Link>
            <Link href="/student/tasks" className="btn-ghost text-sm">برنامه امروز</Link>
            <Link href="/assistant" className="btn-ghost text-sm">دستیار هوشمند</Link>
            <Link href="/boards" className="btn-ghost text-sm">بردها</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
