"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";

type Tutor = {
  profile_id: number;
  user_id: number;
  name: string;
  headline: string | null;
  subjects: string[];
  session_price: number | null;
  availability: string | null;
};

type Req = {
  id: number;
  student_name: string | null;
  tutor_name: string | null;
  subject: string;
  note: string | null;
  status: string;
};

type Group = { id: number; title: string; subject: string; tutor_name: string | null; is_open: boolean };

type Msg = { id: number; sender: string | null; content: string; flagged: boolean };

const STATUS_FA: Record<string, string> = {
  pending: "در انتظار پاسخ",
  accepted: "پذیرفته‌شده",
  rejected: "ردشده",
};

const SUBJECT_FA: Record<string, string> = {
  math: "ریاضی",
  physics: "فیزیک",
  chemistry: "شیمی",
};

export default function TutorPage() {
  const [role, setRole] = useState("");
  const [tutors, setTutors] = useState<Tutor[]>([]);
  const [requests, setRequests] = useState<Req[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [activeGroup, setActiveGroup] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({ headline: "", subjects: ["math"], session_price: 300000 });
  const [requestNote, setRequestNote] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);
      const [t, r, g] = await Promise.all([
        api<{ tutors: Tutor[] }>("/tutor/market"),
        api<{ requests: Req[] }>("/tutor/requests"),
        api<{ groups: Group[] }>("/tutor/groups"),
      ]);
      setTutors(t.tutors);
      setRequests(r.requests);
      setGroups(g.groups);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadMessages = useCallback(async (gid: number) => {
    try {
      const d = await api<{ messages: Msg[] }>(`/tutor/groups/${gid}/messages`);
      setMessages(d.messages);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    }
  }, []);

  useEffect(() => {
    if (activeGroup !== null) loadMessages(activeGroup);
  }, [activeGroup, loadMessages]);

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api("/tutor/profile", { method: "POST", json: form });
      setMsg("✓ نمایه ذخیره شد.");
      await load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "خطا");
    }
  }

  async function requestSession(tutorUserId: number) {
    setMsg("");
    try {
      await api("/tutor/requests", {
        method: "POST",
        json: { tutor_user_id: tutorUserId, subject: "math", note: requestNote[tutorUserId] || "درخواست جلسه" },
      });
      setMsg("✓ درخواست جلسه ثبت شد.");
      await load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "خطا");
    }
  }

  async function decide(id: number, approve: boolean) {
    setMsg("");
    try {
      await api(`/tutor/requests/${id}/decide`, { method: "POST", json: { approve } });
      await load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "خطا");
    }
  }

  async function joinGroup(gid: number) {
    setMsg("");
    try {
      await api(`/tutor/groups/${gid}/join`, { method: "POST" });
      setActiveGroup(gid);
      await load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "خطا");
    }
  }

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || activeGroup === null) return;
    setMsg("");
    try {
      const out = await api<{ flagged: boolean }>("/tutor/messages", {
        method: "POST",
        json: { content: input, group_id: activeGroup },
      });
      setInput("");
      if (out.flagged) setMsg("⚠️ اطلاعات تماس/پیوند خارجی در پیام شما حذف شد (ایمنی زیر ۱۸).");
      await loadMessages(activeGroup);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "خطا");
    }
  }

  async function report(id: number) {
    setMsg("");
    try {
      await api(`/tutor/messages/${id}/report`, { method: "POST", json: { reason: "گزارش کاربر" } });
      setMsg("✓ گزارش ثبت شد و برای نظارت در لاگ ممیزی ذخیره گردید.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "خطا");
    }
  }

  if (error) return <main className="p-6 text-red-600">{error}</main>;

  return (
    <main className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">بازار معلم خصوصی</h1>
          <p className="text-xs text-slate-400 mt-1">چت گروهی با فیلتر ایمنی زیر ۱۸ — شماره تماس و پیوند خارجی حذف می‌شود.</p>
        </div>
        <a href="/student" className="btn-ghost text-xs">
          بازگشت
        </a>
      </header>

      {msg && <div className="card border-primary-200 bg-primary-50 text-sm text-primary-700">{msg}</div>}

      {/* بازار معلم‌ها */}
      <section className="space-y-3">
        <h2 className="font-semibold">معلم‌های فعال</h2>
        {tutors.length === 0 && <div className="card text-sm text-slate-400">معلمی نمایه نساخته است.</div>}
        <div className="grid sm:grid-cols-2 gap-3">
          {tutors.map((t) => (
            <div key={t.profile_id} className="card space-y-2">
              <p className="font-medium">{t.name}</p>
              <p className="text-sm text-slate-600">{t.headline}</p>
              <div className="flex flex-wrap gap-1">
                {t.subjects.map((s) => (
                  <span key={s} className="badge bg-slate-100 text-slate-600">
                    {SUBJECT_FA[s] ?? s}
                  </span>
                ))}
              </div>
              <p className="text-xs text-slate-500">
                {t.session_price ? `${fa(t.session_price)} تومان / جلسه` : "قیمت توافقی"} · {t.availability ?? "زمان توافقی"}
              </p>
              {role === "student" && (
                <div className="flex gap-2">
                  <input
                    className="input flex-1 text-xs"
                    placeholder="یادداشت درخواست…"
                    value={requestNote[t.profile_id] ?? ""}
                    onChange={(e) => setRequestNote({ ...requestNote, [t.profile_id]: e.target.value })}
                  />
                  <button className="btn-primary text-xs" onClick={() => requestSession(t.user_id)}>
                    درخواست جلسه
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* کارتابل درخواست‌ها */}
      <section className="space-y-3">
        <h2 className="font-semibold">درخواست‌های جلسه</h2>
        {requests.length === 0 && <div className="card text-sm text-slate-400">درخواستی ثبت نشده.</div>}
        {requests.map((r) => (
          <div key={r.id} className="card flex items-center justify-between">
            <div>
              <p className="font-medium text-sm">
                {r.student_name} ← {r.tutor_name}
              </p>
              <p className="text-xs text-slate-500 mt-1">
                {SUBJECT_FA[r.subject] ?? r.subject} · {r.note ?? "بدون یادداشت"} · {STATUS_FA[r.status] ?? r.status}
              </p>
            </div>
            {r.status === "pending" && role === "teacher" && (
              <div className="flex gap-2">
                <button className="btn-primary text-xs" onClick={() => decide(r.id, true)}>
                  پذیرش
                </button>
                <button className="btn-ghost text-xs" onClick={() => decide(r.id, false)}>
                  رد
                </button>
              </div>
            )}
          </div>
        ))}
      </section>

      {/* گروه‌ها و چت */}
      <section className="grid md:grid-cols-2 gap-4">
        <div className="space-y-3">
          <h2 className="font-semibold">گروه‌های گفت‌وگو</h2>
          {groups.map((g) => (
            <div key={g.id} className="card flex items-center justify-between">
              <div>
                <p className="font-medium text-sm">{g.title}</p>
                <p className="text-xs text-slate-500">
                  {g.tutor_name} · {SUBJECT_FA[g.subject] ?? g.subject}
                </p>
              </div>
              <button className="btn-ghost text-xs" onClick={() => joinGroup(g.id)}>
                {activeGroup === g.id ? "باز کردن" : "پیوستن"}
              </button>
            </div>
          ))}
          {role === "teacher" && <CreateGroupButton onCreated={load} />}
        </div>

        <div className="card space-y-3">
          <h2 className="font-semibold text-sm">گفت‌وگو{activeGroup !== null ? " — گروه #" + fa(activeGroup) : ""}</h2>
          {activeGroup === null ? (
            <p className="text-sm text-slate-400">برای شروع، به یک گروه بپیوندید.</p>
          ) : (
            <>
              <div className="space-y-2 max-h-72 overflow-y-auto">
                {messages.map((m) => (
                  <div key={m.id} className="text-sm bg-slate-50 rounded-xl p-2">
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span>{m.sender}</span>
                      <button className="text-red-400 hover:text-red-600" onClick={() => report(m.id)}>
                        گزارش
                      </button>
                    </div>
                    <p className="mt-1">
                      {m.content}
                      {m.flagged && <span className="badge bg-amber-100 text-amber-700 mr-2">فیلتر شده</span>}
                    </p>
                  </div>
                ))}
              </div>
              <form onSubmit={sendMessage} className="flex gap-2">
                <input className="input flex-1" value={input} onChange={(e) => setInput(e.target.value)} placeholder="پیام…" />
                <button className="btn-primary text-xs">ارسال</button>
              </form>
            </>
          )}
        </div>
      </section>

      {/* نمایه معلم */}
      {role === "teacher" && (
        <section className="card space-y-3">
          <h2 className="font-semibold">نمایه من (بازار)</h2>
          <form onSubmit={saveProfile} className="grid sm:grid-cols-2 gap-3">
            <input
              className="input"
              placeholder="عنوان نمایه"
              value={form.headline}
              onChange={(e) => setForm({ ...form, headline: e.target.value })}
            />
            <input
              className="input"
              type="number"
              placeholder="قیمت هر جلسه (تومان)"
              value={form.session_price}
              onChange={(e) => setForm({ ...form, session_price: Number(e.target.value) })}
            />
            <button className="btn-primary sm:col-span-2">ذخیره نمایه</button>
          </form>
        </section>
      )}
    </main>
  );
}

function CreateGroupButton({ onCreated }: { onCreated: () => void }) {
  const [title, setTitle] = useState("");
  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      await api("/tutor/groups", { method: "POST", json: { title, subject: "math", is_open: true } });
      setTitle("");
      onCreated();
    } catch {
      /* خطا در پیام والدین */
    }
  }
  return (
    <form onSubmit={create} className="flex gap-2">
      <input className="input flex-1 text-sm" placeholder="عنوان گروه جدید" value={title} onChange={(e) => setTitle(e.target.value)} />
      <button className="btn-ghost text-xs">ساخت گروه</button>
    </form>
  );
}
