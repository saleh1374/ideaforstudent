"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getToken } from "@/lib/api";
import { NEED_FA, NEED_COLOR, CAUSE_SHORT, STATUS_FA, fa, subjectFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/ui/table";
import { ProgressBar } from "@/components/ui/progress";
import { BarChart, DonutChart } from "@/components/ui/charts";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconChart, IconLayers, IconTarget, IconUsers } from "@/components/ui/icons";
import { AssessmentSection } from "./assessment-section";
import { ExamBuilderSection } from "./exam-builder-section";
import { ExamAnalysisSection } from "./exam-analysis-section";
import { CopilotSection } from "./copilot-section";

type ClassInfo = {
  class_id: number;
  name: string;
  grade: string;
  subject: string;
  school_name: string | null;
  students_count: number;
};

type RadarRow = {
  topic_id: number;
  title: string;
  avg_mastery: number;
  avg_retention: number;
  status: string;
  weak_count: number;
  students_with_data: number;
  total_students: number;
  error_causes: Record<string, number>;
  prereq_weak: boolean;
};

type RootCause = {
  topic: { topic_id: number; title: string; mastery: number | null };
  chain: { topic_id: number; title: string; mastery: number | null }[];
  root: { topic_id: number; title: string; mastery: number | null };
  root_reason: string;
  diagnosis: string;
};

type Group = {
  need: string;
  label: string;
  action: string;
  students: {
    student_id: number;
    full_name: string;
    mastery: number;
    retention: number;
    progress_pct: number | null;
    repeat_errors: number;
    prereq_weak: boolean;
  }[];
};

