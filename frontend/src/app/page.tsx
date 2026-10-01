"use client";

import { useEffect } from "react";

export default function Home() {
  useEffect(() => {
    window.location.href = "/login";
  }, []);
  return (
    <main className="grid min-h-screen place-content-center gap-4 bg-canvas text-center">
      <span className="mx-auto grid h-16 w-16 animate-fade-in-up place-items-center rounded-2xl bg-brand-gradient text-2xl font-black text-white shadow-lift">
        د
      </span>
      <p className="animate-fade-in text-sm font-semibold text-ink-muted">دانشیار — در حال انتقال به ورود…</p>
    </main>
  );
}
