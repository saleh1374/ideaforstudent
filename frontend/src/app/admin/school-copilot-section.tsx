"use client";

/** دستیار هوشمند مدیر مدرسه (سند مدیر مدرسه §16 پرسش/پاسخ + §18 پیشنهاد اقدام).

۲ تب داخلی:
- گفت‌وگو: پرسش‌های تحلیلی روی داده تجمیعی همین مدرسه؛ هر پاسخ «منابع» و
  یادداشت «copilot است، نه تصمیم‌گیرنده» دارد.
- پیشنهادهای اقدام: سیستم پیشنهاد می‌سازد؛ فقط با تأیید، ویرایش یا رد مدیر
  «اجرا» می‌شود — هوش مصنوعی تصمیم نمی‌گیرد. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { fa } from "@/lib/labels";
import { Card, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconCheckCircle,
  IconChat,
  IconRefresh,
  IconSend,
  IconSparkles,
  IconX,
} from "@/components/ui/icons";

type Source = { type: string; id: number; title: string };

type ChatTurn = {
  role: "user" | "assistant";
  content: string;
  intent?: string | null;
  sources?: Source[] | null;
};

type ChatReply = {
  conversation_id: number;
  intent: string;
  reply: string;
  sources: Source[];
  note_fa: string;
};

type Suggestion = {
  id: number;
  class_id: number | null;
  subject: string | null;
  title_fa: string;
  evidence_fa: string;
  actions_fa: string[];
  status: string; // proposed | approved | edited | rejected
  final_actions_fa: string[] | null;
  decision_note: string | null;
};

type StatusFilter = "" | "proposed" | "approved" | "edited" | "rejected";

const FILTERS: { key: StatusFilter; label: string }[] = [
  { key: "proposed", label: "در انتظار تصمیم" },
  { key: "approved", label: "تأییدشده" },
  { key: "edited", label: "ویرایش‌شده" },
  { key: "rejected", label: "ردشده" },
  { key: "", label: "همه" },
];

const STATUS_FA: Record<string, string> = {
  proposed: "پیشنهاد شده",
  approved: "تأیید شده",
  edited: "ویرایش شده",
  rejected: "رد شده",
};

/** پرسش‌های نمونه §16 (شکل ۱۳ سند) — هر کدام به یک نیت سرویس می‌رسد. */
const SAMPLE_QUESTIONS = [
  "بزرگ‌ترین مشکل آموزشی مدرسه در دو دوره اخیر چه بوده است؟",
  "کدام کلاس‌ها بیشترین افت را داشته‌اند؟",
  "در پایه دهم ریاضی، مشکل بیشتر از کدام مباحث است؟",
  "کدام دانش‌آموزان بعد از دو بار مداخله هنوز پیشرفت نکرده‌اند؟",
  "کدام کلاس‌ها در یک درس الگوی غیرعادی دارند و نیاز به بررسی دارند؟",
  "برای جلسه شورای آموزشی هفته آینده مهم‌ترین موارد چیست؟",
];

export function SchoolCopilotSection({ schoolId }: { schoolId: number | null }) {
  const [innerTab, setInnerTab] = useState<"chat" | "suggestions">("chat");

  if (schoolId === null) {
    return (
      <Section title="دستیار هوشمند مدیر مدرسه" subtitle="§16 پرسش و پاسخ · §18 پیشنهاد اقدام">
        <Alert variant="warning">پیش از استفاده از دستیار، اطلاعات مدرسه باید بارگذاری شود.</Alert>
      </Section>
    );
  }

  return (
    <Section
      title="دستیار هوشمند مدیر مدرسه"
      subtitle="پاسخ‌ها از داده تجمیعی همین مدرسه ساخته می‌شوند — copilot است، نه تصمیم‌گیرنده."
    >
      <Tabs
        items={[
          { key: "chat", label: "گفت‌وگو" },
          { key: "suggestions", label: "پیشنهادهای اقدام" },
        ]}
        value={innerTab}
        onChange={(k) => setInnerTab(k as "chat" | "suggestions")}
      />
      {innerTab === "chat" ? <ChatPanel schoolId={schoolId} /> : <SuggestionsPanel schoolId={schoolId} />}
    </Section>
  );
}