export default function TeacherPage() {
  const [view, setView] = useState<"class" | "assessment" | "builder" | "analysis" | "copilot">("class");
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [activeClass, setActiveClass] = useState<number | null>(null);
  const [radar, setRadar] = useState<RadarRow[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [rootCause, setRootCause] = useState<RootCause | null>(null);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);

  const loadClass = useCallback(async (cid: number) => {
    setActiveClass(cid);
    setRootCause(null);
    setRadar([]);
    setGroups([]);
    try {
      const r = await api<{ rows: RadarRow[] }>(`/teacher/classes/${cid}/radar`);
      setRadar(r.rows);
      const g = await api<{ groups: Group[] }>(`/teacher/classes/${cid}/groups`);
      setGroups(g.groups.filter((x) => x.students.length > 0));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
      toast(e instanceof Error ? e.message : "خطا در بارگذاری کلاس", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ classes: ClassInfo[] }>("/teacher/me/classes")
      .then((d) => {
        setClasses(d.classes);
        if (d.classes.length > 0) loadClass(d.classes[0].class_id);
        else setLoading(false);
      })
      .catch((e) => {
        setMsg(e instanceof Error ? e.message : "خطا");
        setLoading(false);
      });
  }, [loadClass]);

  async function openRootCause(topicId: number) {
    if (!activeClass) return;
    setRootCause(null);
    try {
      setRootCause(await api<RootCause>(`/teacher/classes/${activeClass}/root-cause/${topicId}`));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "خطا");
    }
  }

  const stats = useMemo(() => {
    const withData = radar.filter((r) => r.students_with_data > 0);
    const avgMastery = withData.length > 0 ? withData.reduce((s, r) => s + r.avg_mastery, 0) / withData.length : null;
    const weakTopics = radar.filter((r) => r.status === "weak" || r.status === "critical").length;
    const prereqWeak = radar.filter((r) => r.prereq_weak).length;
    const weakStudents = radar.reduce((s, r) => s + r.weak_count, 0);
    return { avgMastery, weakTopics, prereqWeak, weakStudents };
  }, [radar]);

  const chartData = useMemo(
    () =>
      [...radar]
        .filter((r) => r.students_with_data > 0)
        .sort((a, b) => a.avg_mastery - b.avg_mastery)
        .slice(0, 6)
        .map((r) => ({ label: r.title, value: Math.round(r.avg_mastery), color: r.avg_mastery < 50 ? "#f43f5e" : r.avg_mastery < 70 ? "#f59e0b" : "#6366f1" })),
    [radar]
  );

  const statusData = useMemo(() => {
    const counts: Record<string, number> = {};
    radar.forEach((r) => {
      counts[r.status] = (counts[r.status] ?? 0) + 1;
    });
    const colors: Record<string, string> = {
      mastered: "#10b981",
      consolidating: "#0ea5e9",
      weak: "#f59e0b",
      critical: "#f43f5e",
      unknown: "#cbd5e1",
    };
    return Object.entries(counts).map(([k, v]) => ({ label: STATUS_FA[k] ?? k, value: v, color: colors[k] }));
  }, [radar]);

  const columns: Column<RadarRow>[] = [
    {
      key: "title",
      header: "مبحث",
      render: (row) => (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{row.title}</span>
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
          <span className="num mb-1 block text-xs font-bold text-ink">{fa(row.avg_mastery)}٪</span>
          <ProgressBar value={row.avg_mastery} size="sm" tone={row.avg_mastery < 50 ? "danger" : row.avg_mastery < 70 ? "warning" : "success"} />
        </div>
      ),
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num font-semibold">{fa(row.avg_retention * 100)}٪</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => <Badge tone={statusTone(row.status)}>{STATUS_FA[row.status] ?? row.status}</Badge>,
    },
    {
      key: "weak",
      header: "نیازمند توجه",
      align: "center",
      render: (row) => (
        <span className={`num font-bold ${row.weak_count > 0 ? "text-danger-600" : "text-ink-faint"}`}>
          {fa(row.weak_count)} / {fa(row.total_students)}
        </span>
      ),
    },
    {
      key: "causes",
      header: "علت خطاها",
      align: "center",
      render: (row) => (
        <div className="flex flex-wrap justify-center gap-1">
          {Object.entries(row.error_causes).map(([c, n]) => (
            <span key={c} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-ink-muted">
              {CAUSE_SHORT[c] ?? c}: {fa(n)}
            </span>
          ))}
        </div>
      ),
    },
  ];

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="پنل معلم — هوش کلاس"
          description="رادار مباحث، ریشه‌یابی ضعف و گروه‌بندی نیاز دانش‌آموزان — بدون رتبه‌بندی."
          crumbs={[{ label: "دانشیار" }, { label: "آموزشی" }, { label: "هوش کلاس" }]}
          badge={classes.length > 0 ? <Badge tone="primary" dot>{fa(classes.length)} کلاس</Badge> : undefined}
        />

        <Tabs
          items={[
            { key: "class", label: "هوش کلاس", count: classes.length },
            { key: "assessment", label: "ارزیابی صلاحیت" },
            { key: "builder", label: "سازنده آزمون" },
            { key: "analysis", label: "تحلیل آزمون" },
            { key: "copilot", label: "دستیار هوشمند" },
          ]}
          value={view}
          onChange={(k) => setView(k as "class" | "assessment" | "builder" | "analysis" | "copilot")}
        />

        {view === "assessment" && <AssessmentSection />}

        {view === "builder" && <ExamBuilderSection />}

        {view === "analysis" && <ExamAnalysisSection />}

        {view === "copilot" && <CopilotSection classId={activeClass} />}

        {view === "class" && msg && classes.length === 0 && <Alert variant="danger" title="خطا">{msg}</Alert>}

        {view === "class" && classes.length === 0 && !msg && (
          <EmptyState
            icon={<IconUsers size={26} />}
            title="کلاسی به شما تخصیص نیافته است"
            description="هنوز کلاسی برای این حساب ثبت نشده؛ با مدیر مدرسه هماهنگ کنید."
          />
        )}

        {view === "class" && classes.length > 0 && (
          <>
            {/* class switcher */}
            <Tabs
              items={classes.map((c) => ({
                key: String(c.class_id),
                label: `کلاس ${c.name} — ${subjectFa(c.subject)}`,
                count: c.students_count,
              }))}
              value={String(activeClass ?? "")}
              onChange={(k) => loadClass(Number(k))}
            />

            {/* KPIs */}
            <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard
                label="میانگین تسط کلاس"
                value={stats.avgMastery !== null ? `${fa(stats.avgMastery, 1)}٪` : "—"}
                tone="primary"
                icon={<IconTarget size={20} />}
                hint="میانگین مباحث دارای داده"
              />
              <StatCard label="مباحث نیازمند کار" value={fa(stats.weakTopics)} tone="danger" icon={<IconAlert size={20} />} hint="ضعیف + بحرانی" />
              <StatCard label="پیش‌نیاز ضعیف" value={fa(stats.prereqWeak)} tone="warning" icon={<IconLayers size={20} />} hint="نیازمند ریشه‌یابی" />
              <StatCard label="دانش‌آموزان نیازمند توجه" value={fa(stats.weakStudents)} tone="accent" icon={<IconUsers size={20} />} hint="جمع امتیازها در هر مبحث" />
            </section>

            {msg && <Alert variant="warning">{msg}</Alert>}

            {/* charts */}
            <section className="grid gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader
                  title="ضعیف‌ترین مباحث کلاس"
                  subtitle="۶ مبحث با کمترین میانگین تسط — برای برنامه ترمیم گروهی"
                  icon={<IconChart size={17} />}
                />
                {chartData.length > 0 ? (
                  <BarChart data={chartData} height={230} id="teacher-weak" format={(v) => `${fa(v)}٪`} />
                ) : (
                  <EmptyState compact title="داده‌ای برای نمودار نیست" description="پس از ثبت آزمون، نمودار نمایش داده می‌شود." />
                )}
              </Card>
              <Card>
                <CardHeader title="توزیع وضعیت مباحث" icon={<IconChart size={17} />} />
                {statusData.length > 0 ? (
                  <DonutChart data={statusData} size={140} thickness={20} centerSubtitle="مبحث" />
                ) : (
                  <EmptyState compact title="مبحثی ثبت نشده" />
                )}
              </Card>
            </section>

            {/* radar table */}
            <Section title="رادار مباحث کلاس" subtitle="مرتب بر اساس ضعف — روی هر ردیف کلیک کن تا ریشه ضعف با گراف پیش‌نیاز باز شود.">
              <DataTable
                columns={columns}
                rows={radar}
                keyOf={(r) => r.topic_id}
                loading={loading}
                onRowClick={(r) => openRootCause(r.topic_id)}
                empty={<EmptyState compact title="هنوز داده‌ای برای این کلاس ثبت نشده" description="با اولین آزمون، رادار مباحث پر می‌شود." />}
              />
            </Section>

            {/* root cause */}
            {rootCause && (
              <Card variant="brand" className="animate-fade-in-up space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-extrabold text-primary-900">
                    ریشه‌یابی: {rootCause.topic.title}{" "}
                    <span className="num text-xs font-bold text-primary-600">({rootCause.topic.mastery !== null ? `${fa(rootCause.topic.mastery)}٪` : "بدون داده"})</span>
                  </h2>
                  <button
                    onClick={() => setRootCause(null)}
                    className="rounded-lg px-2 py-1 text-xs font-semibold text-primary-700 transition hover:bg-white"
                  >
                    بستن
                  </button>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-xs">
                  {rootCause.chain.map((step, i) => (
                    <span key={step.topic_id} className="flex items-center gap-2">
                      {i > 0 && <span className="text-primary-300">←</span>}
                      <Badge
                        tone={i === rootCause.chain.length - 1 && rootCause.root_reason === "prerequisite" ? "danger" : "neutral"}
                      >
                        {step.title} — {step.mastery !== null ? `${fa(step.mastery)}٪` : "بدون داده"}
                      </Badge>
                    </span>
                  ))}
                </div>

                <Alert variant={rootCause.root_reason === "prerequisite" ? "warning" : "info"} title="تشخیص">
                  {rootCause.diagnosis}
                </Alert>
              </Card>
            )}

            {/* need groups */}
            <Section
              title="گروه‌بندی نیاز — نه رتبه"
              subtitle="دو دانش‌آموز با نمره یکسان می‌توانند نیاز کاملاً متفاوت داشته باشند."
            >
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {groups.map((g) => (
                  <Card key={g.need} className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className={`badge ${NEED_COLOR[g.need]}`}>{NEED_FA[g.need] ?? g.need}</span>
                      <span className="num text-xs text-ink-faint">{fa(g.students.length)} نفر</span>
                    </div>
                    <p className="rounded-xl bg-surface-sunken px-3 py-2 text-[11px] leading-6 text-ink-muted">
                      <b className="text-ink">اقدام پیشنهادی:</b> {g.action}
                    </p>
                    <ul className="divide-y divide-line-soft">
                      {g.students.map((s) => (
                        <li key={s.student_id} className="flex items-center justify-between gap-3 py-2 text-xs">
                          <span className="flex items-center gap-2 font-semibold text-ink">
                            {s.full_name}
                            {s.prereq_weak && <span className="text-warning-500" title="پیش‌نیاز ضعیف">⚠</span>}
                          </span>
                          <span className="num text-ink-faint">
                            تسط {fa(s.mastery)}٪ · ماندگاری {fa(s.retention * 100)}٪
                            {s.repeat_errors > 0 && <span className="text-danger-500"> · {fa(s.repeat_errors)} خطای باز</span>}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </Card>
                ))}
                {groups.length === 0 && !loading && (
                  <div className="md:col-span-2">
                    <EmptyState
                      compact
                      icon={<IconLayers size={24} />}
                      title="هنوز گروهی تشکیل نشده"
                      description="داده کافی نیست؛ با ثبت آزمون و تمرین، گروه‌های نیاز ساخته می‌شوند."
                    />
                  </div>
                )}
              </div>
            </Section>
          </>
        )}
      </div>
    </AppShell>
  );
}
