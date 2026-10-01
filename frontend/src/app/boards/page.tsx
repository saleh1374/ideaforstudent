"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { STATUS_FA, STATUS_COLOR, fa } from "@/lib/labels";

type BoardRow = {
  key: string;
  kind: string;
  students_with_data: number;
  avg_mastery: number | null;
  avg_retention: number | null;
  weak_count: number | null;
  status_counts: Record<string, number> | null;
  suppressed: boolean;
};

type Board = {
  scope: string;
  min_group: number;
  note_fa: string;
  rows: BoardRow[];
  total?: BoardRow;
};

type Tab = "school" | "province" | "national";

const TAB_FA: Record<Tab, string> = {
  school: "مدرسه",
  province: "استان",
  national: "کشور",
};

export default function BoardsPage() {
  const [tab, setTab] = useState<Tab>("school");
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (t: Tab) => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setBoard(null);
    try {
      // MVP: شناسه‌های نمونه (مدرسه ۱، استان ۱)
      const path = t === "school" ? "/boards/school/1" : t === "province" ? "/boards/province/1" : "/boards/national";
      setBoard(await api<Board>(path));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">بردهای تحلیلی</h1>
          <p className="text-xs text-slate-400 mt-1">نام‌ها مستعار است و اعداد زیر حداقل جمعیت نمایش داده نمی‌شوند.</p>
        </div>
        <a href="/student" className="btn-ghost text-xs">
          بازگشت
        </a>
      </header>

      <nav className="flex gap-2">
        {(["school", "province", "national"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`btn text-sm ${tab === t ? "bg-primary-600 text-white" : "border border-slate-300 hover:bg-slate-50"}`}
            onClick={() => setTab(t)}
          >
            {TAB_FA[t]}
          </button>
        ))}
      </nav>

      {board && (
        <section className="space-y-3">
          <div className="card border-slate-200 bg-slate-50 text-xs text-slate-600">{board.note_fa}</div>

          {board.total && (
            <div className="card">
              <h2 className="font-semibold mb-3">جمع کلی</h2>
              <BoardAggregate row={board.total} />
            </div>
          )}

          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs border-b border-slate-100">
                  <th className="text-right py-2">کد مستعار</th>
                  <th className="py-2">دانش‌آموز دارای داده</th>
                  <th className="py-2">تسلط</th>
                  <th className="py-2">ماندگاری</th>
                  <th className="py-2">ضعیف/بحرانی</th>
                  <th className="py-2">وضعیت</th>
                </tr>
              </thead>
              <tbody>
                {board.rows.map((row) => (
                  <tr key={row.key} className="border-b border-slate-50">
                    <td className="py-2 text-right font-medium">{row.key}</td>
                    <td className="py-2 text-center">{fa(row.students_with_data)}</td>
                    <td className="py-2 text-center font-semibold">
                      {row.suppressed ? <span className="text-slate-400">زیر حد نصاب</span> : `${fa(row.avg_mastery)}٪`}
                    </td>
                    <td className="py-2 text-center">
                      {row.suppressed ? "—" : row.avg_retention !== null ? `${fa(row.avg_retention * 100)}٪` : "—"}
                    </td>
                    <td className="py-2 text-center">{row.weak_count === null ? "—" : fa(row.weak_count)}</td>
                    <td className="py-2 text-center">
                      {row.status_counts ? (
                        <span className="badge bg-slate-100 text-slate-600">
                          {Object.entries(row.status_counts)
                            .map(([k, v]) => `${STATUS_FA[k] ?? k}: ${fa(v)}`)
                            .join(" · ")}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-slate-400">
            زیر حداقل جمعیت {fa(board.min_group)} نفر، عددی نمایش داده نمی‌شود — نه تخمین، نه رنگ (حریم خصوصی §8.2).
          </p>
        </section>
      )}
    </main>
  );
}

function BoardAggregate({ row }: { row: BoardRow }) {
  if (row.suppressed) {
    return <p className="text-sm text-slate-400">با جمعیت فعلی ({fa(row.students_with_data)} نفر دارای داده) زیر حد نصاب است.</p>;
  }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center text-sm">
      <div>
        <p className="text-xs text-slate-500">دانش‌آموز</p>
        <p className="font-bold">{fa(row.students_with_data)}</p>
      </div>
      <div>
        <p className="text-xs text-slate-500">تسلط</p>
        <p className="font-bold text-emerald-600">{fa(row.avg_mastery)}٪</p>
      </div>
      <div>
        <p className="text-xs text-slate-500">ماندگاری</p>
        <p className="font-bold">{row.avg_retention !== null ? `${fa(row.avg_retention * 100)}٪` : "—"}</p>
      </div>
      <div>
        <p className="text-xs text-slate-500">ضعیف/بحرانی</p>
        <p className="font-bold text-red-600">{row.weak_count === null ? "—" : fa(row.weak_count)}</p>
      </div>
    </div>
  );
}