/* ------------------------- §16 گفت‌وگو ------------------------- */

function ChatPanel({ schoolId }: { schoolId: number }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setInput("");
      setError("");
      setTurns((prev) => [...prev, { role: "user", content: message }]);
      setBusy(true);
      try {
        const res = await api<ChatReply>(`/admin/school/${schoolId}/copilot/chat`, {
          method: "POST",
          json: { message, conversation_id: conversationId },
        });
        setConversationId(res.conversation_id);
        setTurns((prev) => [
          ...prev,
          { role: "assistant", content: res.reply, intent: res.intent, sources: res.sources },
        ]);
      } catch (e) {
        const msg =
          e instanceof ApiError
            ? e.status === 403
              ? e.detail ?? "دسترسی لازم: view_school_analytics"
              : e.message
            : e instanceof Error
              ? e.message
              : "خطا در دریافت پاسخ";
        setError(msg);
        toast(msg, "error");
      } finally {
        setBusy(false);
      }
    },
    [busy, conversationId, schoolId]
  );

  function newConversation() {
    setConversationId(null);
    setTurns([]);
    setError("");
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] leading-6 text-ink-faint">
          پرسش‌ها فقط روی داده همین مدرسه جواب می‌دهند؛ بدون کش سراسری (حریم خصوصی §20).
        </p>
        <Button
          size="sm"
          variant="ghost"
          icon={<IconRefresh size={14} />}
          onClick={newConversation}
          disabled={busy}
        >
          گفت‌وگوی تازه
        </Button>
      </div>

      {/* پرسش‌های نمونه */}
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {SAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => send(q)}
              className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[11px] text-ink-muted transition hover:border-primary-300 hover:text-primary-700"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* پیام‌ها */}
      <div className="max-h-[420px] space-y-3 overflow-y-auto rounded-2xl border border-line bg-surface-sunken p-4">
        {turns.length === 0 && (
          <EmptyState
            compact
            icon={<IconChat size={24} />}
            title="هنوز پرسشی ثبت نشده است"
            description="از پرسش‌های نمونه بالا شروع کنید یا سؤال خودتان را بنویسید."
          />
        )}
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "flex justify-start" : "flex justify-end"}>
            <div
              className={[
                "max-w-[85%] rounded-2xl px-4 py-2.5 text-xs leading-6",
                t.role === "user"
                  ? "bg-primary-600 text-white"
                  : "border border-line bg-surface text-ink shadow-soft",
              ].join(" ")}
            >
              <p className="whitespace-pre-wrap">{t.content}</p>
              {t.role === "assistant" && t.sources && t.sources.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line pt-2">
                  <span className="text-[10px] font-bold text-ink-faint">منابع:</span>
                  {t.sources.map((s, j) => (
                    <Badge key={`${s.type}-${s.id}-${j}`} tone="info">
                      {s.title}
                    </Badge>
                  ))}
                </div>
              )}
              {t.role === "assistant" && t.intent && (
                <p className="mt-1.5 text-[10px] text-ink-faint">نیت تشخیص‌داده‌شده: {t.intent}</p>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <p className="text-center text-[11px] text-ink-faint">در حال جست‌وجوی داده‌های مدرسه…</p>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <Alert variant="danger">{error}</Alert>}

      {/* ورودی */}
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <Field label="پرسش شما" className="flex-1">
          <Textarea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="مثال: کدام مباحث بیشترین دانش‌آموز ضعیف را دارند؟"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
          />
        </Field>
        <Button type="submit" icon={<IconSend size={15} />} loading={busy} disabled={!input.trim()}>
          ارسال
        </Button>
      </form>
    </div>
  );
}

/* ------------------------- §18 پیشنهاد اقدام ------------------------- */

