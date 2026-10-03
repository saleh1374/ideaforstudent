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
  verified?: boolean;
  rating_avg?: number | null;
  rating_count?: number;
  match_score?: number | null;
};

type Req = {
  id: number;
  student_name: string | null;
  tutor_name: string | null;
  subject: string;
  note: string | null;
  status: string;
  state?: string;
  state_fa?: string;
  hours_left?: number;
  expires_at?: string | null;
  consent_status?: string | null;
};

type Group = { id: number; title: string; subject: string; tutor_name: string | null; is_open: boolean };

type Msg = { id: number; sender: string | null; content: string; flagged: boolean };

type Session = {
  id: number;
  topic: string;
  starts_at: string;
  duration_min: number;
  join_link: string | null;
  status: string;
  tutor_name: string | null;
  student_name: string | null;
  attended: boolean;
  tutor_confirmed: boolean;
  lesson_note: string | null;
  homework: string | null;
  rating: number | null;
  rating_avg: number | null;
};

type Consent = {
  request_id: number;
  tutor_name: string | null;
  student_name: string | null;
  subject: string;
  note: string | null;
  status: string;
};

type Verification = {
  status: string;
  status_fa?: string;
  review_note?: string | null;
  missing_fa?: string[];
  degree?: string | null;
  university?: string | null;
  experience_years?: number | null;
};

