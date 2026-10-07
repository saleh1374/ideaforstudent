"use client";

/** دانش‌آموزان کلاس (سند پنل معلم §5 + §9 + §11/§12):
- فهرست کلاس: تسط/ماندگاری/خطاها/وضعیت نیاز — روی هر ردیف، مودال «چرا؟» (§5.2)
  و «روند» (§5.3) باز می‌شود.
- مأموریت کلاسی §9: ثبت هدف ← پیشرفت زنده ← بستن با سنجش نهایی.
- مقایسه §11 و آمادگی §12 فقط برای تشخیص الگو، نه رتبه‌بندی.
هر واکشی جدا انجام می‌شود تا خطای 403 یک بخش، کل تب را نیندازد. */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { fa, subjectFa } from "@/lib/labels";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonCard, SkeletonTable } from "@/components/ui/skeleton";
import { DataTable, type Column } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import { IconChart, IconCheckCircle, IconPlus, IconTarget, IconUsers } from "@/components/ui/icons";

type ClassInfo = {
  class_id: number;
  name: string;
  grade: string;
  subject: string;
  school_name: string | null;
  students_count: number;
};

/** ردیف GET /teacher/classes/{id}/students — همان need_groups + برچسب نیاز. */
type RosterStudent = {
  student_id: number;
  full_name: string;
  mastery: number;
  retention: number;
  progress_pct: number | null;
  repeat_errors: number;
  prereq_weak: boolean;
  need: string;
  need_label: string;
};

/** GET /teacher/classes/{id}/students/{sid}/why — teacher_svc.student_why */
type Why = {
  class_id: number;
  student_id: number;
  need: string;
  need_label: string;
  action: string;
  mastery: number;
  retention: number;
  progress_pct: number | null;
  open_errors: number;
  reasons_fa: string[];
  dominant_cause: string | null;
  dominant_cause_fa: string | null;
  problem_prereq: string | null;
  last_failure: {
    at: string | null;
    days_ago: number | null;
    topic: string | null;
    cause: string;
    cause_fa: string;
    status: string;
    status_fa: string;
  } | null;
  last_success: { at: string | null; topic: string | null; source: string; source_fa: string } | null;
  similar_errors_fa: Record<string, number>;
  suggestion_fa: string;
  note_fa: string;
};

type TimelineEvent = { at: string | null; kind: string; tone: string; title_fa: string; detail_fa: string };

/** GET /teacher/classes/{id}/students/{sid}/timeline */
type Timeline = { class_id: number; student_id: number; events: TimelineEvent[]; note_fa: string };

/** ردیف مأموریت — teacher_svc.mission_row */
type Mission = {
  id: number;
  class_id: number;
  class_name: string | null;
  topic_id: number | null;
  topic_title: string | null;
  title_fa: string;
  target_mastery: number;
  deadline: string | null;
  status: string;
  status_fa: string;
  baseline_mastery: number | null;
  current_mastery: number | null;
  progress_pct: number;
  students_total: number;
  students_achieved: number;
  result_note_fa: string | null;
  created_at: string | null;
  completed_at: string | null;
  note_fa: string;
};

type CompareScope = { students: number; mastery: number | null; retention: number | null; name?: string | null };

/** GET /teacher/classes/{id}/compare — teacher_svc.class_compare */
type CompareData = {
  class_id: number;
  class_name: string;
  class: CompareScope;
  school: CompareScope;
  province: CompareScope;
  cause_share_class: Record<string, number>;
  cause_share_school: Record<string, number>;
  dominant_gap_fa: string | null;
  pattern_fa: string;
  note_fa: string;
};

/** GET /teacher/classes/{id}/readiness — teacher_svc.readiness_snapshot */
type Readiness = {
  class_id: number;
  topic_id: number | null;
  topic_title: string | null;
  students: number;
  counts: Record<string, number>;
  estimate_pct: number | null;
  buckets_fa: Record<string, string>;
  note_fa: string;
};