function SuggestionsPanel({ schoolId }: { schoolId: number }) {
  const [filter, setFilter] = useState<StatusFilter>("proposed");
  const [rows, setRows] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  // تصمیم مدیر
  const [editing, setEditing] = useState<Suggestion | null>(null);
  const [editText, setEditText] = useState("");
  const [rejecting, setRejecting] = useState<Suggestion | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [decidingId, setDecidingId] = useState<number | null>(null);

  const load = useCallback(
    async (st: StatusFilter) => {
      setLoading(true);
      setError("");
      try {
        const res = await api<{ suggestions: Suggestion[] }>(
          `/admin/school/${schoolId}/suggestions${st ? `?status=${encodeURIComponent(st)}` : ""}`
        );
        setRows(res.suggestions);
      } catch (e) {
        setRows([]);
        setError(e instanceof Error ? e.message : "خطا در دریافت پیشنهادها");
      } finally {
        setLoading(false);
      }
    },
    [schoolId]
  );

  useEffect(() => {
    load(filter);
  }, [filter, load]);

  async function generate() {
    setGenerating(true);
    try {
      const res = await api<{ created: number }>(`/admin/school/${schoolId}/suggestions/generate`, {
        method: "POST",
      });
      toast(
        res.created > 0
          ? `${fa(res.created)} پیشنهاد جدید از داده‌های مدرسه ساخته شد`
          : "پیشنهاد بازِ تکراری وجود ندارد؛ چیزی دوباره ساخته نشد",
        "success"
      );
      await load(filter);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "خطا در ساخت پیشنهاد";
      toast(msg, "error");
      if (e instanceof ApiError && e.status === 403) setError(msg);
    } finally {
      setGenerating(false);
    }
  }

  async function decide(s: Suggestion, action: "approve" | "reject" | "edit", extra?: { edited_actions?: string[]; note?: string }) {
    setDecidingId(s.id);
    try {
      await api(`/admin/school/${schoolId}/suggestions/${s.id}/decide`, {
        method: "POST",
        json: { action, ...extra },
      });
      toast(
        action === "approve"
          ? "پیشنهاد تأیید شد"
          : action === "reject"
            ? "پیشنهاد رد شد"
            : "پیشنهاد با اقدام‌های شما ویرایش شد",
        action === "reject" ? "info" : "success"
      );
      setEditing(null);
      setRejecting(null);
      setEditText("");
      setRejectNote("");
      await load(filter);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) toast(e.detail ?? "برای این پیشنهاد قبلاً تصمیم گرفته شده است", "error");
        else if (e.status === 403) toast(e.detail ?? "تصمیم‌گیری در حوزه دسترسی شما نیست", "error");
        else toast(e.message || "خطا در ثبت تصمیم", "error");
      } else {
        toast(e instanceof Error ? e.message : "خطا در ثبت تصمیم", "error");
      }
    } finally {
      setDecidingId(null);
    }
  }

  const proposedCount = rows.filter((r) => r.status === "proposed").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] leading-6 text-ink-faint">
          سیستم پیشنهاد می‌سازد؛ فقط با تأیید، ویرایش یا رد شما اجرا می‌شود (§18). هر تصمیم با رویداد ممیزی ثبت
          می‌گردد.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="soft" icon={<IconRefresh size={14} />} loading={loading} onClick={() => load(filter)}>
            تازه‌سازی
          </Button>
          <Button size="sm" icon={<IconSparkles size={14} />} loading={generating} onClick={generate}>
            ساخت پیشنهاد از داده‌ها
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key || "all"}
            type="button"
            onClick={() => setFilter(f.key)}
            className={[
              "rounded-full border px-3.5 py-1.5 text-[11px] font-bold transition",
              filter === f.key
                ? "border-primary-300 bg-primary-50 text-primary-700"
                : "border-line bg-surface text-ink-muted hover:border-primary-300 hover:text-primary-700",
            ].join(" ")}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <Alert variant="danger">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={3} cols={2} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<IconSparkles size={26} />}
          title="پیشنهادی در این وضعیت نیست"
          description="با دکمه «ساخت پیشنهاد از داده‌ها»، پیشنهاد اقدام از پرچم‌های §5 و کلاس‌های دارای افت ساخته می‌شود."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((s) => (
            <Card key={s.id} className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <span className="flex items-center gap-2 text-sm font-bold text-ink">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-50 text-primary-600">
                    <IconSparkles size={16} />
                  </span>
                  {s.title_fa}
                </span>
                <Badge tone={statusTone(s.status)} dot>
                  {STATUS_FA[s.status] ?? s.status}
                </Badge>
              </div>

              <p className="text-xs leading-6 text-ink-muted">{s.evidence_fa}</p>

              <div className="rounded-xl bg-surface-sunken p-3">
                <p className="mb-1.5 text-[11px] font-bold text-ink">
                  {s.status === "proposed" ? "اقدام‌های پیشنهادی" : "اقدام‌های نهایی (با تصمیم شما)"}
                </p>
                <ul className="space-y-1 text-[11px] leading-6">
                  {(s.final_actions_fa ?? s.actions_fa).map((a, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-primary-400" />
                      {a}
                    </li>
                  ))}
                </ul>
              </div>

              {s.status === "proposed" ? (
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    size="sm"
                    variant="success"
                    icon={<IconCheckCircle size={14} />}
                    loading={decidingId === s.id}
                    onClick={() => decide(s, "approve")}
                  >
                    تأیید
                  </Button>
                  <Button
                    size="sm"
                    variant="soft"
                    onClick={() => {
                      setEditing(s);
                      setEditText(s.actions_fa.join("\n"));
                    }}
                  >
                    ویرایش
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<IconX size={14} />}
                    onClick={() => {
                      setRejecting(s);
                      setRejectNote("");
                    }}
                  >
                    رد
                  </Button>
                </div>
              ) : (
                <p className="text-[11px] leading-6 text-ink-faint">
                  {s.decision_note ? `یادداشت شما: ${s.decision_note}` : "با تصمیم شما ثبت شده است."}
                </p>
              )}
            </Card>
          ))}
        </div>
      )}

      {proposedCount > 0 && (
        <Alert variant="info">
          {fa(proposedCount)} پیشنهاد در انتظار تصمیم شماست — تا وقتی تأیید، ویرایش یا رد نشود، اجرا نمی‌شود.
        </Alert>
      )}

      {/* مودال ویرایش اقدام‌ها */}
      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={`ویرایش اقدام‌ها — ${editing?.title_fa ?? ""}`}
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              انصراف
            </Button>
            <Button
              loading={decidingId === editing?.id}
              disabled={!editText.trim()}
              onClick={() => editing && decide(editing, "edit", { edited_actions: editText.split("\n").map((x) => x.trim()).filter(Boolean) })}
            >
              ثبت ویرایش
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert variant="info">هر سطر یک اقدام باشد. نسخه ویرایش‌شده به جای پیشنهاد سیستم اجرا می‌شود.</Alert>
          <Field label="اقدام‌ها (هر سطر یک مورد)" required>
            <Textarea rows={6} value={editText} onChange={(e) => setEditText(e.target.value)} />
          </Field>
        </div>
      </Modal>

      {/* مودال رد */}
      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title={`رد پیشنهاد — ${rejecting?.title_fa ?? ""}`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRejecting(null)}>
              انصراف
            </Button>
            <Button
              variant="danger"
              loading={decidingId === rejecting?.id}
              onClick={() => rejecting && decide(rejecting, "reject", { note: rejectNote.trim() || undefined })}
            >
              رد پیشنهاد
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert variant="warning">
            پیشنهاد رد می‌شود و اجرا نخواهد شد؛ ردیف برای بهبود پیشنهادهای بعدی می‌ماند.
          </Alert>
          <Field label="یادداشت (اختیاری)">
            <Textarea rows={3} value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} placeholder="مثال: برنامه فعلی کافی است" />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
