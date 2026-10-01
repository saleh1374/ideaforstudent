"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, SearchInput, Select } from "@/components/ui/forms";
import { SkeletonCard } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconBriefcase,
  IconChat,
  IconHome,
  IconPlus,
  IconSearch,
  IconSend,
  IconShield,
  IconUsers,
} from "@/components/ui/icons";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ headline: "", subjects: ["math"], session_price: 300000 });
  const [requestNote, setRequestNote] = useState<Record<number, string>>({});
  const [query, setQuery] = useState("");
  const [subjectFilter, setSubjectFilter] = useState("all");
  const [sending, setSending] = useState(false);

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
    } finally {
      setLoading(false);
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
      toast(e instanceof Error ? e.message : "خطا در بارگذاری پیام‌ها", "error");
    }
  }, []);

  useEffect(() => {
    if (activeGroup !== null) loadMessages(activeGroup);
  }, [activeGroup, loadMessages]);

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/tutor/profile", { method: "POST", json: form });
      toast("نمایه ذخیره شد ✓", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ذخیره نمایه", "error");
    }
  }

  async function requestSession(tutorUserId: number) {
    try {
      await api("/tutor/requests", {
        method: "POST",
        json: { tutor_user_id: tutorUserId, subject: "math", note: requestNote[tutorUserId] || "درخواست جلسه" },
      });
      toast("درخواست جلسه ثبت شد ✓", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ثبت درخواست", "error");
    }
  }

  async function decide(id: number, approve: boolean) {
    try {
      await api(`/tutor/requests/${id}/decide`, { method: "POST", json: { approve } });
      toast(approve ? "درخواست پذیرفته شد." : "درخواست رد شد.", approve ? "success" : "info");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا", "error");
    }
  }

  async function joinGroup(gid: number) {
    try {
      await api(`/tutor/groups/${gid}/join`, { method: "POST" });
      setActiveGroup(gid);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در پیوستن به گروه", "error");
    }
  }

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || activeGroup === null) return;
    setSending(true);
    try {
      const out = await api<{ flagged: boolean }>("/tutor/messages", {
        method: "POST",
        json: { content: input, group_id: activeGroup },
      });
      setInput("");
      if (out.flagged) toast("اطلاعات تماس/پیوند خارجی در پیام شما حذف شد (ایمنی زیر ۱۸).", "warning");
      await loadMessages(activeGroup);
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ارسال پیام", "error");
    } finally {
      setSending(false);
    }
  }

  async function report(id: number) {
    try {
      await api(`/tutor/messages/${id}/report`, { method: "POST", json: { reason: "گزارش کاربر" } });
      toast("گزارش ثبت شد و در لاگ ممیزی ذخیره گردید.", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در گزارش", "error");
    }
  }

  const subjects = useMemo(() => Array.from(new Set(tutors.flatMap((t) => t.subjects))), [tutors]);

  const visibleTutors = useMemo(
    () =>
      tutors.filter(
        (t) =>
          (subjectFilter === "all" || t.subjects.includes(subjectFilter)) &&
          (query.trim() === "" || t.name.includes(query.trim()) || (t.headline ?? "").includes(query.trim()))
      ),
    [tutors, query, subjectFilter]
  );

  const activeGroupInfo = groups.find((g) => g.id === activeGroup);

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="بازار معلم خصوصی"
          description="چت گروهی با فیلتر ایمنی زیر ۱۸ — شماره تماس و پیوند خارجی به‌صورت خودکار حذف می‌شود."
          crumbs={[{ label: "دانشیار" }, { label: "آموزشی" }, { label: "بازار معلم خصوصی" }]}
          badge={
            <Badge tone="success" dot>
              <IconShield size={12} /> ایمنی فعال
            </Badge>
          }
          actions={
            <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
              خانه
            </ButtonLink>
          }
        />

        {error && <Alert variant="danger" title="خطا">{error}</Alert>}

        {loading && (
          <div className="grid gap-4 sm:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {!loading && (
          <>
            {/* ——— market ——— */}
            <Section
              title="معلم‌های فعال"
              subtitle="بر اساس درس، نام یا عنوان نمایه جستجو کن."
              action={
                <Badge tone="primary" className="num">
                  {fa(visibleTutors.length)} معلم
                </Badge>
              }
            >
              <div className="flex flex-col gap-3 sm:flex-row">
                <SearchInput value={query} onChange={setQuery} placeholder="جستجوی معلم یا عنوان…" className="w-full sm:max-w-xs" />
                <Select value={subjectFilter} onChange={(e) => setSubjectFilter(e.target.value)} className="w-full sm:w-44">
                  <option value="all">همه درس‌ها</option>
                  {subjects.map((s) => (
                    <option key={s} value={s}>
                      {SUBJECT_FA[s] ?? s}
                    </option>
                  ))}
                </Select>
              </div>

              {visibleTutors.length === 0 ? (
                <EmptyState
                  icon={<IconSearch size={26} />}
                  title="معلمی با این فیلترها نیست"
                  description="فیلتر را تغییر بده یا صبر کن تا معلم جدیدی نمایه بسازد."
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  {visibleTutors.map((t) => (
                    <Card key={t.profile_id} hover className="space-y-3">
                      <div className="flex items-start gap-3">
                        <Avatar name={t.name} size="md" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-bold text-ink">{t.name}</p>
                          <p className="mt-0.5 line-clamp-2 text-xs leading-6 text-ink-muted">{t.headline ?? "بدون عنوان"}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {t.subjects.map((s) => (
                          <Badge key={s} tone="neutral">
                            {SUBJECT_FA[s] ?? s}
                          </Badge>
                        ))}
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-surface-sunken px-3.5 py-2.5 text-[11px]">
                        <span className="num font-bold text-ink">
                          {t.session_price ? `${fa(t.session_price)} تومان / جلسه` : "قیمت توافقی"}
                        </span>
                        <span className="text-ink-faint">{t.availability ?? "زمان توافقی"}</span>
                      </div>

                      {role === "student" && (
                        <div className="flex gap-2">
                          <Input
                            className="flex-1 py-2 text-xs"
                            placeholder="یادداشت درخواست…"
                            value={requestNote[t.profile_id] ?? ""}
                            onChange={(e) => setRequestNote({ ...requestNote, [t.profile_id]: e.target.value })}
                          />
                          <Button size="sm" onClick={() => requestSession(t.user_id)}>
                            درخواست جلسه
                          </Button>
                        </div>
                      )}
                    </Card>
                  ))}
                </div>
              )}
            </Section>

            {/* ——— requests ——— */}
            <Section title="درخواست‌های جلسه" subtitle="کارتابل درخواست‌های ورودی و خروجی">
              {requests.length === 0 ? (
                <EmptyState compact icon={<IconBriefcase size={24} />} title="درخواستی ثبت نشده" description="درخواست‌های جلسه اینجا نمایش داده می‌شود." />
              ) : (
                <div className="space-y-3">
                  {requests.map((r) => (
                    <Card key={r.id} className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <Avatar name={r.student_name ?? "؟"} size="sm" />
                        <div>
                          <p className="text-sm font-semibold text-ink">
                            {r.student_name} ← {r.tutor_name}
                          </p>
                          <p className="num mt-0.5 text-[11px] text-ink-muted">
                            {SUBJECT_FA[r.subject] ?? r.subject} · {r.note ?? "بدون یادداشت"}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge tone={statusTone(r.status)} dot>
                          {STATUS_FA[r.status] ?? r.status}
                        </Badge>
                        {r.status === "pending" && role === "teacher" && (
                          <>
                            <Button size="sm" variant="success" onClick={() => decide(r.id, true)}>
                              پذیرش
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => decide(r.id, false)}>
                              رد
                            </Button>
                          </>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </Section>

            {/* ——— groups + chat ——— */}
            <Section title="گروه‌های گفت‌وگو" subtitle="گروه‌ها را ببین و وارد گفت‌وگو شو.">
              <div className="grid gap-5 md:grid-cols-2">
                <div className="space-y-3">
                  {groups.length === 0 && (
                    <EmptyState compact icon={<IconUsers size={24} />} title="گروهی ساخته نشده" description="اولین گروه گفت‌وگو را بسازید." />
                  )}
                  {groups.map((g) => (
                    <Card key={g.id} className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                          <IconChat size={17} />
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-ink">{g.title}</p>
                          <p className="text-[11px] text-ink-faint">
                            {g.tutor_name ?? "—"} · {SUBJECT_FA[g.subject] ?? g.subject} · {g.is_open ? "باز" : "بسته"}
                          </p>
                        </div>
                      </div>
                      <Button
                        size="sm"
                        variant={activeGroup === g.id ? "soft" : "ghost"}
                        onClick={() => joinGroup(g.id)}
                      >
                        {activeGroup === g.id ? "باز کردن" : "پیوستن"}
                      </Button>
                    </Card>
                  ))}
                  {role === "teacher" && <CreateGroupButton onCreated={load} />}
                </div>

                {/* chat panel */}
                <Card padded={false} className="flex flex-col overflow-hidden">
                  <div className="flex items-center justify-between border-b border-line bg-surface-sunken px-4 py-3">
                    <p className="text-xs font-bold text-ink">
                      گفت‌وگو{activeGroup !== null ? ` — ${activeGroupInfo?.title ?? `گروه #${fa(activeGroup)}`}` : ""}
                    </p>
                    {activeGroup !== null && <Badge tone="primary" dot>فعال</Badge>}
                  </div>

                  {activeGroup === null ? (
                    <div className="p-4">
                      <EmptyState compact icon={<IconChat size={24} />} title="برای شروع به یک گروه بپیوندید" description="از فهرست کناری، گروه را انتخاب کنید." />
                    </div>
                  ) : (
                    <>
                      <div className="max-h-[24rem] flex-1 space-y-3 overflow-y-auto px-4 py-4">
                        {messages.length === 0 && (
                          <p className="text-center text-xs text-ink-faint">هنوز پیامی در این گروه نیست — اولین پیام را بنویسید.</p>
                        )}
                        {messages.map((m) => (
                          <div key={m.id} className="rounded-xl bg-surface-sunken p-3">
                            <div className="flex items-center justify-between text-[11px]">
                              <span className="font-semibold text-ink-muted">{m.sender ?? "کاربر"}</span>
                              <button
                                className="text-ink-faint transition hover:text-danger-600"
                                onClick={() => report(m.id)}
                                title="گزارش پیام"
                              >
                                گزارش
                              </button>
                            </div>
                            <p className="mt-1 text-sm leading-7 text-ink">
                              {m.content}
                              {m.flagged && (
                                <Badge tone="warning" className="mr-2">
                                  فیلتر شده
                                </Badge>
                              )}
                            </p>
                          </div>
                        ))}
                      </div>
                      <form onSubmit={sendMessage} className="flex gap-2 border-t border-line px-4 py-3">
                        <Input
                          className="flex-1"
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          placeholder="پیام…"
                        />
                        <Button type="submit" size="sm" loading={sending} icon={<IconSend size={14} />}>
                          ارسال
                        </Button>
                      </form>
                    </>
                  )}
                </Card>
              </div>
            </Section>

            {/* ——— profile (teacher) ——— */}
            {role === "teacher" && (
              <Card>
                <CardHeader title="نمایه من (بازار)" subtitle="عنوان، قیمت و درس‌های خود را برای دانش‌آموزان تنظیم کنید." icon={<IconBriefcase size={17} />} />
                <form onSubmit={saveProfile} className="grid gap-3 sm:grid-cols-2">
                  <Field label="عنوان نمایه">
                    <Input placeholder="عنوان نمایه" value={form.headline} onChange={(e) => setForm({ ...form, headline: e.target.value })} />
                  </Field>
                  <Field label="قیمت هر جلسه (تومان)">
                    <Input
                      type="number"
                      placeholder="قیمت هر جلسه"
                      value={form.session_price}
                      onChange={(e) => setForm({ ...form, session_price: Number(e.target.value) })}
                    />
                  </Field>
                  <div className="sm:col-span-2">
                    <Button type="submit" icon={<IconPlus size={15} />}>
                      ذخیره نمایه
                    </Button>
                  </div>
                </form>
              </Card>
            )}
          </>
        )}
      </div>
    </AppShell>
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
      toast("گروه ساخته شد ✓", "success");
      onCreated();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ساخت گروه", "error");
    }
  }
  return (
    <form onSubmit={create} className="flex gap-2">
      <Input className="flex-1 text-sm" placeholder="عنوان گروه جدید" value={title} onChange={(e) => setTitle(e.target.value)} />
      <Button type="submit" variant="ghost" size="sm" icon={<IconPlus size={14} />}>
        ساخت گروه
      </Button>
    </form>
  );
}
