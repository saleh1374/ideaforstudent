"use client";

import { useEffect, useRef, useState } from "react";
import { api, getToken } from "@/lib/api";
import { STATUS_FA, STATUS_COLOR, fa } from "@/lib/labels";

type Source = { type: string; id: number; title: string; status: string };

type Msg = {
  id: number;
  role: "user" | "assistant";
  content: string;
  model_tier: string | null;
  sources: Source[] | null;
  cached: boolean;
};

type ChatResp = {
  conversation_id: number;
  reply: string;
  sources: Source[];
  model_tier: string;
  cached: boolean;
};

export default function AssistantPage() {
  const [convId, setConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastMeta, setLastMeta] = useState<{ tier: string; cached: boolean } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setError("");
    // پیام کاربر فوراً نمایش داده می‌شود
    const tempId = Date.now();
    setMessages((m) => [...m, { id: tempId, role: "user", content: text, model_tier: null, sources: null, cached: false }]);
    try {
      const out = await api<ChatResp>("/assistant/chat", {
        method: "POST",
        json: { message: text, conversation_id: convId },
      });
      setConvId(out.conversation_id);
      setLastMeta({ tier: out.model_tier, cached: out.cached });
      setMessages((m) => [
        ...m,
        { id: tempId + 1, role: "assistant", content: out.reply, model_tier: out.model_tier, sources: out.sources, cached: out.cached },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="max-w-3xl mx-auto p-6 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">دستیار هوشمند</h1>
          <p className="text-xs text-slate-400 mt-1">پاسخ‌ها از کاتالوگ درس و وضعیت خودتان ساخته می‌شوند؛ منابع نمایش داده می‌شوند.</p>
        </div>
        <div className="flex gap-2">
          <a href="/boards" className="btn-ghost text-xs">بردها</a>
          <a href="/student" className="btn-ghost text-xs">بازگشت</a>
        </div>
      </header>

      <section className="card space-y-4 min-h-[50vh] flex flex-col">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400">
            مثلاً بپرسید: «تعداد زیرمجموعه‌ها چند است؟» یا «چرا نسبت‌های مثلثاتی مهم‌اند؟»
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-start" : "justify-end"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                m.role === "user" ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-800"
              }`}
            >
              {m.content}
              {m.role === "assistant" && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span className="badge bg-white border border-slate-200">
                    {m.cached ? "از کش معنایی" : m.model_tier === "large" ? "مدل تحلیلی" : "مدل سبک"}
                  </span>
                  {(m.sources ?? []).map((s) => (
                    <span key={`${s.type}-${s.id}`} className="badge bg-white border border-slate-200">
                      {s.title}
                      {s.status !== "unknown" && (
                        <span className={`mr-1 ${STATUS_COLOR[s.status] ?? ""} rounded-full px-1`}>
                          {STATUS_FA[s.status] ?? s.status}
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <p className="text-xs text-slate-400">در حال پردازش…</p>}
        {error && <p className="text-xs text-red-600">{error}</p>}
        <div ref={bottomRef} />
      </section>

      <form onSubmit={send} className="flex gap-2">
        <input
          className="input flex-1"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="سؤال خود را بنویسید…"
        />
        <button className="btn-primary" disabled={busy || !input.trim()}>
          ارسال
        </button>
      </form>

      {lastMeta && (
        <p className="text-[11px] text-slate-400">
          {lastMeta.cached
            ? "پاسخ از کش معنایی آمد — بدون فراخوانی مدل."
            : `پاسخ با ${lastMeta.tier === "large" ? "مدل تحلیلی" : "مدل سبک"} ساخته شد.`}
        </p>
      )}
    </main>
  );
}
