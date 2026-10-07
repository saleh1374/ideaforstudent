"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, getToken } from "@/lib/api";
import { STATUS_FA, STATUS_COLOR, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { EmptyState } from "@/components/ui/empty";
import { SkeletonText } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconChart, IconChat, IconRefresh, IconSend, IconSparkles } from "@/components/ui/icons";

/**
 * دستیار هوشمند: چت چندمرحله‌ای با تاریخچه گفتگوها (GET /assistant/conversations
 * + GET /assistant/conversations/{id}) و نشانگر وضعیت سقف روزانه/سکوت آزمون
 * (GET /assistant/status). همه واکشی‌ها تدافعی‌اند تا خطا کل صفحه را نیندازد.
 */

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

type ConvItem = { id: number; title: string | null; created_at: string | null };

type StatusData = {
  used: number;
  cap: number;
  remaining: number;
  limit_reached: boolean;
  silenced: boolean;
  silence_exam_title: string | null;
  blocked: boolean;
  reason_fa: string | null;
  note_fa: string | null;
};

const EXAMPLES = [
  "تعداد زیرمجموعه‌ها چند است؟",
  "چرا نسبت‌های مثلثاتی مهم‌اند؟",
  "کدام مباحثم ضعیف است و چطور مرور کنم؟",
];

function convDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fa-IR", { dateStyle: "short" });
}

