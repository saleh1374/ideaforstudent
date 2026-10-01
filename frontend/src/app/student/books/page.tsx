"use client";

import { useEffect, useState } from "react";
import { api, getToken, BookNode } from "@/lib/api";
import { STATUS_FA, STATUS_COLOR, fa } from "@/lib/labels";

export default function BooksPage() {
  const [books, setBooks] = useState<BookNode[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ books: BookNode[] }>("/student/books").then((d) => setBooks(d.books)).catch((e) => setError(e.message));
  }, []);

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">کتاب‌های من</h1>
        <a href="/student" className="btn-ghost text-xs">بازگشت</a>
      </div>

      {books.map((b) => (
        <div key={b.id} className="card space-y-3">
          <button
            className="w-full flex items-center justify-between"
            onClick={() => setOpen(open === b.id ? null : b.id)}
          >
            <span className="font-semibold">{b.title}</span>
            <span className="text-xs text-slate-400">{b.chapters.length} فصل</span>
          </button>

          {open === b.id && (
            <div className="space-y-3 pt-2 border-t border-slate-100">
              {b.chapters.map((ch) => (
                <div key={ch.id} className="space-y-2">
                  <h3 className="text-sm font-semibold text-slate-600">{ch.title}</h3>
                  {ch.topics.map((t) => (
                    <div key={t.id} className="flex items-center justify-between text-sm">
                      <span>{t.title}</span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-slate-400">{t.effective_mastery !== null ? `${fa(t.effective_mastery)}٪` : ""}</span>
                        <span className={`badge ${STATUS_COLOR[t.status] ?? STATUS_COLOR.unknown}`}>{STATUS_FA[t.status]}</span>
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </main>
  );
}