/** نیاز پنج‌گانه §6 → لحن Badge */
const NEED_TONE: Record<string, Tone> = {
  intervention: "danger",
  retention_drop: "warning",
  behind: "warning",
  future_risk: "info",
  ready: "success",
};

const EVENT_TONE: Record<string, Tone> = {
  success: "success",
  danger: "danger",
  warning: "warning",
  neutral: "neutral",
};

const EVENT_KIND_FA: Record<string, string> = {
  error: "خطا",
  evidence: "شاهد",
  exam: "آزمون",
  plan: "برنامه",
  state: "تسط",
};

const BUCKETS = ["mastered", "ready", "review", "repair"] as const;
/** لحن ProgressBar («sky» فقط در progress.tsx هست، نه در Badge) */
type BarTone = "primary" | "success" | "warning" | "danger" | "accent" | "sky";
const BUCKET_TONE: Record<string, BarTone> = {
  mastered: "success",
  ready: "sky",
  review: "warning",
  repair: "danger",
};

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : "خطا");

const fmtDateTime = (iso: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
};

const fmtDate = (iso: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fa-IR");
};

export function StudentsSection({
  classes,
  classesLoading = false,
}: {
  classes: ClassInfo[];
  /** وضعیت واکشی فهرست کلاس‌ها در صفحهٔ والد — برای جلوگیری از پیام «کلاسی نیست» در آغاز بارگذاری */
  classesLoading?: boolean;
}) {
  const [classId, setClassId] = useState<number | null>(classes[0]?.class_id ?? null);
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [compare, setCompare] = useState<CompareData | null>(null);
  const [ready, setReady] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const reqRef = useRef(0);

  // مودال دانش‌آموز
  const [selected, setSelected] = useState<RosterStudent | null>(null);
  const [modalTab, setModalTab] = useState<"why" | "timeline">("why");
  const [why, setWhy] = useState<Why | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalError, setModalError] = useState("");

  // فرم مأموریت
  const [title, setTitle] = useState("");
  const [target, setTarget] = useState("70");
  const [deadline, setDeadline] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");
  const [completingId, setCompletingId] = useState<number | null>(null);

  // کلاس‌ها در صفحهٔ والد به‌صورت ناهمزمان می‌آیند → انتخاب را همگام نگه می‌داریم
  useEffect(() => {
    setClassId((prev) =>
      prev !== null && classes.some((c) => c.class_id === prev) ? prev : classes[0]?.class_id ?? null
    );
  }, [classes]);

  const loadClass = useCallback(async (cid: number) => {
    const id = ++reqRef.current;
    setLoading(true);
    setError("");
    setStudents([]);
    setMissions([]);
    setCompare(null);
    setReady(null);

    // هر بخش مستقل واکشی می‌شود تا 403 یک بخش، کل تب را نیندازد
    const parts = await Promise.allSettled([
      api<{ class_id: number; students: RosterStudent[] }>(`/teacher/classes/${cid}/students`),
      api<{ class_id: number; missions: Mission[] }>(`/teacher/classes/${cid}/missions`),
      api<CompareData>(`/teacher/classes/${cid}/compare`),
      api<Readiness>(`/teacher/classes/${cid}/readiness`),
    ]);
    if (reqRef.current !== id) return; // کلاس عوض شده؛ پاسخ کهنه را دور می‌ریزیم

    if (parts[0].status === "fulfilled") setStudents(parts[0].value.students);
    if (parts[1].status === "fulfilled") setMissions(parts[1].value.missions);
    if (parts[2].status === "fulfilled") setCompare(parts[2].value);
    if (parts[3].status === "fulfilled") setReady(parts[3].value);

    const failed = parts.filter((p) => p.status === "rejected") as PromiseRejectedResult[];
    if (failed.length === parts.length) {
      setError(errMsg(failed[0]?.reason));
    } else if (failed.length > 0) {
      toast("برخی بخش‌ها بر اساس حوزه دسترسی شما نمایش داده نشدند.", "info");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (classId === null) {
      reqRef.current++;
      setStudents([]);
      setMissions([]);
      setCompare(null);
      setReady(null);
      setError("");
      setLoading(false);
      return;
    }
    loadClass(classId);
  }, [classId, loadClass]);

  // «چرا؟» + «روند» هر دو با هم واکشی می‌شوند تا عوض‌کردن زیرتب فوری باشد
  useEffect(() => {
    if (selected === null || classId === null) return;
    let alive = true;
    setModalLoading(true);
    setModalError("");
    setWhy(null);
    setTimeline(null);
    Promise.allSettled([
      api<Why>(`/teacher/classes/${classId}/students/${selected.student_id}/why`),
      api<Timeline>(`/teacher/classes/${classId}/students/${selected.student_id}/timeline`),
    ]).then((parts) => {
      if (!alive) return;
      if (parts[0].status === "fulfilled") setWhy(parts[0].value);
      if (parts[1].status === "fulfilled") setTimeline(parts[1].value);
      if (parts[0].status === "rejected" && parts[1].status === "rejected") {
        setModalError(errMsg((parts[0] as PromiseRejectedResult).reason));
      } else if (parts[0].status === "rejected" || parts[1].status === "rejected") {
        toast("برخی اطلاعات این دانش‌آموز قابل نمایش نیست.", "info");
      }
      setModalLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [selected, classId]);

  async function createMission(e: FormEvent) {
    e.preventDefault();
    if (classId === null) return;
    const t = title.trim();
    const targetNum = Number(target);
    if (t.length < 3) {
      setFormError("عنوان مأموریت باید حداقل ۳ حرف باشد.");
      return;
    }
    if (Number.isNaN(targetNum) || targetNum < 10 || targetNum > 100) {
      setFormError("هدف تسط باید بین ۱۰ تا ۱۰۰ درصد باشد.");
      return;
    }
    setCreating(true);
    setFormError("");
    try {
      const d = await api<{ ok: boolean; mission: Mission }>(`/teacher/classes/${classId}/missions`, {
        method: "POST",
        json: {
          title_fa: t,
          topic_id: null,
          target_mastery: targetNum,
          deadline: deadline ? deadline : null,
        },
      });
      setMissions((prev) => [d.mission, ...prev]);
      setTitle("");
      setDeadline("");
      toast("مأموریت ثبت شد؛ دانش‌آموزان زیر آستانه خودکار شناسایی شدند.", "success");
    } catch (e2) {
      setFormError(errMsg(e2));
      toast(errMsg(e2), "error");
    } finally {
      setCreating(false);
    }
  }

  async function completeMission(m: Mission) {
    setCompletingId(m.id);
    try {
      const d = await api<{ ok: boolean; mission: Mission }>(`/teacher/missions/${m.id}/complete`, {
        method: "POST",
        json: {},
      });
      setMissions((prev) => prev.map((x) => (x.id === m.id ? d.mission : x)));
      toast("مأموریت بسته شد و نتیجهٔ سنجش ثبت گردید.", "success");
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setCompletingId(null);
    }
  }

  const columns: Column<RosterStudent>[] = [
    {
      key: "name",
      header: "دانش‌آموز",
      render: (row) => (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{row.full_name}</span>
          {row.prereq_weak && (
            <Badge tone="warning" dot>
              پیش‌نیاز
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: "mastery",
      header: "تسط",
      align: "center",
      render: (row) => (
        <div className="mx-auto w-28">
          <span className="num mb-1 block text-xs font-bold text-ink">{fa(row.mastery)}٪</span>
          <ProgressBar
            value={row.mastery}
            size="sm"
            tone={row.mastery < 50 ? "danger" : row.mastery < 70 ? "warning" : "success"}
          />
        </div>
      ),
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num font-semibold">{fa(row.retention * 100)}٪</span>,
    },
    {
      key: "errors",
      header: "خطاهای باز",
      align: "center",
      render: (row) => (
        <span className={`num font-bold ${row.repeat_errors > 0 ? "text-danger-600" : "text-ink-faint"}`}>
          {fa(row.repeat_errors)}
        </span>
      ),
    },
    {
      key: "status",
      header: "وضعیت نیاز",
      align: "center",
      render: (row) => <Badge tone={NEED_TONE[row.need] ?? "neutral"}>{row.need_label}</Badge>,
    },
  ];

  if (classes.length === 0) {
    if (classesLoading) return <SkeletonCard />;
    return (
      <EmptyState
        icon={<IconUsers size={26} />}
        title="کلاسی به شما تخصیص نیافته است"
        description="پس از تخصیص کلاس توسط مدیر مدرسه، فهرست دانش‌آموزان اینجا نمایش داده می‌شود."
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* انتخاب کلاس */}
      <Tabs
        items={classes.map((c) => ({
          key: String(c.class_id),
          label: `کلاس ${c.name} — ${subjectFa(c.subject)}`,
          count: c.students_count,
        }))}
        value={String(classId ?? "")}
        onChange={(k) => {
          setSelected(null);
          setClassId(Number(k));
        }}
      />

      {error && <Alert variant="danger" title="خطا در دریافت اطلاعات کلاس">{error}</Alert>}

      {/* ——— فهرست دانش‌آموزان ——— */}
      <Section
        title="فهرست دانش‌آموزان کلاس"
        subtitle="تسط، ماندگاری، خطاهای باز و وضعیت نیاز — روی هر ردیف کلیک کنید تا «چرا؟» و «روند» باز شود."
      >
        <DataTable
          columns={columns}
          rows={students}
          keyOf={(r) => r.student_id}
          loading={loading}
          onRowClick={(r) => {
            setModalTab("why");
            setSelected(r);
          }}
          empty={
            <EmptyState
              compact
              icon={<IconUsers size={24} />}
              title="دانش‌آموزی در این کلاس ثبت نشده"
              description="با ثبت‌نام دانش‌آموزان، فهرست و شاخص‌ها اینجا پر می‌شود."
            />
          }
        />
      </Section>

      {/* ——— مأموریت‌های کلاسی §9 ——— */}
      <Section
        title="مأموریت‌های کلاس"
        subtitle="§9 — هدف را شما تعیین می‌کنید؛ دانش‌آموزان زیر آستانه خودکار شناسایی و پیشرفت زنده محاسبه می‌شود."
      >
        <Card>
          <CardHeader
            title="مأموریت جدید"
            subtitle="عنوان و هدف تسط الزامی است؛ مهلت اختیاری."
            icon={<IconTarget size={17} />}
          />
          <form onSubmit={createMission} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="عنوان مأموریت" required className="sm:col-span-2">
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="مثلاً: تثبیت مفهوم کسری‌ها"
                maxLength={200}
              />
            </Field>
            <Field label="هدف تسط (٪)" required hint="بین ۱۰ تا ۱۰۰">
              <Input
                type="number"
                min={10}
                max={100}
                step={1}
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="num"
              />
            </Field>
            <Field label="مهلت (اختیاری)">
              <Input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} className="num" />
            </Field>
            <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-4">
              <Button type="submit" loading={creating} icon={<IconPlus size={15} />}>
                ثبت مأموریت
              </Button>
              {formError && <span className="text-xs font-semibold text-danger-600">{formError}</span>}
            </div>
          </form>
        </Card>

        {loading ? (
          <div className="grid gap-3 md:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : missions.length === 0 ? (
          <EmptyState
            compact
            icon={<IconTarget size={24} />}
            title="مأموریتی برای این کلاس ثبت نشده"
            description="با ثبت اولین مأموریت، پیشرفت تسط کلاس تا رسیدن به هدف اینجا دنبال می‌شود."
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {missions.map((m) => (
              <Card key={m.id} className="space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-ink">{m.title_fa}</p>
                    <p className="num mt-1 text-[11px] leading-5 text-ink-muted">
                      {m.topic_title ? `مبحث: ${m.topic_title}` : "کل درس"} · مهلت: {fmtDate(m.deadline)}
                    </p>
                  </div>
                  <Badge tone={m.status === "completed" ? "success" : m.status === "archived" ? "neutral" : "info"}>
                    {m.status_fa}
                  </Badge>
                </div>

                <ProgressBar
                  value={m.progress_pct}
                  size="sm"
                  tone={m.progress_pct >= 85 ? "success" : m.progress_pct >= 50 ? "warning" : "danger"}
                  label={`تسط کلاس: ${fa(m.current_mastery)}٪ از هدف ${fa(m.target_mastery)}٪`}
                  showValue
                />

                <p className="num text-[11px] text-ink-muted">
                  پایه: {m.baseline_mastery !== null ? `${fa(m.baseline_mastery)}٪` : "—"} · دانش‌آموزان هدف رسیده:{" "}
                  {fa(m.students_achieved)} از {fa(m.students_total)}
                </p>

                {m.result_note_fa && (
                  <p className="rounded-xl bg-surface-sunken px-3 py-2 text-[11px] leading-6 text-ink-muted">
                    {m.result_note_fa}
                  </p>
                )}

                {m.status === "active" && (
                  <Button
                    size="sm"
                    variant="soft"
                    loading={completingId === m.id}
                    icon={<IconCheckCircle size={14} />}
                    onClick={() => completeMission(m)}
                  >
                    ثبت نتیجه و بستن مأموریت
                  </Button>
                )}
              </Card>
            ))}
          </div>
        )}
      </Section>

      {/* ——— مقایسه §11 + آمادگی §12 ——— */}
      <Section
        title="مقایسه و آمادگی"
        subtitle="تجمیع ناشناس برای تشخیص الگو — نه رتبه‌بندی معلم، مدرسه یا استان."
      >
        {loading ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : !compare && !ready ? (
          <EmptyState
            compact
            icon={<IconChart size={24} />}
            title="داده‌ای برای مقایسه و آمادگی موجود نیست"
            description="پس از ثبت شواهد کافی، این بخش بر اساس دادهٔ همین کلاس پر می‌شود."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {compare && (
              <Card>
                <CardHeader
                  title="کلاس شما در برابر مدرسه و استان"
                  subtitle="میانگین تسط/ماندگاری روی دانش‌آموزان دارای دادهٔ کافی"
                  icon={<IconChart size={17} />}
                />
                <div className="grid grid-cols-3 gap-3 text-center">
                  {(
                    [
                      ["کلاس شما", compare.class],
                      ["میانگین مدرسه", compare.school],
                      ["میانگین استان", compare.province],
                    ] as [string, CompareScope][]
                  ).map(([label, scope]) => (
                    <div key={label} className="rounded-xl bg-surface-sunken px-2 py-3">
                      <p className="text-[11px] font-bold text-ink-muted">{label}</p>
                      <p className="num mt-1 text-lg font-extrabold text-ink">
                        {scope.mastery !== null ? `${fa(scope.mastery, 1)}٪` : "—"}
                      </p>
                      <p className="num text-[11px] text-ink-faint">
                        ماندگاری {scope.retention !== null ? `${fa(scope.retention * 100)}٪` : "—"}
                      </p>
                      <p className="num text-[10px] text-ink-faint">{fa(scope.students)} دانش‌آموز</p>
                    </div>
                  ))}
                </div>
                {compare.pattern_fa && (
                  <Alert variant="info" title="الگو">
                    {compare.pattern_fa}
                  </Alert>
                )}
                {compare.dominant_gap_fa && (
                  <Alert variant="warning" title="شکاف غالب خطا">
                    {compare.dominant_gap_fa}
                  </Alert>
                )}
                <p className="text-[11px] leading-6 text-ink-faint">{compare.note_fa}</p>
              </Card>
            )}

            {ready && (
              <Card>
                <CardHeader
                  title="آمادگی کلاس"
                  subtitle="اگر فردا از این فصل امتحان بگیرم — برآورد تشخیصی، نه پیش‌بینی نمره"
                  icon={<IconTarget size={17} />}
                />
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-bold text-ink">برآورد آمادگی کل کلاس</span>
                  <span className="num text-lg font-extrabold text-ink">
                    {ready.estimate_pct !== null ? `${fa(ready.estimate_pct, 1)}٪` : "—"}
                  </span>
                </div>
                <ProgressBar
                  value={ready.estimate_pct ?? 0}
                  tone={ready.estimate_pct !== null && ready.estimate_pct >= 70 ? "success" : "warning"}
                />
                <div className="mt-4 space-y-2.5">
                  {BUCKETS.map((k) => (
                    <div key={k}>
                      <div className="mb-1 flex items-center justify-between text-[11px]">
                        <span className="font-semibold text-ink-muted">{ready.buckets_fa[k] ?? k}</span>
                        <span className="num text-ink-faint">{fa(ready.counts[k] ?? 0)} نفر</span>
                      </div>
                      <ProgressBar
                        value={ready.students > 0 ? ((ready.counts[k] ?? 0) / ready.students) * 100 : 0}
                        size="sm"
                        tone={BUCKET_TONE[k]}
                      />
                    </div>
                  ))}
                </div>
                <p className="num mt-3 text-[11px] text-ink-faint">
                  {ready.topic_title ? `مبحث: ${ready.topic_title}` : "کل درس"} · {fa(ready.students)} دانش‌آموز
                </p>
                <p className="mt-1 text-[11px] leading-6 text-ink-faint">{ready.note_fa}</p>
              </Card>
            )}
          </div>
        )}
      </Section>

      {/* ——— مودال دانش‌آموز: «چرا؟» + «روند» ——— */}
      <Modal
        open={selected !== null}
        onClose={() => setSelected(null)}
        size="lg"
        title={selected ? `پروندهٔ ${selected.full_name}` : ""}
      >
        <div className="space-y-4">
          <Tabs
            items={[
              { key: "why", label: "چرا؟" },
              { key: "timeline", label: "روند" },
            ]}
            value={modalTab}
            onChange={(k) => setModalTab(k as "why" | "timeline")}
          />

          {modalLoading && <SkeletonTable rows={4} cols={3} />}

          {!modalLoading && modalError && (
            <Alert variant="danger" title="خطا در دریافت اطلاعات دانش‌آموز">
              {modalError}
            </Alert>
          )}

          {!modalLoading && !modalError && modalTab === "why" && (
            <>{why ? <WhyView why={why} /> : <EmptyState compact title="داده‌ای برای توضیح ثبت نشده" />}</>
          )}

          {!modalLoading && !modalError && modalTab === "timeline" && (
            <>{timeline ? <TimelineView tl={timeline} /> : <EmptyState compact title="رویدادی ثبت نشده" />}</>
          )}
        </div>
      </Modal>
    </div>
  );
}

/** §5.2 کارت «چرا؟» — دلایل ریشه‌ای، مبحث/پیش‌نیاز ضعیف و شواهد عددی. */
function WhyView({ why }: { why: Why }) {
  const stats: { label: string; value: string }[] = [
    { label: "تسط مؤثر", value: `${fa(why.mastery)}٪` },
    { label: "ماندگاری", value: `${fa(why.retention * 100)}٪` },
    { label: "پیشرفت برنامه", value: why.progress_pct !== null ? `${fa(why.progress_pct)}٪` : "—" },
    { label: "خطاهای باز", value: fa(why.open_errors) },
  ];
  const hasEvidence = why.last_failure !== null || why.last_success !== null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl bg-surface-sunken px-3 py-2.5 text-center">
            <p className="text-[11px] font-bold text-ink-muted">{s.label}</p>
            <p className="num mt-1 text-sm font-extrabold text-ink">{s.value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={NEED_TONE[why.need] ?? "neutral"}>{why.need_label}</Badge>
        {why.dominant_cause_fa && <Badge tone="danger">علت غالب: {why.dominant_cause_fa}</Badge>}
        {why.problem_prereq && <Badge tone="warning">پیش‌نیاز ضعیف: {why.problem_prereq}</Badge>}
      </div>

      <div>
        <p className="mb-2 text-xs font-bold text-ink">چرا در این گروه نیاز است؟ (ریشه‌یابی قاعده‌محور)</p>
        {why.reasons_fa.length === 0 ? (
          <p className="text-xs text-ink-faint">دلیلی ثبت نشده است.</p>
        ) : (
          <ul className="space-y-1.5">
            {why.reasons_fa.map((r, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-xl bg-surface-sunken px-3 py-2 text-xs leading-6 text-ink-muted"
              >
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-400" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {Object.keys(why.similar_errors_fa).length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-bold text-ink">علت خطاها (شواهد)</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(why.similar_errors_fa).map(([cause, n]) => (
              <span
                key={cause}
                className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-ink-muted"
              >
                {cause}: {fa(n)}
              </span>
            ))}
          </div>
        </div>
      )}

      {hasEvidence ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {why.last_failure ? (
            <div className="rounded-xl border border-line bg-surface px-3 py-2.5">
              <p className="text-[11px] font-bold text-danger-600">آخرین شکست</p>
              <p className="mt-1 text-xs font-semibold text-ink">{why.last_failure.topic ?? "—"}</p>
              <p className="num mt-0.5 text-[11px] leading-5 text-ink-muted">
                {why.last_failure.cause_fa} · {why.last_failure.status_fa}
                {why.last_failure.days_ago !== null && ` · ${fa(why.last_failure.days_ago)} روز پیش`}
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-surface px-3 py-2.5">
              <p className="text-[11px] font-bold text-danger-600">آخرین شکست</p>
              <p className="mt-1 text-xs text-ink-faint">خطایی ثبت نشده است.</p>
            </div>
          )}
          {why.last_success ? (
            <div className="rounded-xl border border-line bg-surface px-3 py-2.5">
              <p className="text-[11px] font-bold text-success-600">آخرین تلاش موفق</p>
              <p className="mt-1 text-xs font-semibold text-ink">{why.last_success.topic ?? "—"}</p>
              <p className="num mt-0.5 text-[11px] leading-5 text-ink-muted">
                {why.last_success.source_fa} · {fmtDateTime(why.last_success.at)}
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-surface px-3 py-2.5">
              <p className="text-[11px] font-bold text-success-600">آخرین تلاش موفق</p>
              <p className="mt-1 text-xs text-ink-faint">شاهدهای موفق ثبت نشده است.</p>
            </div>
          )}
        </div>
      ) : null}

      <Alert variant="info" title="اقدام پیشنهادی — فقط با تأیید شما">
        {why.suggestion_fa}
      </Alert>
      <p className="text-[11px] leading-6 text-ink-faint">{why.note_fa}</p>
    </div>
  );
}

/** §5.3 «روند» — خط زمان رویدادهای یادگیری همین دانش‌آموز. */
function TimelineView({ tl }: { tl: Timeline }) {
  if (tl.events.length === 0) {
    return (
      <EmptyState
        compact
        title="رویدادی برای این دانش‌آموز ثبت نشده"
        description="با ثبت خطا، شاهد، آزمون و برنامه، خط زمان پر می‌شود."
      />
    );
  }
  return (
    <div className="space-y-3">
      <ol className="space-y-2">
        {tl.events.map((e, i) => (
          <li key={i} className="flex flex-wrap items-start gap-3 rounded-xl border border-line-soft bg-surface px-3 py-2.5">
            <Badge tone={EVENT_TONE[e.tone] ?? "neutral"}>{EVENT_KIND_FA[e.kind] ?? e.kind}</Badge>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold text-ink">{e.title_fa}</p>
              <p className="mt-0.5 text-[11px] leading-5 text-ink-muted">{e.detail_fa}</p>
            </div>
            <span className="num shrink-0 text-[10px] text-ink-faint">{fmtDateTime(e.at)}</span>
          </li>
        ))}
      </ol>
      <p className="text-[11px] leading-6 text-ink-faint">{tl.note_fa}</p>
    </div>
  );
}