export default function AssistantPage() {
  const [convId, setConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastMeta, setLastMeta] = useState<{ tier: string; cached: boolean } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  /* تاریخچه گفتگوها — GET /assistant/conversations */
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [convsLoading, setConvsLoading] = useState(false);
  const [convsError, setConvsError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false); // فقط موبایل: لیست جمع‌شونده
  const [openingId, setOpeningId] = useState<number | null>(null);

  /* وضعیت دستیار — GET /assistant/status */
  const [status, setStatus] = useState<StatusData | null>(null);
  const [statusError, setStatusError] = useState("");

  const loadConversations = useCallback(async () => {
    setConvsLoading(true);
    setConvsError("");
    try {
      const d = await api<{ conversations: ConvItem[] }>("/assistant/conversations");
      setConvs(Array.isArray(d?.conversations) ? d.conversations : []);
    } catch (e) {
      // شکست تاریخچه نباید چت را از کار بیندازد
      const msg = e instanceof ApiError ? e.detail ?? e.message : e instanceof Error ? e.message : "خطا";
      setConvsError(msg);
    } finally {
      setConvsLoading(false);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    setStatusError("");
    try {
      setStatus(await api<StatusData>("/assistant/status"));
    } catch (e) {
      setStatusError(e instanceof ApiError ? e.detail ?? e.message : e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    void loadConversations();
    void loadStatus();
  }, [loadConversations, loadStatus]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  /** باز کردن یک گفتگوی قدیمی — GET /assistant/conversations/{id} */
  async function openConversation(id: number) {
    if (busy || openingId !== null) return;
    setOpeningId(id);
    setError("");
    try {
      const d = await api<{ id: number; messages: Msg[] }>(`/assistant/conversations/${id}`);
      setConvId(typeof d?.id === "number" ? d.id : id);
      setMessages(Array.isArray(d?.messages) ? d.messages : []);
      setLastMeta(null);
      if (historyOpen) setHistoryOpen(false);
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail ?? e.message : e instanceof Error ? e.message : "خطا";
      toast(msg, "error");
    } finally {
      setOpeningId(null);
    }
  }

  /** گفتگوی جدید: سرور با اولین پیام، مکالمه تازه می‌سازد. */
  function newConversation() {
    setConvId(null);
    setMessages([]);
    setLastMeta(null);
    setError("");
    if (historyOpen) setHistoryOpen(false);
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setError("");
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
      // چندمرحله‌ای: فهرست گفتگوها + شمارنده روزانه تازه می‌شوند
      void loadConversations();
      void loadStatus();
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail ?? err.message : err instanceof Error ? err.message : "خطا";
      setError(msg);
      toast(msg, "error");
      void loadStatus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-6">
        <PageHeader
          title="دستیار هوشمند"
          description="پاسخ‌ها از کاتالوگ درس و وضعیت خودتان ساخته می‌شوند؛ منابع هر پاسخ نمایش داده می‌شوند."
          crumbs={[{ label: "دانشیار" }, { label: "عمومی" }, { label: "دستیار هوشمند" }]}
          badge={
            <span className="inline-flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-gradient px-2.5 py-1 text-[11px] font-bold text-white shadow-soft">
                <IconSparkles size={13} />
                SLM
              </span>
              {/* وضعیت بک‌اند: سقف روزانه + سکوت حین آزمون (GET /assistant/status) */}
              {statusError ? (
                <Badge tone="neutral">وضعیت دستیار: نامشخص</Badge>
              ) : status ? (
                status.silenced ? (
                  <Badge tone="warning" dot>
                    خاموش حین آزمون
                  </Badge>
                ) : status.limit_reached ? (
                  <Badge tone="danger" dot>
                    سقف روزانه پر شد
                  </Badge>
                ) : (
                  <Badge tone="primary" dot>
                    {fa(status.used)} از {fa(status.cap)} پرسش امروز — {fa(status.remaining)} باقی‌مانده
                  </Badge>
                )
              ) : (
                <Badge tone="neutral">در حال بررسی وضعیت…</Badge>
              )}
            </span>
          }
          actions={
            <ButtonLink href="/boards" variant="ghost" size="sm" icon={<IconChart size={15} />}>
              بردها
            </ButtonLink>
          }
        />

        {/* علت مسدودی (سقف روزانه / سکوت آزمون) — فقط وقتی سرور چیزی فرستاده */}
        {status?.blocked && status.reason_fa && (
          <Alert variant="warning" title="دستیار موقتاً در دسترس نیست">
            {status.reason_fa}
          </Alert>
        )}

        {/* تاریخچه در موبایل جمع‌شونده است؛ در دسکتاپ همیشه کنار چت */}
        <div className="lg:hidden">
          <Button
            variant="ghost"
            size="sm"
            icon={<IconChat size={15} />}
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((v) => !v)}
          >
            گفتگوهای قبلی ({fa(convs.length)})
          </Button>
        </div>

        <div className="grid items-start gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
          {/* ---------------- پنل گفتگوهای قبلی ---------------- */}
          <aside className={`${historyOpen ? "block" : "hidden"} lg:block`}>
            <Card padded={false} className="overflow-hidden">
              <div className="flex items-center justify-between gap-2 border-b border-line bg-surface-sunken px-4 py-3">
                <p className="text-xs font-bold text-ink">گفتگوهای قبلی</p>
                <Button
                  variant="ghost"
                  size="sm"
                  loading={convsLoading}
                  icon={<IconRefresh size={13} />}
                  onClick={() => void loadConversations()}
                >
                  تازه‌سازی
                </Button>
              </div>

              <div className="max-h-[52vh] space-y-2 overflow-y-auto p-2">
                {convsError && <Alert variant="danger">{convsError}</Alert>}
                {convsLoading && convs.length === 0 && <SkeletonText lines={5} />}
                {!convsLoading && !convsError && convs.length === 0 && (
                  <EmptyState
                    compact
                    icon={<IconChat size={22} />}
                    title="هنوز گفتگویی ثبت نشده"
                    description="نخستین پرسش شما اینجا ذخیره می‌شود."
                  />
                )}

                <ul className="space-y-1">
                  {convs.map((c) => {
                    const active = c.id === convId;
                    return (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => void openConversation(c.id)}
                          disabled={openingId !== null}
                          className={`w-full rounded-xl px-3 py-2.5 text-right transition ${
                            active
                              ? "bg-surface text-primary-700 ring-1 ring-primary-100"
                              : "text-ink-muted hover:bg-surface-sunken hover:text-ink"
                          } ${openingId === c.id ? "animate-pulse" : ""}`}
                        >
                          <span className="block truncate text-xs font-semibold">{c.title || "بدون عنوان"}</span>
                          <span className="num mt-0.5 block text-[10px] text-ink-faint">
                            {convDate(c.created_at)}
                            {active && " · در حال نمایش"}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>

              <div className="border-t border-line p-2">
                <Button variant="soft" size="sm" className="w-full" onClick={newConversation}>
                  گفتگوی جدید
                </Button>
              </div>
            </Card>
          </aside>

          {/* ---------------- گفتگو ---------------- */}
          <Card padded={false} className="flex min-h-[52vh] flex-col overflow-hidden">
            <div className="flex items-center gap-2 border-b border-line bg-surface-sunken px-5 py-3">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-gradient text-white">
                <IconSparkles size={14} />
              </span>
              <p className="text-xs font-bold text-ink">گفت‌وگو با دستیار</p>
              {convId !== null && <span className="num text-[11px] text-ink-faint">گفتگوی {fa(convId)}</span>}
              {messages.length > 0 && <span className="num mr-auto text-[11px] text-ink-faint">{fa(messages.length)} پیام</span>}
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-5">
              {messages.length === 0 && (
                <div className="py-6">
                  <EmptyState
                    icon={<IconSparkles size={26} />}
                    title="از من بپرسید"
                    description="یکی از پرسش‌های نمونه را انتخاب کن یا سؤال خودت را بنویس."
                  />
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {EXAMPLES.map((ex) => (
                      <button
                        key={ex}
                        type="button"
                        onClick={() => setInput(ex)}
                        className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[11px] font-semibold text-ink-muted shadow-soft transition hover:border-primary-300 hover:bg-primary-50 hover:text-primary-700"
                      >
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m) => (
                <div key={m.id} className={`flex animate-fade-in-up ${m.role === "user" ? "justify-start" : "justify-end"}`}>
                  <div className={`flex max-w-[88%] gap-2.5 ${m.role === "user" ? "flex-row" : "flex-row-reverse"}`}>
                    <Avatar name={m.role === "user" ? "شما" : "دانشیار"} size="sm" className={m.role === "assistant" ? "bg-brand-gradient" : ""} />
                    <div>
                      <div
                        className={`whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-7 ${
                          m.role === "user"
                            ? "rounded-tr-md bg-brand-gradient text-white shadow-lift"
                            : "rounded-tl-md border border-line bg-surface-sunken text-ink shadow-soft"
                        }`}
                      >
                        {m.content}
                      </div>

                      {m.role === "assistant" && (
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                          <span className="rounded-full border border-line bg-surface px-2 py-0.5 font-semibold text-ink-muted">
                            {m.cached ? "از کش معنایی" : m.model_tier === "large" ? "مدل تحلیلی" : "مدل سبک"}
                          </span>
                          {(m.sources ?? []).map((s) => (
                            <span
                              key={`${s.type}-${s.id}`}
                              className="flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 text-ink-faint"
                            >
                              {s.title}
                              {s.status !== "unknown" && (
                                <span className={`rounded-full px-1 ${STATUS_COLOR[s.status] ?? ""}`}>{STATUS_FA[s.status] ?? s.status}</span>
                              )}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {busy && (
                <div className="flex justify-end">
                  <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-md border border-line bg-surface-sunken px-4 py-3 shadow-soft">
                    {[0, 1, 2].map((i) => (
                      <span
                        key={i}
                        className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary-400"
                        style={{ animationDelay: `${i * 120}ms` }}
                      />
                    ))}
                    <span className="mr-1 text-[11px] text-ink-faint">در حال پردازش…</span>
                  </div>
                </div>
              )}

              {error && <Alert variant="danger">{error}</Alert>}
              <div ref={bottomRef} />
            </div>

            {/* composer */}
            <form onSubmit={send} className="flex items-center gap-2 border-t border-line bg-surface px-4 py-3 sm:px-5">
              <input
                className="flex-1 rounded-xl border border-line bg-surface-sunken px-4 py-2.5 text-sm text-ink placeholder:text-ink-faint transition focus:border-primary-400 focus:bg-surface focus:ring-2 focus:ring-primary-500/20"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="سؤال خود را بنویسید…"
              />
              <Button type="submit" disabled={busy || !input.trim()} icon={<IconSend size={15} />}>
                ارسال
              </Button>
            </form>
          </Card>
        </div>

        {lastMeta && (
          <p className="text-center text-[11px] text-ink-faint">
            {lastMeta.cached
              ? "پاسخ از کش معنایی آمد — بدون فراخوانی مدل."
              : `پاسخ با ${lastMeta.tier === "large" ? "مدل تحلیلی" : "مدل سبک"} ساخته شد.`}
            {status ? ` سهم امروز: ${fa(status.used)} از ${fa(status.cap)} پرسش.` : ""}
          </p>
        )}

        {status?.note_fa && <p className="text-center text-[11px] text-ink-faint">{status.note_fa}</p>}
      </div>
    </AppShell>
  );
}
