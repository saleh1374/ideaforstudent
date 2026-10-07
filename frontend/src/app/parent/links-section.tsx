"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { fa, subjectFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Select, Textarea } from "@/components/ui/forms";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonCard, SkeletonText } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import {
  IconCheckCircle,
  IconClock,
  IconFamily,
  IconRefresh,
  IconTarget,
  IconTrend,
} from "@/components/ui/icons";

/**
 * تب «فرزندان و دسترسی‌ها» (سند §17):
 * 1) GET /parent/links + PATCH /parent/links/{link_id}/permissions — سوییچ مجوز هر پیوند
 * 2) GET /parent/children/{id}/subjects و GET /parent/children/{id}/comparisons (§2/§4)
 * 3) GET /parent/children/{id}/attendance (§9) — بدون ساختن داده؛ یادداشت خود سرور نمایش داده می‌شود
 * 4) GET/POST /parent/tutor-satisfaction (§11/§12)
 * هر واکشی مستقل است تا 403 یک بخش، بقیه تب را نیندازد.
 */

type Err = { message: string; denied: boolean };

type LinkRow = {
  link_id: number;
  student_user_id: number;
  student_name: string | null;
  relation: string | null;
  permissions: Record<string, boolean>;
  overridden_keys: string[];
};

type LinksResp = { links: LinkRow[]; permission_keys: Record<string, string> };

type SubjectTopic = {
  topic_id: number;
  title: string;
  mastery: number;
  status: string;
  status_fa: string;
  needs_attention: boolean;
  trend: string;
  trend_delta: number | null;
  trend_fa: string;
  dominant_error_fa: string | null;
  similar_errors: number;
  suggestion_fa: string;
};

type SubjectRow = {
  subject: string | null;
  current_mastery: number | null;
  status: string;
  status_fa: string;
  trend: string;
  trend_delta: number | null;
  trend_fa: string;
  topics_count: number;
  attention_count: number;
  consolidated_count: number;
  dominant_error_fa: string | null;
  suppressed: boolean;
  topics: SubjectTopic[];
};

type SubjectsData = {
  student_id: number;
  subjects: SubjectRow[];
  strengths: { subject: string | null; current_mastery: number | null }[];
  attention_subjects: { subject: string | null; attention_count: number }[];
  thresholds: { mastered: number; consolidating: number; weak: number };
  note_fa: string;
};

type CompareRow = {
  subject: string | null;
  self: { previous: number | null; current: number | null; delta: number | null; note_fa: string };
  period_goal: { goal: number; current: number | null; gap: number | null; note_fa: string };
  class: {
    allowed: boolean;
    class_avg: number | null;
    student: number | null;
    gap: number | null;
    suppressed: boolean;
    reason_fa: string | null;
  };
};

type CompareData = {
  student_id: number;
  min_group: number;
  class_comparison_allowed: boolean;
  comparisons: CompareRow[];
  note_fa: string;
};

type AttendanceDay = { on_date: string; status: string; status_fa: string; note: string | null };

type MeetingRow = {
  id: number;
  kind: string;
  kind_fa: string;
  subject: string | null;
  topic_fa: string | null;
  tutor_name: string | null;
  scheduled_at: string | null;
  duration_min: number | null;
  status: string;
  status_fa: string;
  report_fa: string | null;
  task_fa: string | null;
  task_status_fa: string | null;
  is_past: boolean;
};

type AttendanceData = {
  student_id: number;
  attendance: {
    days: number;
    rate_pct: number | null;
    counts: Record<string, number>;
    absent: number;
    late: number;
    excused: number;
    rows: AttendanceDay[];
  };
  sessions: {
    total: number;
    upcoming: MeetingRow[];
    past: MeetingRow[];
    missed: MeetingRow[];
    pending_tasks: MeetingRow[];
  };
  note_fa: string;
};

type SatisfactionRow = {
  tutor_user_id: number;
  tutor_name: string | null;
  rating: number;
  comment: string | null;
  updated_at: string | null;
};

type ViewKey = "subjects" | "compare" | "attendance";

