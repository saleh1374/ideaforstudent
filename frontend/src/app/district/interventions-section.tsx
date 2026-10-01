"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { GRADE_FA, fa, gradeFa } from "@/lib/labels";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { ProgressBar } from "@/components/ui/progress";
import { StatCard } from "@/components/ui/stat";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { Tabs } from "@/components/ui/tabs";
import {
  IconAlert,
  IconCheckCircle,
  IconClock,
  IconExam,
  IconPlus,
  IconRefresh,
  IconSchool,
  IconTarget,
} from "@/components/ui/icons";

/* ------------------------- نگاشت‌های محلی (lib مشترک قابل ویرایش نیست) ------------------------- */

const IV_TYPE_FA: Record<string, string> = {
  course: "دوره آموزشی",
  supervision: "نظارت",
  replacement: "تعویض",
  program: "برنامه آموزشی",
};

const IV_STATUS_FA: Record<string, string> = {
  active: "در حال اجرا",
  closed: "بسته‌شده",
  cancelled: "لغوشده",
};

const IV_STATUS_TONE: Record<string, Tone> = {
  active: "info",
  closed: "success",
  cancelled: "warning",
};

const VERDICT_TONE: Record<string, Tone> = {
  pending: "neutral",
  needs_retention: "warning",
  effective: "success",
  ineffective: "danger",
  needs_attention: "warning",
};

const MISSION_STATUS_TONE: Record<string, Tone> = {
  active: "info",
  completed: "success",
  overdue: "danger",
  suppressed: "neutral",
};

/* ------------------------- انواع پاسخ سرور ------------------------- */

type SchoolLite = { id: number; name: string };

type TopicOpt = { id: number; title: string; subject: string; grade: string };

type InterventionRow = {
  id: number;
  title_fa: string;
  type: string;
  type_fa: string;
  topic_id: number | null;
  topic_title: string | null;
  grade: string | null;
  start_date: string | null;
  end_date: string | null;
  before_mastery: number | null;
  after_mastery: number | null;
  retention_mastery: number | null;
  status: string;
  status_fa: string;
  notes: string | null;
  schools: { id: number; name: string | null }[];
  created_at: string;
  verdict: string;
  verdict_fa: string;
  delta_after: number | null;
  delta_retention: number | null;
  next_stage: "after" | "retention" | null;
  min_gain: number;
  retention_days: number;
};

type MissionSchoolRow = {
  school_id: number;
  name: string | null;
  students_with_data: number;
  avg_mastery: number | null;
  suppressed: boolean;
  min_group: number;
  completed: boolean;
  status: string;
  status_fa: string;
};

type MissionRow = {
  id: number;
  title_fa: string;
  goal: string;
  topic_id: number;
  topic_title: string | null;
  target_mastery: number;
  deadline: string;
  created_at: string;
  schools: MissionSchoolRow[];
  schools_count: number;
  completed_count: number;
  suppressed_count: number;
  progress_avg: number | null;
  status: string;
  status_fa: string;
  days_left: number;
  note_fa: string;
};

/* ------------------------- بخش مداخله و مأموریت‌ها (§25–§27) ------------------------- */