const STATUS_FA: Record<string, string> = {
  pending: "در انتظار پاسخ",
  accepted: "پذیرفته‌شده",
  rejected: "ردشده",
  awaiting_parent: "در انتظار تأیید والد",
  expired: "منقضی شده",
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
  const [sessions, setSessions] = useState<Session[]>([]);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [verifQueue, setVerifQueue] = useState<
    { id: number; tutor_name: string | null; degree: string | null; status: string; experience_years: number | null }[]
  >([]);
  const [activeGroup, setActiveGroup] = useState<number | null>(null);
  const [activeRequest, setActiveRequest] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ headline: "", subjects: ["math"], session_price: 300000 });
  const [verifForm, setVerifForm] = useState({
    full_name: "",
    national_id: "",
    degree: "",
    university: "",
    experience_years: 0,
    intro: "",
  });
  const [sessionForm, setSessionForm] = useState({
    topic: "",
    starts_at: "",
    duration_min: 60,
    join_link: "",
    student_user_id: 0,
  });
  const [inviteCode, setInviteCode] = useState<Record<number, string>>({});
  const [joinCode, setJoinCode] = useState("");
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
      const me = await api<{ role: string; id: number }>("/auth/me");
      setRole(me.role);
      const [t, r, g, s] = await Promise.all([
        api<{ tutors: Tutor[] }>("/tutor/market"),
        api<{ requests: Req[] }>("/tutor/requests"),
        api<{ groups: Group[] }>("/tutor/groups"),
        api<{ sessions: Session[] }>("/tutor/sessions"),
      ]);
      setTutors(t.tutors);
      setRequests(r.requests);
      setGroups(g.groups);
      setSessions(s.sessions);

      // داده‌های نقش‌محور: رضایت والد، فرم صالحیت، صف بررسی
      if (me.role === "parent") {
        try {
          const c = await api<{ consents: Consent[] }>("/tutor/consents");
          setConsents(c.consents);
        } catch {
          setConsents([]);
        }
      }
      if (me.role === "teacher") {
        try {
          const v = await api<Verification>("/tutor/verification");
          setVerification(v);
        } catch {
          setVerification(null);
        }
      }
      if (["ministry", "province_admin", "district_admin", "platform_admin"].includes(me.role)) {
        try {
          const q = await api<{ verifications: typeof verifQueue }>("/tutor/verifications/pending");
          setVerifQueue(q.verifications);
        } catch {
          setVerifQueue([]);
        }
      }
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

  const loadRequestMessages = useCallback(async (rid: number) => {
    try {
      const d = await api<{ messages: Msg[] }>(`/tutor/requests/${rid}/messages`);
      setMessages(d.messages);
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در بارگذاری پیام‌ها", "error");
    }
  }, []);

  useEffect(() => {
    if (activeGroup !== null) loadMessages(activeGroup);
  }, [activeGroup, loadMessages]);

  useEffect(() => {
    if (activeRequest !== null) loadRequestMessages(activeRequest);
  }, [activeRequest, loadRequestMessages]);

  /** باز کردن چتِ یک درخواست پذیرفته‌شده (پنل گفت‌وگو را روی همان درخواست می‌اندازد) */
  function openRequestChat(rid: number) {
    setActiveGroup(null);
    setActiveRequest(rid);
  }

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
      setActiveRequest(null);
      setActiveGroup(gid);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در پیوستن به گروه", "error");
    }
  }

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || (activeGroup === null && activeRequest === null)) return;
    setSending(true);
    try {
      const out = await api<{ flagged: boolean }>("/tutor/messages", {
        method: "POST",
        json: {
          content: input,
          group_id: activeGroup,
          request_id: activeGroup === null ? activeRequest : null,
        },
      });
      setInput("");
      if (out.flagged) toast("اطلاعات تماس/پیوند خارجی در پیام شما حذف شد (ایمنی زیر ۱۸).", "warning");
      if (activeGroup !== null) await loadMessages(activeGroup);
      else if (activeRequest !== null) await loadRequestMessages(activeRequest);
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

  // ---------------- §10.2: صالحیت، رضایت والد، جلسه، دعوت ----------------

  async function submitVerification(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/tutor/verification", { method: "POST", json: verifForm });
      toast("فرم صالحیت برای بررسی ارسال شد ✓", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ارسال فرم", "error");
    }
  }

  async function decideVerification(id: number, decision: string) {
    try {
      await api(`/tutor/verifications/${id}/decide`, { method: "POST", json: { decision } });
      toast("نتیجه بررسی ثبت شد.", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا", "error");
    }
  }

  async function decideConsent(requestId: number, approve: boolean) {
    try {
      await api(`/tutor/requests/${requestId}/consent`, { method: "POST", json: { approve } });
      toast(approve ? "رضایت شما ثبت شد ✓" : "درخواست رد شد.", approve ? "success" : "info");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا", "error");
    }
  }

  async function createSession(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/tutor/sessions", {
        method: "POST",
        json: {
          ...sessionForm,
          join_link: sessionForm.join_link || null,
          student_user_id: sessionForm.student_user_id || null,
        },
      });
      toast("کارت جلسه ثبت شد ✓", "success");
      setSessionForm({ topic: "", starts_at: "", duration_min: 60, join_link: "", student_user_id: 0 });
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ثبت جلسه", "error");
    }
  }

  async function sessionAction(id: number, action: "attend" | "confirm", json?: object) {
    try {
      await api(`/tutor/sessions/${id}/${action}`, { method: "POST", json });
      toast(action === "attend" ? "حضور شما ثبت شد ✓" : "جلسه تأیید شد ✓", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا", "error");
    }
  }

  async function rateSession(id: number, rating: number) {
    try {
      await api(`/tutor/sessions/${id}/feedback`, { method: "POST", json: { rating } });
      toast("امتیاز شما ثبت شد ✓", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا", "error");
    }
  }

  async function makeInvite(groupId: number) {
    try {
      const out = await api<{ code: string }>(`/tutor/groups/${groupId}/invites`, { method: "POST" });
      setInviteCode({ ...inviteCode, [groupId]: out.code });
      toast(`کد دعوت: ${out.code}`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ساخت کد", "error");
    }
  }

  async function joinByInvite() {
    if (!joinCode.trim()) return;
    try {
      await api("/tutor/invites/join", { method: "POST", json: { code: joinCode.trim() } });
      setJoinCode("");
      toast("به گروه پیوستید ✓", "success");
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "کد دعوت معتبر نیست", "error");
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
                          <p className="flex items-center gap-1.5 text-sm font-bold text-ink">
                            {t.name}
                            {t.verified && (
                              <Badge tone="success" dot>
                                <IconShield size={11} /> تأییدشده
                              </Badge>
                            )}
                          </p>
                          <p className="mt-0.5 line-clamp-2 text-xs leading-6 text-ink-muted">{t.headline ?? "بدون عنوان"}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {t.subjects.map((s) => (
                          <Badge key={s} tone="neutral">
                            {SUBJECT_FA[s] ?? s}
                          </Badge>
                        ))}
                        {t.match_score != null && (
                          <Badge tone="primary" className="num">
                            تناسب {fa(Math.round(t.match_score * 100))}٪
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-surface-sunken px-3.5 py-2.5 text-[11px]">
                        <span className="num font-bold text-ink">
                          {t.session_price ? `${fa(t.session_price)} تومان / جلسه` : "قیمت توافقی"}
                        </span>
                        <span className="text-ink-faint">
                          {t.rating_avg != null ? `★ ${fa(t.rating_avg)} از ${fa(t.rating_count ?? 0)} نظر` : (t.availability ?? "زمان توافقی")}
                        </span>
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
                          {r.state === "expired" && (
                            <p className="mt-0.5 text-[11px] font-semibold text-danger-600">
                              مهلت ۷۲ ساعته پاسخ معلم گذشته است.
                            </p>
                          )}
                          {r.state === "awaiting_parent" && (
                            <p className="mt-0.5 text-[11px] font-semibold text-warning-600">
                              در انتظار تأیید والد — هنوز برای معلم نمایش داده نشده است.
                            </p>
                          )}
                          {r.status === "pending" && r.state !== "expired" && r.hours_left != null && r.hours_left > 0 && (
                            <p className="num mt-0.5 text-[11px] text-ink-faint">
                              {fa(r.hours_left)} ساعت تا انقضا
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge tone={r.state === "expired" ? "danger" : statusTone(r.status)} dot>
                          {r.state_fa ?? STATUS_FA[r.status] ?? r.status}
                        </Badge>
                        {r.status === "pending" && r.state !== "expired" && role === "teacher" && (
                          <>
                            <Button size="sm" variant="success" onClick={() => decide(r.id, true)}>
                              پذیرش
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => decide(r.id, false)}>
                              رد
                            </Button>
                          </>
                        )}
                        {r.status === "accepted" && (
                          <Button
                            size="sm"
                            variant={activeRequest === r.id ? "soft" : "ghost"}
                            icon={<IconChat size={14} />}
                            onClick={() => openRequestChat(r.id)}
                          >
                            {activeRequest === r.id ? "گفت‌وگوی باز" : "گفت‌وگو"}
                          </Button>
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
                      گفت‌وگو
                      {activeGroup !== null
                        ? ` — ${activeGroupInfo?.title ?? `گروه #${fa(activeGroup)}`}`
                        : activeRequest !== null
                          ? ` — درخواست جلسه #${fa(activeRequest)}`
                          : ""}
                    </p>
                    {(activeGroup !== null || activeRequest !== null) && <Badge tone="primary" dot>فعال</Badge>}
                  </div>

                  {activeGroup === null && activeRequest === null ? (
                    <div className="p-4">
                      <EmptyState compact icon={<IconChat size={24} />} title="برای شروع به یک گروه بپیوندید" description="از فهرست کناری، گروه را انتخاب کنید یا روی درخواست پذیرفته‌شده «گفت‌وگو» بزنید." />
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

            {/* ——— رضایت والد (§10.2-۵) ——— */}
            {role === "parent" && (
              <Section
                title="رضایت برای کلاس خصوصی فرزند"
                subtitle="تا شما تأیید نکنید، درخواست دانش‌آموز برای معلم خصوصی ارسال نمی‌شود."
                action={<Badge tone="primary" className="num">{fa(consents.length)} در انتظار</Badge>}
              >
                {consents.length === 0 ? (
                  <EmptyState compact icon={<IconShield size={24} />} title="درخواستی در انتظار شما نیست" description="درخواست‌های جدید کلاس خصوصی فرزندتان اینجا ظاهر می‌شود." />
                ) : (
                  <div className="space-y-3">
                    {consents.map((c) => (
                      <Card key={c.request_id} className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-ink">
                            {c.student_name} ← {c.tutor_name}
                          </p>
                          <p className="mt-0.5 text-[11px] text-ink-muted">
                            {SUBJECT_FA[c.subject] ?? c.subject} · {c.note ?? "بدون یادداشت"}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" variant="success" onClick={() => decideConsent(c.request_id, true)}>
                            تأیید
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => decideConsent(c.request_id, false)}>
                            رد
                          </Button>
                        </div>
                      </Card>
                    ))}
                  </div>
                )}
              </Section>
            )}

            {/* ——— کارت جلسه‌ها (§10.2-۸/۹) ——— */}
            <Section
              title="جلسه‌های من"
              subtitle="کارت جلسه: لینک کلاس، حضور دانش‌آموز، تأیید معلم و امتیاز پایان جلسه."
              action={<Badge tone="primary" className="num">{fa(sessions.length)} جلسه</Badge>}
            >
              {sessions.length === 0 ? (
                <EmptyState compact icon={<IconBriefcase size={24} />} title="جلسه‌ای ثبت نشده" description="پس از پذیرش درخواست، معلم کارت جلسه ثبت می‌کند." />
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  {sessions.map((s) => (
                    <Card key={s.id} className="space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-sm font-bold text-ink">{s.topic}</p>
                          <p className="num mt-0.5 text-[11px] text-ink-muted">
                            {s.starts_at?.slice(0, 16).replace("T", " ")} · {fa(s.duration_min)} دقیقه
                          </p>
                          <p className="mt-0.5 text-[11px] text-ink-faint">
                            {s.tutor_name} ← {s.student_name}
                          </p>
                        </div>
                        <Badge tone={s.tutor_confirmed ? "success" : s.attended ? "primary" : "neutral"} dot>
                          {s.status === "completed" ? "کامل‌شده" : s.attended ? "حضور ثبت شد" : "برگزار نشده"}
                        </Badge>
                      </div>

                      {s.join_link && (
                        <a href={s.join_link} target="_blank" rel="noreferrer" className="block truncate rounded-xl bg-surface-sunken px-3 py-2 text-[11px] font-semibold text-primary-600 hover:underline">
                          {s.join_link}
                        </a>
                      )}

                      {s.homework && (
                        <p className="rounded-xl bg-warning-50 px-3 py-2 text-[11px] leading-6 text-ink">
                          <b>تکلیف:</b> {s.homework}
                        </p>
                      )}

                      <div className="flex flex-wrap items-center gap-2">
                        {role === "student" && !s.attended && (
                          <Button size="sm" variant="soft" onClick={() => sessionAction(s.id, "attend")}>
                            ورود به کلاس
                          </Button>
                        )}
                        {role === "teacher" && s.attended && !s.tutor_confirmed && (
                          <Button size="sm" variant="success" onClick={() => sessionAction(s.id, "confirm")}>
                            تأیید حضور و پایان جلسه
                          </Button>
                        )}
                        {role === "teacher" && !s.tutor_confirmed && <SessionNoteButton sessionId={s.id} onSaved={load} />}
                        {(role === "student" || role === "parent") && s.tutor_confirmed && (
                          <div className="flex items-center gap-1">
                            <span className="ml-1 text-[11px] text-ink-faint">امتیاز شما:</span>
                            {[1, 2, 3, 4, 5].map((n) => (
                              <button
                                key={n}
                                onClick={() => rateSession(s.id, n)}
                                className={`num h-7 w-7 rounded-lg text-xs font-bold transition ${
                                  s.rating === n ? "bg-warning-500 text-white" : "bg-surface-sunken text-ink-muted hover:bg-surface"
                                }`}
                                title={`${n} از ۵`}
                              >
                                {n}
                              </button>
                            ))}
                          </div>
                        )}
                        {s.rating_avg != null && (
                          <Badge tone="warning" className="num">★ {fa(s.rating_avg)}</Badge>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </Section>

            {/* ——— فرم کارت جلسه (معلم) ——— */}
            {role === "teacher" && (
              <Card>
                <CardHeader title="ثبت کارت جلسه" subtitle="تاریخ، موضوع و لینک کلاس آنلاین (Meet/Zoom/Teams) را وارد کنید." icon={<IconPlus size={17} />} />
                <form onSubmit={createSession} className="grid gap-3 sm:grid-cols-2">
                  <Field label="موضوع جلسه">
                    <Input placeholder="مثلاً فصل ۳ — مشتق" value={sessionForm.topic} onChange={(e) => setSessionForm({ ...sessionForm, topic: e.target.value })} required />
                  </Field>
                  <Field label="زمان شروع">
                    <Input type="datetime-local" value={sessionForm.starts_at} onChange={(e) => setSessionForm({ ...sessionForm, starts_at: e.target.value })} required />
                  </Field>
                  <Field label="مدت (دقیقه)">
                    <Input type="number" value={sessionForm.duration_min} onChange={(e) => setSessionForm({ ...sessionForm, duration_min: Number(e.target.value) })} />
                  </Field>
                  <Field label="لینک کلاس آنلاین">
                    <Input placeholder="https://meet.google.com/…" value={sessionForm.join_link} onChange={(e) => setSessionForm({ ...sessionForm, join_link: e.target.value })} />
                  </Field>
                  <div className="sm:col-span-2">
                    <Button type="submit" icon={<IconPlus size={15} />}>
                      ثبت کارت جلسه
                    </Button>
                  </div>
                </form>
              </Card>
            )}

            {/* ——— کد دعوت (§10.2-۵) ——— */}
            <Section title="کد دعوت امن به گروه" subtitle="عضویت فقط با کد دعوت — بدون جست‌وجوی کد ملی و بدون افشای نتیجه جست‌وجو.">
              <div className="grid gap-5 md:grid-cols-2">
                <div className="space-y-3">
                  {role === "teacher" &&
                    groups.map((g) => (
                      <Card key={g.id} className="flex items-center justify-between gap-3">
                        <p className="truncate text-sm font-semibold text-ink">{g.title}</p>
                        {inviteCode[g.id] ? (
                          <span className="num rounded-xl bg-surface-sunken px-3 py-1.5 text-sm font-bold tracking-widest text-primary-600">
                            {inviteCode[g.id]}
                          </span>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={() => makeInvite(g.id)}>
                            ساخت کد
                          </Button>
                        )}
                      </Card>
                    ))}
                  {role !== "teacher" && (
                    <p className="text-xs leading-6 text-ink-muted">
                      معلم گروه، کد شش‌حرفی می‌سازد و در اختیار شما می‌گذارد؛ با همین کد به گروه می‌پیوندید.
                    </p>
                  )}
                </div>
                <Card>
                  <CardHeader title="پیوستن با کد دعوت" subtitle="کد را وارد کنید و به گروه کلاس بپیوندید." icon={<IconUsers size={17} />} />
                  <div className="flex gap-2">
                    <Input className="flex-1 num tracking-widest" placeholder="کد شش‌حرفی" value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())} />
                    <Button onClick={joinByInvite} disabled={joinCode.trim().length < 4}>
                      پیوستن
                    </Button>
                  </div>
                </Card>
              </div>
            </Section>

            {/* ——— فرم صالحیت معلم خصوصی (§10.2-۲) ——— */}
            {role === "teacher" && (
              <Card>
                <CardHeader
                  title="تأیید صالحیت (معلم خصوصی)"
                  subtitle="مدرک، سوابق و معرفی‌نامه بررسی می‌شود؛ بدون تأیید، دانش‌آموز نمی‌تواند درخواست دهد."
                  icon={<IconShield size={17} />}
                />
                {verification && verification.status !== "none" && (
                  <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-surface-sunken px-3.5 py-2.5">
                    <Badge tone={verification.status === "verified" ? "success" : verification.status === "rejected" ? "danger" : "primary"} dot>
                      {verification.status_fa}
                    </Badge>
                    {verification.review_note && <span className="text-[11px] text-ink-muted">{verification.review_note}</span>}
                    {verification.missing_fa && verification.missing_fa.length > 0 && (
                      <span className="text-[11px] font-semibold text-danger-600">
                        ناقص: {verification.missing_fa.join("، ")}
                      </span>
                    )}
                  </div>
                )}
                {!verification || !["verified", "in_review", "submitted"].includes(verification.status) ? (
                  <form onSubmit={submitVerification} className="grid gap-3 sm:grid-cols-2">
                    <Field label="نام و نام خانوادگی">
                      <Input value={verifForm.full_name} onChange={(e) => setVerifForm({ ...verifForm, full_name: e.target.value })} required />
                    </Field>
                    <Field label="کد ملی (فقط هش ذخیره می‌شود)">
                      <Input value={verifForm.national_id} onChange={(e) => setVerifForm({ ...verifForm, national_id: e.target.value })} required />
                    </Field>
                    <Field label="مدرک و رشته">
                      <Input value={verifForm.degree} onChange={(e) => setVerifForm({ ...verifForm, degree: e.target.value })} required />
                    </Field>
                    <Field label="دانشگاه">
                      <Input value={verifForm.university} onChange={(e) => setVerifForm({ ...verifForm, university: e.target.value })} />
                    </Field>
                    <Field label="سوابق تدریس (سال)">
                      <Input type="number" value={verifForm.experience_years} onChange={(e) => setVerifForm({ ...verifForm, experience_years: Number(e.target.value) })} />
                    </Field>
                    <div className="sm:col-span-2">
                      <Field label="معرفی‌نامه">
                        <textarea
                          className="w-full rounded-xl border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-primary-400"
                          rows={3}
                          value={verifForm.intro}
                          onChange={(e) => setVerifForm({ ...verifForm, intro: e.target.value })}
                          required
                        />
                      </Field>
                    </div>
                    <div className="sm:col-span-2">
                      <Button type="submit" icon={<IconShield size={15} />}>
                        ارسال برای بررسی
                      </Button>
                    </div>
                  </form>
                ) : (
                  <p className="text-xs leading-6 text-ink-muted">
                    فرم شما برای بررسی ارسال شده است؛ نتیجه از همین‌جا اطلاع داده می‌شود.
                  </p>
                )}
              </Card>
            )}

            {/* ——— صف بررسی صالحیت (نظارتی) ——— */}
            {verifQueue.length > 0 && (
              <Section title="صف بررسی مدارک معلمان خصوصی" subtitle="تأیید، رد یا درخواست تکمیل مدارک.">
                <div className="space-y-3">
                  {verifQueue.map((v) => (
                    <Card key={v.id} className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-ink">{v.tutor_name ?? "—"}</p>
                        <p className="mt-0.5 text-[11px] text-ink-muted">
                          {v.degree ?? "بدون مدرک"} · {fa(v.experience_years ?? 0)} سال سابقه
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="success" onClick={() => decideVerification(v.id, "verified")}>
                          تأیید
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => decideVerification(v.id, "needs_completion")}>
                          تکمیل مدارک
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => decideVerification(v.id, "rejected")}>
                          رد
                        </Button>
                      </div>
                    </Card>
                  ))}
                </div>
              </Section>
            )}

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

function SessionNoteButton({ sessionId, onSaved }: { sessionId: number; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [homework, setHomework] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api(`/tutor/sessions/${sessionId}/note`, { method: "POST", json: { note, homework } });
      toast("یادداشت و تکلیف ذخیره شد ✓", "success");
      setOpen(false);
      setNote("");
      setHomework("");
      onSaved();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ذخیره یادداشت", "error");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        یادداشت و تکلیف
      </Button>
    );
  }
  return (
    <form onSubmit={save} className="w-full space-y-2 rounded-xl bg-surface-sunken p-3">
      <Field label="یادداشت جلسه">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="چه گذشت؟" />
      </Field>
      <Field label="تکلیف">
        <Input value={homework} onChange={(e) => setHomework(e.target.value)} placeholder="تمرین صفحه…" />
      </Field>
      <div className="flex gap-2">
        <Button type="submit" size="sm" loading={saving}>
          ذخیره
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          انصراف
        </Button>
      </div>
    </form>
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