const TREND_TONE: Record<string, Tone> = { up: "success", down: "danger", flat: "info", none: "neutral" };

const BAR_TONE: Record<string, "primary" | "success" | "warning" | "danger" | "accent" | "sky"> = {
  mastered: "success",
  consolidating: "primary",
  weak: "warning",
  critical: "danger",
  unknown: "sky",
};

const ATT_TONE: Record<string, Tone> = { present: "success", absent: "danger", late: "warning", excused: "info" };

const MEET_TONE: Record<string, Tone> = { scheduled: "info", held: "success", missed: "danger", cancelled: "neutral" };

function toErr(e: unknown): Err {
  if (e instanceof ApiError) return { message: e.detail ?? e.message, denied: e.status === 403 };
  return { message: e instanceof Error ? e.message : "خطا در دریافت اطلاعات", denied: false };
}

function ErrAlert({ err }: { err: Err }) {
  return (
    <Alert variant={err.denied ? "warning" : "danger"} title={err.denied ? "دسترسی محدود" : "خطا در دریافت اطلاعات"}>
      {err.message}
    </Alert>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-sunken p-3 text-center">
      <p className="text-[11px] font-semibold text-ink-muted">{label}</p>
      <p className="num mt-1 text-lg font-extrabold text-ink">{value}</p>
    </div>
  );
}

function fmtDate(v: string | null): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("fa-IR", { dateStyle: "short" });
}

function fmtDateTime(v: string | null): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? v
    : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}