export function InterventionsSection() {
  const [view, setView] = useState("interventions");

  const [schools, setSchools] = useState<SchoolLite[]>([]);
  const [topics, setTopics] = useState<TopicOpt[]>([]);

  // مداخله‌ها
  const [interventions, setInterventions] = useState<InterventionRow[]>([]);
  const [ivLoading, setIvLoading] = useState(true);
  const [ivError, setIvError] = useState("");
  const [ivForm, setIvForm] = useState({
    title: "",
    type: "course",
    topic_id: "",
    grade: "",
    start: "",
    end: "",
    before: "",
    notes: "",
  });
  const [ivSchools, setIvSchools] = useState<number[]>([]);
  const [ivCreating, setIvCreating] = useState(false);

  // مأموریت‌ها
  const [missions, setMissions] = useState<MissionRow[]>([]);
  const [msLoading, setMsLoading] = useState(false);
  const [msError, setMsError] = useState("");
  const [msForm, setMsForm] = useState({
    title: "",
    goal: "",
    topic_id: "",
    target: "65",
    deadline: "",
  });
  const [msSchools, setMsSchools] = useState<number[]>([]);
  const [msCreating, setMsCreating] = useState(false);

  // مودال ثبت اندازه‌گیری
  const [measTarget, setMeasTarget] = useState<InterventionRow | null>(null);
  const [measStage, setMeasStage] = useState<"after" | "retention">("after");
  const [measValue, setMeasValue] = useState("");
  const [measBusy, setMeasBusy] = useState(false);

  // مودال داشبورد مأموریت
  const [missionTarget, setMissionTarget] = useState<MissionRow | null>(null);
  const [ivBusy, setIvBusy] = useState(false);

  useEffect(() => {
    api<{ schools: SchoolLite[] }>("/district/me/schools")
      .then((d) => setSchools(d.schools))
      .catch(() => setSchools([]));
    api<{ topics: TopicOpt[] }>("/district/topics")
      .then((d) => setTopics(d.topics))
      .catch(() => setTopics([]));
  }, []);

  const loadIv = useCallback(async () => {
    setIvLoading(true);
    try {
      const res = await api<{ total: number; interventions: InterventionRow[] }>("/district/interventions");
      setInterventions(res.interventions);
      setIvError("");
    } catch (e) {
      setIvError(e instanceof Error ? e.message : "خطا در دریافت مداخله‌ها");
    } finally {
      setIvLoading(false);
    }
  }, []);

  const loadMs = useCallback(async () => {
    setMsLoading(true);
    try {
      const res = await api<{ total: number; missions: MissionRow[] }>("/district/missions");
      setMissions(res.missions);
      setMsError("");
    } catch (e) {
      setMsError(e instanceof Error ? e.message : "خطا در دریافت مأموریت‌ها");
    } finally {
      setMsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadIv();
  }, [loadIv]);

  useEffect(() => {
    if (view === "missions" && missions.length === 0 && !msLoading) loadMs();
  }, [view, missions.length, msLoading, loadMs]);

  /* ------------------------- عملیات مداخله ------------------------- */

  async function createIntervention(e: React.FormEvent) {
    e.preventDefault();
    if (!ivForm.title.trim()) {
      toast("عنوان مداخله الزامی است.", "warning");
      return;
    }
    if (ivSchools.length === 0) {
      toast("دست‌کم یک مدرسه را انتخاب کنید.", "warning");
      return;
    }
    setIvCreating(true);
    try {
      await api("/district/interventions", {
        method: "POST",
        json: {
          title_fa: ivForm.title.trim(),
          type: ivForm.type,
          school_ids: ivSchools,
          topic_id: ivForm.topic_id ? Number(ivForm.topic_id) : null,
          grade: ivForm.grade || null,
          start_date: ivForm.start || null,
          end_date: ivForm.end || null,
          before_mastery: ivForm.before !== "" ? Number(ivForm.before) : null,
          notes: ivForm.notes.trim() || null,
        },
      });
      toast(`مداخله «${ivForm.title.trim()}» ثبت شد.`, "success");
      setIvForm({ title: "", type: "course", topic_id: "", grade: "", start: "", end: "", before: "", notes: "" });
      setIvSchools([]);
      await loadIv();
    } catch (err) {
      // 400 (زیر حداقل جمعیت / مقدار تسط) و 404 مبحث — همه فارسی
      toast(err instanceof Error ? err.message : "خطا در ثبت مداخله", "error");
    } finally {
      setIvCreating(false);
    }
  }

  function openMeasurement(row: InterventionRow) {
    setMeasTarget(row);
    setMeasStage(row.next_stage ?? "after");
    setMeasValue("");
  }

  async function recordMeasurement() {
    if (!measTarget) return;
    const value = Number(measValue);
    if (measValue === "" || Number.isNaN(value) || value < 0 || value > 100) {
      toast("مقدار تسط باید بین ۰ تا ۱۰۰ باشد.", "warning");
      return;
    }
    setMeasBusy(true);
    try {
      await api(`/district/interventions/${measTarget.id}`, {
        method: "PATCH",
        json: { stage: measStage, mastery: value },
      });
      toast(
        measStage === "after" ? "سنجش «پس از مداخله» ثبت شد." : "سنجش «ماندگاری» ثبت شد.",
        "success"
      );
      setMeasTarget(null);
      await loadIv();
    } catch (e) {
      // 409 برای بسته بودن یا نبودن سنجش قبلی
      toast(e instanceof Error ? e.message : "خطا در ثبت اندازه‌گیری", "error");
    } finally {
      setMeasBusy(false);
    }
  }

  async function setIvStatus(row: InterventionRow, status: string) {
    setIvBusy(true);
    try {
      await api(`/district/interventions/${row.id}`, { method: "PATCH", json: { status } });
      toast(`وضعیت مداخله: ${IV_STATUS_FA[status] ?? status}`, "success");
      await loadIv();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در تغییر وضعیت", "error");
    } finally {
      setIvBusy(false);
    }
  }

  /* ------------------------- عملیات مأموریت ------------------------- */

  async function createMission(e: React.FormEvent) {
    e.preventDefault();
    if (!msForm.title.trim()) {
      toast("عنوان مأموریت الزامی است.", "warning");
      return;
    }
    if (!msForm.goal.trim()) {
      toast("بیانیه هدف الزامی است.", "warning");
      return;
    }
    if (!msForm.topic_id) {
      toast("مبحث هدف را انتخاب کنید.", "warning");
      return;
    }
    if (msSchools.length === 0) {
      toast("دست‌کم یک مدرسه را انتخاب کنید.", "warning");
      return;
    }
    const target = Number(msForm.target);
    if (Number.isNaN(target) || target < 0 || target > 100) {
      toast("هدف تسط باید بین ۰ تا ۱۰۰ باشد.", "warning");
      return;
    }
    setMsCreating(true);
    try {
      await api("/district/missions", {
        method: "POST",
        json: {
          title_fa: msForm.title.trim(),
          goal: msForm.goal.trim(),
          topic_id: Number(msForm.topic_id),
          target_mastery: target,
          school_ids: msSchools,
          deadline: msForm.deadline || null,
        },
      });
      toast(`مأموریت «${msForm.title.trim()}» ثبت شد.`, "success");
      setMsForm({ title: "", goal: "", topic_id: "", target: "65", deadline: "" });
      setMsSchools([]);
      await loadMs();
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ثبت مأموریت", "error");
    } finally {
      setMsCreating(false);
    }
  }

  /* ------------------------- ستون‌های جدول‌ها ------------------------- */

  const missionColumns: Column<MissionRow>[] = [
    {
      key: "title",
      header: "مأموریت",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.title_fa}</p>
          <p className="text-[11px] text-ink-faint">{row.topic_title ?? "—"}</p>
        </div>
      ),
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={MISSION_STATUS_TONE[row.status] ?? "neutral"} dot>
          {row.status_fa}
        </Badge>
      ),
    },
    {
      key: "target",
      header: "هدف",
      align: "center",
      render: (row) => <span className="num text-xs font-bold text-ink">≥ {fa(row.target_mastery)}٪</span>,
    },
    {
      key: "progress",
      header: "پیشرفت مدارس",
      render: (row) => (
        <div className="space-y-1">
          <span className="num text-[11px] font-semibold text-ink">
            {fa(row.completed_count)} از {fa(row.schools_count)} مدرسه تکمیل
            {row.progress_avg !== null && ` · میانگین ${fa(row.progress_avg)}٪`}
          </span>
          <ProgressBar
            value={row.schools_count === 0 ? 0 : (100 * row.completed_count) / row.schools_count}
            size="sm"
            tone={row.status === "completed" ? "success" : row.status === "overdue" ? "danger" : "primary"}
          />
        </div>
      ),
    },
    {
      key: "deadline",
      header: "مهلت",
      align: "center",
      render: (row) => (
        <span className="num text-[11px] text-ink-faint">
          {faDate(row.deadline)}
          <br />
          {row.days_left >= 0 ? `${fa(row.days_left)} روز مانده` : `${fa(Math.abs(row.days_left))} روز گذشته`}
        </span>
      ),
    },
    {
      key: "act",
      header: "",
      align: "end",
      render: (row) => (
        <Button size="sm" variant="soft" onClick={() => setMissionTarget(row)}>
          داشبورد پیشرفت
        </Button>
      ),
    },
  ];

  const missionSchoolColumns: Column<MissionSchoolRow>[] = [
    { key: "name", header: "مدرسه", render: (row) => <span className="font-semibold text-ink">{row.name ?? "—"}</span> },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={MISSION_STATUS_TONE[row.status] ?? "neutral"} dot>
          {row.status_fa}
        </Badge>
      ),
    },
    {
      key: "mastery",
      header: "میانگین تسط",
      render: (row) =>
        row.suppressed || row.avg_mastery === null ? (
          <span className="text-[11px] text-ink-faint">
            زیر حد نصاب ({fa(row.students_with_data)}/{fa(row.min_group)} دانش‌آموز دارای داده)
          </span>
        ) : (
          <div className="space-y-1">
            <span className="num text-xs font-bold text-ink">{fa(row.avg_mastery)}٪</span>
            <ProgressBar
              value={row.avg_mastery}
              size="sm"
              tone={row.completed ? "success" : row.avg_mastery >= 50 ? "warning" : "danger"}
            />
          </div>
        ),
    },
    {
      key: "done",
      header: "هدف",
      align: "center",
      render: (row) =>
        row.completed ? (
          <Badge tone="success">رسیده</Badge>
        ) : row.suppressed ? (
          <Badge tone="neutral">—</Badge>
        ) : (
          <Badge tone="warning">در دسترس</Badge>
        ),
    },
  ];

  /* ------------------------- رندر ------------------------- */

  return (
    <Section
      title="مداخله و مأموریت‌ها"
      subtitle="چرخه کامل مداخله آموزشی با سنجش اثر (پیش ← بازآزمون ← ماندگاری) و مأموریت‌های هدفمند برای مدارس (§25–§27)."
      action={
        <Button size="sm" variant="soft" icon={<IconRefresh size={14} />} onClick={() => (view === "missions" ? loadMs() : loadIv())}>
          به‌روزرسانی
        </Button>
      }
    >
      <Tabs
        items={[
          { key: "interventions", label: "مداخله‌های آموزشی", count: interventions.length },
          { key: "missions", label: "مأموریت مدارس", count: missions.length },
        ]}
        value={view}
        onChange={setView}
      />

      {/* ================= مداخله‌ها (§25–§26) ================= */}
      {view === "interventions" && (
        <>
          <Card>
            <CardHeader
              title="ثبت مداخله"
              subtitle="اگر «پیش از مداخله» خالی بماند و مبحث مشخص باشد، سرور از تجمیع تسط می‌خواند؛ زیر حداقل جمعیت مقدار دستی بخواهید."
              icon={<IconTarget size={17} />}
            />
            <form onSubmit={createIntervention} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="عنوان مداخله" required>
                <Input
                  value={ivForm.title}
                  onChange={(e) => setIvForm({ ...ivForm, title: e.target.value })}
                  placeholder="مثلاً برنامه جبر ترمیمی"
                />
              </Field>
              <Field label="نوع مداخله" required>
                <Select value={ivForm.type} onChange={(e) => setIvForm({ ...ivForm, type: e.target.value })}>
                  {Object.entries(IV_TYPE_FA).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="مبحث هدف" hint="برای سنجش خودکار «پیش از مداخله»">
                <Select value={ivForm.topic_id} onChange={(e) => setIvForm({ ...ivForm, topic_id: e.target.value })}>
                  <option value="">بدون مبحث مشخص</option>
                  {topics.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="پایه (اختیاری)">
                <Select value={ivForm.grade} onChange={(e) => setIvForm({ ...ivForm, grade: e.target.value })}>
                  <option value="">همه پایه‌ها</option>
                  {Object.entries(GRADE_FA).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="تاریخ شروع">
                <Input type="date" value={ivForm.start} onChange={(e) => setIvForm({ ...ivForm, start: e.target.value })} />
              </Field>
              <Field label="تاریخ پایان" hint="خالی → ۲ هفته پس از شروع">
                <Input type="date" value={ivForm.end} onChange={(e) => setIvForm({ ...ivForm, end: e.target.value })} />
              </Field>
              <Field label="تسط «پیش از مداخله» (٪)" hint="خالی → خودکار از تجمیع مبحث">
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={ivForm.before}
                  onChange={(e) => setIvForm({ ...ivForm, before: e.target.value })}
                  placeholder="مثلاً ۴۳"
                />
              </Field>
              <Field label="توضیح">
                <Input
                  value={ivForm.notes}
                  onChange={(e) => setIvForm({ ...ivForm, notes: e.target.value })}
                  placeholder="شرح کوتاه برنامه…"
                />
              </Field>

              <div className="sm:col-span-2 lg:col-span-4">
                <div className="rounded-xl border border-line bg-surface-sunken p-3.5">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-xs font-bold text-ink">مدارس هدف</p>
                    <div className="flex gap-2">
                      <Button type="button" size="sm" variant="ghost" onClick={() => setIvSchools(schools.map((s) => s.id))}>
                        همه
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setIvSchools([])}>
                        هیچ
                      </Button>
                    </div>
                  </div>
                  {schools.length === 0 ? (
                    <p className="text-[11px] text-ink-faint">مدرسه‌ای برای انتخاب یافت نشد.</p>
                  ) : (
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                      {schools.map((sc) => (
                        <label
                          key={sc.id}
                          className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-muted transition hover:bg-white/70"
                        >
                          <input
                            type="checkbox"
                            checked={ivSchools.includes(sc.id)}
                            onChange={() =>
                              setIvSchools((prev) =>
                                prev.includes(sc.id) ? prev.filter((x) => x !== sc.id) : [...prev, sc.id]
                              )
                            }
                            className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                          />
                          {sc.name}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="sm:col-span-2 lg:col-span-4">
                <Button type="submit" loading={ivCreating} icon={<IconPlus size={15} />}>
                  ثبت مداخله
                </Button>
              </div>
            </form>
          </Card>

          {ivError && <Alert variant="danger" title="خطا">{ivError}</Alert>}

          {ivLoading ? (
            <SkeletonTable rows={3} cols={4} />
          ) : interventions.length === 0 ? (
            <EmptyState
              icon={<IconTarget size={26} />}
              title="مداخله‌ای ثبت نشده"
              description="با فرم بالا اولین مداخله آموزشی ناحیه را تعریف کنید و اثر آن را در سه مرحله بسنجید."
            />
          ) : (
            <div className="space-y-3">
              {interventions.map((iv) => (
                <Card key={iv.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-bold text-ink">{iv.title_fa}</p>
                        <Badge tone="primary">{iv.type_fa || IV_TYPE_FA[iv.type] || iv.type}</Badge>
                        <Badge tone={IV_STATUS_TONE[iv.status] ?? "neutral"} dot>
                          {iv.status_fa}
                        </Badge>
                        <Badge tone={VERDICT_TONE[iv.verdict] ?? "neutral"}>{iv.verdict_fa}</Badge>
                      </div>
                      <p className="text-[11px] text-ink-faint">
                        {iv.topic_title ?? "بدون مبحث"}
                        {iv.grade ? ` · ${gradeFa(iv.grade)}` : ""} · {fa(iv.schools.length)} مدرسه
                        {iv.start_date ? ` · ${faDate(iv.start_date)}` : ""}
                        {iv.end_date ? ` تا ${faDate(iv.end_date)}` : ""}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {iv.schools.map((sc) => (
                          <Badge key={sc.id} tone="neutral">
                            {sc.name ?? `مدرسه ${fa(sc.id)}`}
                          </Badge>
                        ))}
                      </div>
                      {iv.notes && <p className="text-[11px] leading-5 text-ink-muted">{iv.notes}</p>}
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2">
                      {iv.status === "active" && iv.next_stage && (
                        <Button size="sm" variant="primary" onClick={() => openMeasurement(iv)}>
                          {iv.next_stage === "after" ? "ثبت بازآزمون" : "ثبت سنجش ماندگاری"}
                        </Button>
                      )}
                      {iv.status === "active" && (
                        <>
                          <Button size="sm" variant="soft" loading={ivBusy} onClick={() => setIvStatus(iv, "closed")}>
                            بستن
                          </Button>
                          <Button size="sm" variant="ghost" loading={ivBusy} onClick={() => setIvStatus(iv, "cancelled")}>
                            لغو
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* چرخه Before → After → Retention */}
                  <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <MeasureCard label="پیش از مداخله" value={iv.before_mastery} tone="danger" />
                    <MeasureCard
                      label="پس از مداخله (بازآزمون)"
                      value={iv.after_mastery}
                      delta={iv.delta_after}
                      minGain={iv.min_gain}
                      tone="warning"
                    />
                    <MeasureCard
                      label={`ماندگاری (~${fa(iv.retention_days)} روز بعد)`}
                      value={iv.retention_mastery}
                      delta={iv.delta_retention}
                      minGain={iv.min_gain}
                      tone="success"
                    />
                  </div>

                  {iv.verdict === "ineffective" && (
                    <Alert variant="danger" title="سنجش اثر">
                      بازآزمون بهبودی کافی نشان نداد (کمتر از {fa(iv.min_gain)}٪ رشد)؛ مداخله بی‌اثر ارزیابی شد.
                    </Alert>
                  )}
                  {iv.verdict === "needs_attention" && (
                    <Alert variant="warning" title="سنجش اثر">
                      رشد اولیه ثبت شد اما در سنجش ماندگاری حفظ نشد؛ به مداخله توجه کنید.
                    </Alert>
                  )}
                  {iv.verdict === "effective" && (
                    <Alert variant="success" title="سنجش اثر">
                      رشد هم پس از بازآزمون و هم در سنجش ماندگاری بالای {fa(iv.min_gain)}٪ ماند؛ مداخله اثر داشته است.
                    </Alert>
                  )}
                </Card>
              ))}
            </div>
          )}
        </>
      )}

      {/* ================= مأموریت‌ها (§27) ================= */}
      {view === "missions" && (
        <>
          <Card>
            <CardHeader
              title="تعریف مأموریت"
              subtitle="«طی دو هفته، تسلط مبحث X به حداقل ۶۵٪ برسد» — پیشرفت هر مدرسه در داشبورد مجزا دنبال می‌شود."
              icon={<IconTarget size={17} />}
            />
            <form onSubmit={createMission} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="عنوان مأموریت" required>
                <Input
                  value={msForm.title}
                  onChange={(e) => setMsForm({ ...msForm, title: e.target.value })}
                  placeholder="مثلاً تثبیت مبحث معادلات"
                />
              </Field>
              <Field label="مبحث هدف" required>
                <Select value={msForm.topic_id} onChange={(e) => setMsForm({ ...msForm, topic_id: e.target.value })}>
                  <option value="">انتخاب مبحث…</option>
                  {topics.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="هدف تسط (٪)" required>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={msForm.target}
                  onChange={(e) => setMsForm({ ...msForm, target: e.target.value })}
                />
              </Field>
              <Field label="مهلت" hint="خالی → ۲ هفته از امروز">
                <Input type="date" value={msForm.deadline} onChange={(e) => setMsForm({ ...msForm, deadline: e.target.value })} />
              </Field>
              <Field label="بیانیه هدف" required className="sm:col-span-2 lg:col-span-4">
                <Textarea
                  value={msForm.goal}
                  onChange={(e) => setMsForm({ ...msForm, goal: e.target.value })}
                  placeholder="اقدامات لازم: درس ترمیمی، تمرین هدفمند، ارزیابی کوتاه، بازآزمون…"
                />
              </Field>

              <div className="sm:col-span-2 lg:col-span-4">
                <div className="rounded-xl border border-line bg-surface-sunken p-3.5">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-xs font-bold text-ink">مدارس هدف</p>
                    <div className="flex gap-2">
                      <Button type="button" size="sm" variant="ghost" onClick={() => setMsSchools(schools.map((s) => s.id))}>
                        همه
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setMsSchools([])}>
                        هیچ
                      </Button>
                    </div>
                  </div>
                  {schools.length === 0 ? (
                    <p className="text-[11px] text-ink-faint">مدرسه‌ای برای انتخاب یافت نشد.</p>
                  ) : (
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                      {schools.map((sc) => (
                        <label
                          key={sc.id}
                          className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-muted transition hover:bg-white/70"
                        >
                          <input
                            type="checkbox"
                            checked={msSchools.includes(sc.id)}
                            onChange={() =>
                              setMsSchools((prev) =>
                                prev.includes(sc.id) ? prev.filter((x) => x !== sc.id) : [...prev, sc.id]
                              )
                            }
                            className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                          />
                          {sc.name}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="sm:col-span-2 lg:col-span-4">
                <Button type="submit" loading={msCreating} icon={<IconPlus size={15} />}>
                  ثبت مأموریت
                </Button>
              </div>
            </form>
          </Card>

          {msError && <Alert variant="danger" title="خطا">{msError}</Alert>}

          {msLoading ? (
            <SkeletonTable rows={3} cols={5} />
          ) : missions.length === 0 ? (
            <EmptyState
              icon={<IconTarget size={26} />}
              title="مأموریتی ثبت نشده"
              description="با فرم بالا اولین مأموریت آموزشی را برای گروهی از مدارس تعریف کنید."
            />
          ) : (
            <DataTable
              columns={missionColumns}
              rows={missions}
              keyOf={(r) => r.id}
              empty={<EmptyState compact title="مأموریتی ثبت نشده" />}
            />
          )}
        </>
      )}

      {/* ---------- مودال ثبت اندازه‌گیری ---------- */}
      <Modal
        open={measTarget !== null}
        onClose={() => setMeasTarget(null)}
        title={measTarget ? `ثبت اندازه‌گیری — ${measTarget.title_fa}` : "ثبت اندازه‌گیری"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMeasTarget(null)}>
              انصراف
            </Button>
            <Button loading={measBusy} onClick={recordMeasurement}>
              ثبت
            </Button>
          </>
        }
      >
        {measTarget && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge tone="danger">پیش: {measTarget.before_mastery !== null ? `${fa(measTarget.before_mastery)}٪` : "—"}</Badge>
              <Badge tone="warning">پس: {measTarget.after_mastery !== null ? `${fa(measTarget.after_mastery)}٪` : "—"}</Badge>
              <Badge tone="success">
                ماندگاری: {measTarget.retention_mastery !== null ? `${fa(measTarget.retention_mastery)}٪` : "—"}
              </Badge>
            </div>

            <Field label="مرحله اندازه‌گیری" required>
              <Select value={measStage} onChange={(e) => setMeasStage(e.target.value as "after" | "retention")}>
                <option value="after">پس از مداخله (بازآزمون)</option>
                <option value="retention">ماندگاری (سنجش مجدد ~۳ هفته بعد)</option>
              </Select>
            </Field>
            <Field label="میانگین تسط مبحث در مدارس هدف (٪)" required hint="بین ۰ تا ۱۰۰">
              <Input
                type="number"
                min={0}
                max={100}
                value={measValue}
                onChange={(e) => setMeasValue(e.target.value)}
                placeholder="مثلاً ۶۷"
                autoFocus
              />
            </Field>

            {measStage === "retention" && measTarget.after_mastery === null && (
              <Alert variant="warning">ابتدا سنجش «پس از مداخله» را ثبت کنید؛ سرور در غیر این صورت 409 می‌دهد.</Alert>
            )}
          </div>
        )}
      </Modal>

      {/* ---------- مودال داشبورد مأموریت ---------- */}
      <Modal
        open={missionTarget !== null}
        onClose={() => setMissionTarget(null)}
        title={missionTarget ? `داشبورد پیشرفت — ${missionTarget.title_fa}` : "داشبورد پیشرفت"}
        size="lg"
        footer={
          <Button variant="ghost" onClick={() => setMissionTarget(null)}>
            بستن
          </Button>
        }
      >
        {missionTarget && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={MISSION_STATUS_TONE[missionTarget.status] ?? "neutral"} dot>
                {missionTarget.status_fa}
              </Badge>
              <Badge tone="neutral">{missionTarget.topic_title ?? "—"}</Badge>
              <Badge tone="info">هدف ≥ {fa(missionTarget.target_mastery)}٪</Badge>
              <Badge tone="neutral">
                <IconClock size={12} /> {faDate(missionTarget.deadline)}
              </Badge>
            </div>

            <Alert variant="info" title="هدف">
              {missionTarget.goal}
            </Alert>

            <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard
                label="مدارس تکمیل‌شده"
                value={`${fa(missionTarget.completed_count)} از ${fa(missionTarget.schools_count)}`}
                tone="success"
                icon={<IconCheckCircle size={20} />}
              />
              <StatCard
                label="میانگین پیشرفت"
                value={missionTarget.progress_avg !== null ? `${fa(missionTarget.progress_avg)}٪` : "زیر حد نصاب"}
                tone="primary"
                icon={<IconTarget size={20} />}
                hint={`هدف: ${fa(missionTarget.target_mastery)}٪`}
              />
              <StatCard
                label="زیر حد نصاب"
                value={fa(missionTarget.suppressed_count)}
                tone={missionTarget.suppressed_count > 0 ? "warning" : "success"}
                icon={<IconAlert size={20} />}
                hint="مدارس بدون حداقل جمعیت داده"
              />
              <StatCard
                label="باقی‌مانده تا مهلت"
                value={missionTarget.days_left >= 0 ? `${fa(missionTarget.days_left)} روز` : `${fa(Math.abs(missionTarget.days_left))} روز گذشته`}
                tone={missionTarget.days_left < 0 ? "danger" : "sky"}
                icon={<IconClock size={20} />}
              />
            </section>

            <div className="space-y-2">
              <p className="text-xs font-bold text-ink">پیشرفت به تفکیک مدرسه</p>
              <DataTable
                columns={missionSchoolColumns}
                rows={missionTarget.schools}
                keyOf={(r) => r.school_id}
                dense
                empty={<EmptyState compact title="مدرسه‌ای ثبت نشده" />}
              />
            </div>

            <p className="text-[11px] leading-6 text-ink-faint">{missionTarget.note_fa}</p>
          </div>
        )}
      </Modal>
    </Section>
  );
}

/* ------------------------- ابزارهای کمکی ------------------------- */

function MeasureCard({
  label,
  value,
  delta,
  minGain,
  tone,
}: {
  label: string;
  value: number | null;
  delta?: number | null;
  minGain?: number;
  tone: "danger" | "warning" | "success";
}) {
  const toneClass =
    tone === "danger" ? "text-danger-600" : tone === "warning" ? "text-warning-600" : "text-success-600";
  return (
    <div className="rounded-xl border border-line bg-surface-sunken px-3.5 py-3">
      <p className="text-[11px] font-semibold text-ink-muted">{label}</p>
      <p className={`num mt-1 text-lg font-extrabold ${value === null ? "text-ink-faint" : toneClass}`}>
        {value !== null ? `${fa(value)}٪` : "ثبت نشده"}
      </p>
      {delta !== undefined && delta !== null && (
        <p className="num mt-0.5 text-[11px] font-semibold text-ink-muted">
          {delta >= 0 ? "+" : ""}
          {fa(delta)}٪ نسبت به پیش
          {minGain !== undefined && (
            <span className={delta >= minGain ? "text-success-600" : "text-danger-600"}>
              {" "}
              ({delta >= minGain ? "بالای حد" : "زیر حد"})
            </span>
          )}
        </p>
      )}
    </div>
  );
}

function faDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fa-IR");
}