export function LinksSection({ childId }: { childId: number }) {
  /* ---------------- پیوندها + مجوزها (GET /parent/links) ---------------- */
  const [links, setLinks] = useState<LinkRow[]>([]);
  const [permKeys, setPermKeys] = useState<Record<string, string>>({});
  const [linksLoading, setLinksLoading] = useState(true);
  const [linksErr, setLinksErr] = useState<Err | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  /* فهرست معلمان — برای فرم رضایت (GET /parent/tutors) */
  const [tutors, setTutors] = useState<{ user_id: number; name: string }[]>([]);
  const [tutorsErr, setTutorsErr] = useState<Err | null>(null);

  /* ---------------- زیرنماها ---------------- */
  const [view, setView] = useState<ViewKey>("subjects");
  const [subjects, setSubjects] = useState<SubjectsData | null>(null);
  const [subjectsLoading, setSubjectsLoading] = useState(true);
  const [subjectsErr, setSubjectsErr] = useState<Err | null>(null);

  const [compare, setCompare] = useState<CompareData | null>(null);
  const [compareLoading, setCompareLoading] = useState(true);
  const [compareErr, setCompareErr] = useState<Err | null>(null);

  const [att, setAtt] = useState<AttendanceData | null>(null);
  const [attLoading, setAttLoading] = useState(true);
  const [attErr, setAttErr] = useState<Err | null>(null);

  /* ---------------- رضایت از معلم خصوصی ---------------- */
  const [satRows, setSatRows] = useState<SatisfactionRow[]>([]);
  const [satLoading, setSatLoading] = useState(true);
  const [satErr, setSatErr] = useState<Err | null>(null);
  const [satTutor, setSatTutor] = useState("");
  const [satRating, setSatRating] = useState(5);
  const [satComment, setSatComment] = useState("");
  const [satBusy, setSatBusy] = useState(false);
  const [satFormErr, setSatFormErr] = useState<Err | null>(null);

  /* ---------------- بارگذاری اولیه (مستقل از هم — الگوی Promise.allSettled) ---------------- */

  const loadTop = useCallback(async () => {
    setLinksLoading(true);
    setLinksErr(null);
    setTutorsErr(null);
    const parts = await Promise.allSettled([
      api<LinksResp>("/parent/links"),
      api<{ tutors: { user_id: number; name: string }[] }>("/parent/tutors"),
    ]);
    if (parts[0].status === "fulfilled") {
      const d = parts[0].value;
      setLinks(Array.isArray(d?.links) ? d.links : []);
      setPermKeys(d?.permission_keys ?? {});
    } else {
      setLinks([]);
      setLinksErr(toErr(parts[0].reason));
    }
    if (parts[1].status === "fulfilled") {
      const list = parts[1].value?.tutors;
      setTutors(Array.isArray(list) ? list : []);
    } else {
      setTutors([]);
      setTutorsErr(toErr(parts[1].reason));
    }
    setLinksLoading(false);
  }, []);

  useEffect(() => {
    void loadTop();
  }, [loadTop]);

  const togglePerm = async (link: LinkRow, key: string, value: boolean) => {
    const tag = `${link.link_id}:${key}`;
    setSavingKey(tag);
    try {
      const res = await api<{ ok?: boolean; permissions?: Record<string, boolean> }>(
        `/parent/links/${link.link_id}/permissions`,
        { method: "PATCH", json: { permissions: { [key]: value } } }
      );
      if (res?.permissions) {
        const next = res.permissions;
        setLinks((prev) => prev.map((l) => (l.link_id === link.link_id ? { ...l, permissions: next } : l)));
      }
      toast(`دسترسی «${permKeys[key] ?? key}» برای ${link.student_name ?? "این فرزند"} ${value ? "فعال" : "محدود"} شد`, "success");
    } catch (e) {
      const err = toErr(e);
      toast(err.message, "error");
    } finally {
      setSavingKey(null);
    }
  };

  /* ---------------- زیرنماها: هر بخش جدا واکشی می‌شود ---------------- */

  const loadSubjects = useCallback(async () => {
    setSubjectsLoading(true);
    setSubjectsErr(null);
    try {
      setSubjects(await api<SubjectsData>(`/parent/children/${childId}/subjects`));
    } catch (e) {
      setSubjects(null);
      setSubjectsErr(toErr(e));
    } finally {
      setSubjectsLoading(false);
    }
  }, [childId]);

  const loadCompare = useCallback(async () => {
    setCompareLoading(true);
    setCompareErr(null);
    try {
      setCompare(await api<CompareData>(`/parent/children/${childId}/comparisons`));
    } catch (e) {
      setCompare(null);
      setCompareErr(toErr(e));
    } finally {
      setCompareLoading(false);
    }
  }, [childId]);

  const loadAttendance = useCallback(async () => {
    setAttLoading(true);
    setAttErr(null);
    try {
      setAtt(await api<AttendanceData>(`/parent/children/${childId}/attendance`));
    } catch (e) {
      setAtt(null);
      setAttErr(toErr(e));
    } finally {
      setAttLoading(false);
    }
  }, [childId]);

  useEffect(() => {
    if (view === "subjects") void loadSubjects();
    else if (view === "compare") void loadCompare();
    else void loadAttendance();
  }, [view, loadSubjects, loadCompare, loadAttendance]);

  const loadSat = useCallback(async () => {
    setSatLoading(true);
    setSatErr(null);
    try {
      const d = await api<{ student_user_id: number; rows: SatisfactionRow[] }>(
        `/parent/tutor-satisfaction?student_user_id=${childId}`
      );
      setSatRows(Array.isArray(d?.rows) ? d.rows : []);
    } catch (e) {
      setSatRows([]);
      setSatErr(toErr(e));
    } finally {
      setSatLoading(false);
    }
  }, [childId]);

  useEffect(() => {
    void loadSat();
  }, [loadSat]);

  async function submitSat() {
    const tutorId = Number(satTutor);
    if (!tutorId) {
      setSatFormErr({ message: "معلم خصوصی را انتخاب کنید.", denied: false });
      return;
    }
    if (satRating < 1 || satRating > 5) {
      setSatFormErr({ message: "امتیاز باید بین ۱ تا ۵ باشد.", denied: false });
      return;
    }
    setSatBusy(true);
    setSatFormErr(null);
    try {
      await api<{ ok?: boolean; rating?: number }>("/parent/tutor-satisfaction", {
        method: "POST",
        json: {
          student_user_id: childId,
          tutor_user_id: tutorId,
          rating: satRating,
          comment: satComment.trim() || null,
        },
      });
      toast("امتیاز شما ثبت شد", "success");
      setSatComment("");
      void loadSat();
    } catch (e) {
      setSatFormErr(toErr(e));
    } finally {
      setSatBusy(false);
    }
  }

  /* نمایش برچسب مجوزها از خودِ سرور؛ در نبودِ آن، کلیدها همان کلید خام */
  const permEntries: [string, string][] =
    Object.keys(permKeys).length > 0
      ? (Object.entries(permKeys) as [string, string][])
      : links.length > 0
        ? Object.keys(links[0].permissions).map((k) => [k, k] as [string, string])
        : [];

  const viewItems: { key: ViewKey; label: string }[] = [
    { key: "subjects", label: "وضعیت درس‌ها" },
    { key: "compare", label: "مقایسه‌ها" },
    { key: "attendance", label: "حضور و جلسات" },
  ];

  return (
    <Section
      title="فرزندان و دسترسی‌ها"
      subtitle="پیوند فعال والد–فرزند، مجوزهای مستقل هر بخش و جزئیات یادگیری فرزند انتخابی"
      action={
        <Button variant="soft" size="sm" loading={linksLoading} icon={<IconRefresh size={14} />} onClick={() => void loadTop()}>
          تازه‌سازی
        </Button>
      }
    >
      {/* ---------------- 1) پیوندها و سوییچ مجوزها ---------------- */}
      <Card>
        <CardHeader
          title="پیوندها و مجوزها"
          subtitle="هر مجوز فقط روی همین فرزند اثر می‌گذارد؛ خاموش کردن آن، بخش مربوط را برای شما محدود می‌کند (§17)."
          icon={<IconFamily size={17} />}
        />

        {linksErr && <ErrAlert err={linksErr} />}
        {linksLoading && links.length === 0 && !linksErr && <SkeletonText lines={4} />}
        {!linksLoading && !linksErr && links.length === 0 && (
          <EmptyState
            compact
            icon={<IconFamily size={24} />}
            title="پیوند فعالی یافت نشد"
            description="فرزندی به حساب شما متصل نیست؛ برای اتصال با مدیر مدرسه هماهنگ کنید."
          />
        )}

        <div className="space-y-4">
          {links.map((l) => (
            <div key={l.link_id} className="rounded-2xl border border-line bg-surface-sunken p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-bold text-ink">{l.student_name ?? `دانش‌آموز #${l.student_user_id}`}</p>
                  <p className="text-[11px] text-ink-faint">{l.relation ? `نسبت: ${l.relation}` : "پیوند فعال والد–فرزند"}</p>
                </div>
                <Badge tone="success" dot>
                  فعال
                </Badge>
              </div>

              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {permEntries.map(([key, label]) => {
                  const allowed = l.permissions[key] !== false;
                  const saving = savingKey === `${l.link_id}:${key}`;
                  return (
                    <label
                      key={key}
                      className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-muted transition ${
                        saving ? "opacity-60" : "cursor-pointer hover:bg-white/70"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={allowed}
                        disabled={saving}
                        onChange={(e) => void togglePerm(l, key, e.target.checked)}
                        className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                      />
                      <span>{label}</span>
                    </label>
                  );
                })}
              </div>

              <p className="mt-2 text-[11px] leading-5 text-ink-faint">
                کلید خاموش یعنی آن بخش برای همین فرزند محدود می‌شود؛ فرزندان دیگر تأثیری نمی‌پذیرند.
              </p>
            </div>
          ))}
        </div>
      </Card>

      {/* ---------------- 2) زیرنمای فرزند انتخابی ---------------- */}
      <Card>
        <CardHeader
          title="جزئیات فرزند انتخابی"
          subtitle="وضعیت درس‌ها، سه نوع مقایسه و حضور/جلسات — همگی تابع مجوزهای همین پیوند"
          icon={<IconTarget size={17} />}
        />

        <Tabs
          items={viewItems}
          value={view}
          onChange={(k) => setView(k as ViewKey)}
        />

        <div className="mt-4 space-y-4">
          {/* ------- وضعیت درس‌ها — GET /parent/children/{id}/subjects ------- */}
          {view === "subjects" && (
            <>
              {subjectsLoading && <SkeletonCard />}
              {subjectsErr && <ErrAlert err={subjectsErr} />}
              {!subjectsLoading && !subjectsErr && subjects && (
                <>
                  {subjects.subjects.length === 0 ? (
                    <EmptyState
                      compact
                      icon={<IconTarget size={24} />}
                      title="هنوز داده‌ای برای این فرزند ثبت نشده"
                      description="با پاسخ به تمرین‌ها و آزمون‌ها، وضعیت هر درس ساخته می‌شود."
                    />
                  ) : (
                    <div className="space-y-4">
                      {subjects.subjects.map((s) => (
                        <div key={s.subject ?? "other"} className="rounded-2xl border border-line bg-surface-sunken p-4">
                          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <p className="text-sm font-bold text-ink">{subjectFa(s.subject)}</p>
                              <p className="text-[11px] text-ink-faint">
                                {fa(s.topics_count)} مبحث — {fa(s.attention_count)} نیازمند توجه — {fa(s.consolidated_count)} مسلط
                              </p>
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Badge tone={statusTone(s.status)} dot>
                                {s.status_fa}
                              </Badge>
                              <Badge tone={TREND_TONE[s.trend] ?? "neutral"}>{s.trend_fa}</Badge>
                            </div>
                          </div>

                          <ProgressBar
                            value={s.current_mastery ?? 0}
                            label="میانگین تسط"
                            showValue
                            tone={BAR_TONE[s.status] ?? "primary"}
                          />

                          {s.dominant_error_fa && (
                            <p className="mt-2 text-[11px] text-ink-faint">خطای غالب: {s.dominant_error_fa}</p>
                          )}

                          {s.topics.length > 0 && (
                            <ul className="mt-3 space-y-1.5">
                              {s.topics.map((t) => (
                                <li
                                  key={t.topic_id}
                                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface px-3 py-2"
                                >
                                  <span className="truncate text-xs font-semibold text-ink">{t.title}</span>
                                  <span className="flex items-center gap-1.5">
                                    <span className="num text-[11px] text-ink-muted">{fa(t.mastery, 1)}٪</span>
                                    <Badge tone={statusTone(t.status)}>{t.status_fa}</Badge>
                                  </span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {subjects.note_fa && <Alert variant="info">{subjects.note_fa}</Alert>}
                </>
              )}
            </>
          )}

          {/* ------- مقایسه‌ها — GET /parent/children/{id}/comparisons ------- */}
          {view === "compare" && (
            <>
              {compareLoading && <SkeletonCard />}
              {compareErr && <ErrAlert err={compareErr} />}
              {!compareLoading && !compareErr && compare && (
                <>
                  {!compare.class_comparison_allowed && (
                    <Alert variant="warning" title="مقایسه با کالس مجاز نیست">
                      مجوز «مقایسه با میانگین کالس» برای این پیوند خاموش است؛ فقط مقایسه با وضعیت خودِ فرزند و هدف دوره
                      نمایش داده می‌شود.
                    </Alert>
                  )}

                  {compare.comparisons.length === 0 ? (
                    <EmptyState
                      compact
                      icon={<IconTrend size={24} />}
                      title="داده‌ای برای مقایسه وجود ندارد"
                      description="هنوز وضعیت درسی برای این فرزند ساخته نشده است."
                    />
                  ) : (
                    <div className="grid gap-4 lg:grid-cols-2">
                      {compare.comparisons.map((row) => (
                        <div key={row.subject ?? "other"} className="rounded-2xl border border-line bg-surface-sunken p-4">
                          <p className="mb-3 text-sm font-bold text-ink">{subjectFa(row.subject)}</p>

                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                            {/* نسبت به خودش */}
                            <div className="rounded-xl border border-line bg-surface p-3">
                              <p className="text-[11px] font-semibold text-ink-faint">نسبت به خودش</p>
                              <p className="num mt-1 text-sm font-extrabold text-ink">
                                {row.self.current != null ? `${fa(row.self.current, 1)}٪` : "—"}
                              </p>
                              <p className="num text-[11px] text-ink-muted">
                                {row.self.previous != null ? `قبلاً ${fa(row.self.previous, 1)}٪` : "بدون دوره قبل"}
                                {row.self.delta != null && ` — ${row.self.delta > 0 ? "+" : ""}${fa(row.self.delta, 1)}`}
                              </p>
                              <p className="mt-1 text-[10px] leading-4 text-ink-faint">{row.self.note_fa}</p>
                            </div>

                            {/* هدف دوره */}
                            <div className="rounded-xl border border-line bg-surface p-3">
                              <p className="text-[11px] font-semibold text-ink-faint">هدف دوره</p>
                              <p className="num mt-1 text-sm font-extrabold text-ink">{fa(row.period_goal.goal, 1)}٪</p>
                              <p className="num text-[11px] text-ink-muted">
                                {row.period_goal.current != null
                                  ? `فعلی ${fa(row.period_goal.current, 1)}٪ — شکاف ${row.period_goal.gap != null && row.period_goal.gap > 0 ? "+" : ""}${fa(row.period_goal.gap ?? 0, 1)}`
                                  : "بدون داده"}
                              </p>
                              <p className="mt-1 text-[10px] leading-4 text-ink-faint">{row.period_goal.note_fa}</p>
                            </div>

                            {/* نسبت به کالس — فقط اگر مجاز و بالای حداقل جمعیت باشد */}
                            <div className="rounded-xl border border-line bg-surface p-3">
                              <p className="text-[11px] font-semibold text-ink-faint">نسبت به کالس</p>
                              {row.class.class_avg != null ? (
                                <>
                                  <p className="num mt-1 text-sm font-extrabold text-ink">{fa(row.class.class_avg, 1)}٪</p>
                                  <p className="num text-[11px] text-ink-muted">
                                    شکاف {row.class.gap != null && row.class.gap > 0 ? "+" : ""}
                                    {fa(row.class.gap ?? 0, 1)}
                                  </p>
                                </>
                              ) : (
                                <p className="mt-1 text-[11px] leading-5 text-ink-faint">
                                  {row.class.reason_fa ?? "میانگین کالس نمایش داده نمی‌شود."}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <Alert variant="info" title="حریم خصوصی مقایسه‌ها">
                    <p className="text-xs leading-6">
                      {compare.note_fa}
                      <br />
                      حداقل جمعیت برای نمایش میانگین کالس: {fa(compare.min_group)} نفر.
                    </p>
                  </Alert>
                </>
              )}
            </>
          )}

          {/* ------- حضور و جلسات — GET /parent/children/{id}/attendance ------- */}
          {view === "attendance" && (
            <>
              {attLoading && <SkeletonCard />}
              {attErr && <ErrAlert err={attErr} />}
              {!attLoading && !attErr && att && (
                <>
                  {att.attendance.days === 0 || att.attendance.rate_pct == null ? (
                    /* سرور چیزی ثبت نشده گفته؛ فقط همان یادداشت را نشان می‌دهیم — بدون ساختن عدد */
                    <Alert variant="info" title="حضور مدرسه ثبت نشده است">
                      {att.note_fa}
                    </Alert>
                  ) : (
                    <div className="rounded-2xl border border-line bg-surface p-4">
                      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                        <MiniStat label="روزهای ثبت‌شده" value={fa(att.attendance.days)} />
                        <MiniStat label="غایب" value={fa(att.attendance.absent)} />
                        <MiniStat label="تاخیر" value={fa(att.attendance.late)} />
                        <MiniStat label="غیبت موجه" value={fa(att.attendance.excused)} />
                      </div>

                      <ProgressBar
                        className="mt-3"
                        value={att.attendance.rate_pct ?? 0}
                        label="نرخ حضور"
                        showValue
                        tone={att.attendance.rate_pct >= 90 ? "success" : att.attendance.rate_pct >= 75 ? "warning" : "danger"}
                      />

                      {att.attendance.rows.length > 0 && (
                        <ul className="mt-3 space-y-1.5">
                          {att.attendance.rows.slice(0, 8).map((r, i) => (
                            <li
                              key={`${r.on_date}-${i}`}
                              className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-sunken px-3 py-2"
                            >
                              <span className="num text-xs text-ink-muted">{fmtDate(r.on_date)}</span>
                              <span className="flex items-center gap-2">
                                {r.note && <span className="text-[11px] text-ink-faint">{r.note}</span>}
                                <Badge tone={ATT_TONE[r.status] ?? "neutral"} dot>
                                  {r.status_fa}
                                </Badge>
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}

                  <div className="rounded-2xl border border-line bg-surface p-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-bold text-ink">جلسات ({fa(att.sessions.total)})</p>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge tone="info" dot>
                          پیش رو: {fa(att.sessions.upcoming.length)}
                        </Badge>
                        <Badge tone={att.sessions.missed.length > 0 ? "danger" : "neutral"} dot>
                          ازدست‌رفته: {fa(att.sessions.missed.length)}
                        </Badge>
                        <Badge tone={att.sessions.pending_tasks.length > 0 ? "warning" : "neutral"} dot>
                          تکلیف در انتظار: {fa(att.sessions.pending_tasks.length)}
                        </Badge>
                      </div>
                    </div>

                    {att.sessions.upcoming.length === 0 && att.sessions.past.length === 0 ? (
                      <EmptyState
                        compact
                        icon={<IconClock size={24} />}
                        title="جلسه‌ای ثبت نشده است"
                        description="جلسات معلم خصوصی، مدرسه و جلسه با والدین پس از ثبت اینجا دیده می‌شوند."
                      />
                    ) : (
                      <div className="grid gap-4 lg:grid-cols-2">
                        <div>
                          <p className="mb-2 text-[11px] font-bold text-ink-muted">جلسات پیش رو</p>
                          {att.sessions.upcoming.length === 0 ? (
                            <p className="text-[11px] text-ink-faint">جلسه پیش رویی ثبت نشده است.</p>
                          ) : (
                            <ul className="space-y-2">
                              {att.sessions.upcoming.map((m) => (
                                <MeetingItem key={m.id} m={m} />
                              ))}
                            </ul>
                          )}
                        </div>
                        <div>
                          <p className="mb-2 text-[11px] font-bold text-ink-muted">جلسات گذشته</p>
                          {att.sessions.past.length === 0 ? (
                            <p className="text-[11px] text-ink-faint">جلسه گذشته‌ای ثبت نشده است.</p>
                          ) : (
                            <ul className="space-y-2">
                              {att.sessions.past.slice(0, 6).map((m) => (
                                <MeetingItem key={m.id} m={m} />
                              ))}
                            </ul>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  <Alert variant="info" title="درباره این نما">
                    {att.note_fa}
                  </Alert>
                </>
              )}
            </>
          )}
        </div>
      </Card>

      {/* ---------------- 4) رضایت از معلم خصوصی ---------------- */}
      <Card>
        <CardHeader
          title="رضایت از معلم خصوصی"
          subtitle="امتیاز ۱ تا ۵ شما از معلمِ همین فرزند — جدا از داده آموزشی (§11/§12)"
          icon={<IconCheckCircle size={17} />}
          action={
            <Button variant="ghost" size="sm" loading={satLoading} icon={<IconRefresh size={13} />} onClick={() => void loadSat()}>
              تازه‌سازی
            </Button>
          }
        />

        {satErr && <ErrAlert err={satErr} />}
        {satLoading && satRows.length === 0 && !satErr && <SkeletonText lines={2} />}
        {!satLoading && !satErr && satRows.length === 0 && (
          <p className="text-[11px] text-ink-faint">هنوز امتیازی برای این فرزند ثبت نکرده‌اید.</p>
        )}

        {satRows.length > 0 && (
          <ul className="space-y-2">
            {satRows.map((r) => (
              <li
                key={r.tutor_user_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface-sunken px-3.5 py-2.5"
              >
                <span className="text-xs font-semibold text-ink">{r.tutor_name ?? `معلم #${r.tutor_user_id}`}</span>
                <span className="flex items-center gap-2">
                  <span className="text-[11px] text-ink-faint">
                    به‌روزرسانی: <span className="num">{fmtDate(r.updated_at)}</span>
                  </span>
                  <Badge tone={r.rating >= 4 ? "success" : r.rating >= 3 ? "warning" : "danger"} dot>
                    {fa(r.rating)} از ۵
                  </Badge>
                </span>
                {r.comment && <p className="w-full text-[11px] leading-5 text-ink-faint">{r.comment}</p>}
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 rounded-2xl border border-line bg-surface-sunken p-4">
          <p className="mb-3 text-xs font-bold text-ink">ثبت یا به‌روزرسانی امتیاز</p>

          {satFormErr && (
            <div className="mb-3">
              <ErrAlert err={satFormErr} />
            </div>
          )}
          {tutorsErr && (
            <div className="mb-3">
              <Alert variant="warning" title="فهرست معلمان در دسترس نیست">
                {tutorsErr.message}
              </Alert>
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field
              label="معلم خصوصی"
              required
              hint={tutors.length === 0 && !tutorsErr ? "در حال بارگذاری فهرست معلمان…" : undefined}
            >
              <Select value={satTutor} onChange={(e) => setSatTutor(e.target.value)}>
                <option value="">انتخاب کنید…</option>
                {tutors.map((t) => (
                  <option key={t.user_id} value={String(t.user_id)}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>

            {/* دکمه‌های امتیاز داخل <label> نمی‌روند تا کلیک برچسب، امتیاز را تغییر ندهد */}
            <div>
              <span className="mb-1.5 flex items-center gap-1 text-xs font-semibold text-ink-muted">
                امتیاز <span className="text-danger-500">*</span>
              </span>
              <div className="flex flex-wrap gap-2">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setSatRating(n)}
                    aria-pressed={satRating === n}
                    className={`h-9 w-9 rounded-xl text-xs font-bold transition ${
                      satRating === n
                        ? "bg-brand-gradient text-white shadow-lift"
                        : "border border-line bg-surface text-ink-muted hover:border-primary-300 hover:text-primary-700"
                    }`}
                  >
                    {fa(n)}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-3">
            <Field label="نظر (اختیاری)">
              <Textarea
                placeholder="مثلاً: نحوه توضیح حل مسئله خوب بود؛ مرور هفتگی را بیشتر کند."
                value={satComment}
                onChange={(e) => setSatComment(e.target.value)}
              />
            </Field>
          </div>

          <div className="mt-3 flex justify-end">
            <Button loading={satBusy} onClick={() => void submitSat()}>
              ثبت امتیاز
            </Button>
          </div>
        </div>
      </Card>
    </Section>
  );
}

function MeetingItem({ m }: { m: MeetingRow }) {
  return (
    <li className="rounded-xl border border-line bg-surface-sunken px-3.5 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-ink">{m.topic_fa ?? m.kind_fa}</span>
        <Badge tone={MEET_TONE[m.status] ?? "neutral"} dot>
          {m.status_fa}
        </Badge>
      </div>
      <p className="mt-1 text-[11px] text-ink-faint">
        {m.kind_fa}
        {m.subject ? ` — ${subjectFa(m.subject)}` : ""} · <span className="num">{fmtDateTime(m.scheduled_at)}</span>
        {m.tutor_name ? ` · ${m.tutor_name}` : ""}
        {typeof m.duration_min === "number" && m.duration_min > 0 ? ` · ${fa(m.duration_min)} دقیقه` : ""}
      </p>
      {m.report_fa && <p className="mt-1 text-[11px] leading-5 text-ink-muted">گزارش: {m.report_fa}</p>}
      {m.task_fa && (
        <p className="mt-1 text-[11px] text-ink-faint">
          تکلیف: {m.task_fa} — {m.task_status_fa ?? "—"}
        </p>
      )}
    </li>
  );
}
