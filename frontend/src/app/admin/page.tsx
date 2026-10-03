"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getToken } from "@/lib/api";
import { CAUSE_SHORT, fa, subjectFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Modal } from "@/components/ui/modal";
import { useTabParam } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/ui/table";
import { BarChart, DonutChart } from "@/components/ui/charts";
import { SkeletonStats } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { Suspense } from "react";
import {
  IconAlert,
  IconChart,
  IconCheckCircle,
  IconLayers,
  IconRefresh,
  IconShield,
  IconTarget,
  IconUsers,
} from "@/components/ui/icons";
import { EmploymentSection } from "./employment-section";
import { AdmissionsSection } from "./admissions-section";
import { TeachersCompareSection } from "./teachers-compare-section";
import { StudentViewSection } from "./student-view-section";
import { SchoolCopilotSection } from "./school-copilot-section";
import { RosterSection } from "./roster-section";
import { ScheduleSection } from "./schedule-section";

type Overview = {
  school: { id: number; name: string; type: string; ownership: string };
  students_count: number;
  avg_effective_mastery: number | null;
  avg_retention: number | null;
  growth_vs_prev: number | null;
  needs_intervention: number;
  critical_topics_count: number;
  drop_classes_count: number;
  drop_class_ids: number[];
  teachers_flagged_count: number;
  status_counts: Record<string, number>;
  note_fa?: string;
};

type CompareRow = {
  class_id: number;
  class_name: string;
  grade: string;
  teacher: { id: number; full_name: string } | null;
  avg_mastery: number | null;
  avg_retention: number | null;
  students_with_data: number;
  total_errors: number;
  gap_vs_school_avg: number | null;
  drop_flag: boolean;
  weak_topics: { topic_id: number; title: string; weak_students: number }[];
};

type CompareData = {
  subject: string;
  comparison_valid: boolean;
  min_group_note: string;
  rows: CompareRow[];
};

type Flag = {
  class_id: number;
  class_name: string;
  subject: string;
  teacher_name: string | null;
  flag_type: string;
  title_fa: string;
  evidence_fa: string;
  action_fa: string;
};

type TeacherProfile = {
  teacher_id: number;
  teacher_name: string | null;
  subject: string;
  class_id: number;
  class_name: string;
  students_count: number;
  class_mastery: number | null;
  class_retention: number | null;
  total_errors: number;
  platform: { exam_sessions_recorded: number; answers_recorded: number };
  note_fa: string;
};

type Diagnosis = {
  class_id: number;
  class_mastery: number | null;
  error_causes: Record<string, number>;
  total_errors: number;
  weak_topics: { topic_id: number; title: string; weak_students: number }[];
  grounded_actions_fa: string[];
  note_fa: string;
};

const FLAG_STYLE: Record<string, string> = {
  low_mastery_majority: "bg-danger-50 text-danger-600",
  high_repeats: "bg-warning-50 text-warning-600",
  ineffective_intervention: "bg-accent-50 text-accent-600",
  low_platform_usage: "bg-slate-100 text-ink-muted",
};

type Tab =
  | "overview"
  | "compare"
  | "flags"
  | "teachers"
  | "admissions"
  | "teachercmp"
  | "students"
  | "copilot"
  | "roster"
  | "schedule"
  | "employment";

/** ترتیب نمایش در منوی سمت راست */
const TAB_KEYS: readonly string[] = [
  "overview",
  "compare",
  "flags",
  "teachers",
  "roster",
  "schedule",
  "teachercmp",
  "students",
  "admissions",
  "employment",
  "copilot",
];

export default function AdminPage() {
  return (
    <AppShell>
      {/* بخش فعال از query آدرس می‌آید → باید داخل یک Suspense باشد */}
      <Suspense fallback={<SkeletonStats count={4} />}>
        <AdminInner />
      </Suspense>
    </AppShell>
  );
}

function AdminInner() {
  const [tab, setTab] = useTabParam(TAB_KEYS, "overview");
  const [ov, setOv] = useState<Overview | null>(null);
  const [cmp, setCmp] = useState<CompareData | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [profiles, setProfiles] = useState<TeacherProfile[]>([]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [error, setError] = useState("");
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);
  // مدرسهٔ جاری از /admin/my/schools می‌آید (نه school/1 hardcode)
  const [schoolId, setSchoolId] = useState<number | null>(null);
  const [mySchools, setMySchools] = useState<{ id: number; name: string }[]>([]);

  // تأیید/رد استخدام فقط سطح ناحیه و بالاتر (بک‌اند scope ناحیه را چک می‌کند)
  const canDecide = role === "district_admin" || role === "province_admin" || role === "platform_admin";

  const loadAll = useCallback(async (sid: number | null = null) => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);

      // مدرسه/مدرسه‌های در دیدِ من (قبلا school/1 hardcode بود)
      let target = sid;
      if (target === null) {
        const mine = await api<{ schools: { id: number; name: string }[]; default_id: number | null }>(
          "/admin/my/schools"
        );
        setMySchools(mine.schools);
        target = mine.default_id;
        setSchoolId(target);
      }
      if (target === null) {
        setError("هیچ مدرسه‌ای در حوزه دسترسی شما یافت نشد.");
        setLoading(false);
        return;
      }

      // هر بخش مستقل واکشی می‌شود تا 403 یک بخش (حوزه دسترسی)، کل صفحه را نیندازد
      const parts = await Promise.allSettled([
        api<Overview>(`/admin/school/${target}/overview`),
        api<CompareData>(`/admin/school/${target}/classes-compare/math`),
        api<{ flags: Flag[] }>(`/admin/school/${target}/attention-flags`),
        api<{ profiles: TeacherProfile[] }>(`/admin/school/${target}/teachers`),
      ]);
      if (parts[0].status === "fulfilled") setOv(parts[0].value);
      if (parts[1].status === "fulfilled") setCmp(parts[1].value);
      if (parts[2].status === "fulfilled") setFlags(parts[2].value.flags);
      if (parts[3].status === "fulfilled") setProfiles(parts[3].value.profiles);
      const failed = parts.filter((p) => p.status === "rejected") as PromiseRejectedResult[];
      if (failed.length === parts.length) {
        setError(failed[0]?.reason instanceof Error ? failed[0].reason.message : "خطا");
      } else if (failed.length > 0) {
        toast("برخی بخش‌ها بر اساس حوزه دسترسی شما نمایش داده نشدند.", "info");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll(null);
  }, [loadAll]);

  async function openDiagnosis(classId: number) {
    setDiagnosis(null);
    try {
      setDiagnosis(await api<Diagnosis>(`/admin/classes/${classId}/diagnosis`));
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در تشخیص", "error");
    }
  }

  const statusData = useMemo(() => {
    if (!ov) return [];
    const colors: Record<string, string> = {
      mastered: "#10b981",
      consolidating: "#0ea5e9",
      weak: "#f59e0b",
      critical: "#f43f5e",
      unknown: "#cbd5e1",
    };
    const labels: Record<string, string> = {
      mastered: "مسلط",
      consolidating: "در حال تثبیت",
      weak: "ضعیف",
      critical: "بحرانی",
      unknown: "نامشخص",
    };
    return Object.entries(ov.status_counts).map(([k, v]) => ({ label: labels[k] ?? k, value: v, color: colors[k] }));
  }, [ov]);

  const classChartData = useMemo(
    () =>
      (cmp?.rows ?? [])
        .filter((r) => r.avg_mastery !== null)
        .map((r) => ({
          label: r.class_name,
          value: Math.round(r.avg_mastery as number),
          color: r.drop_flag ? "#f43f5e" : "#6366f1",
        })),
    [cmp]
  );

  const compareColumns: Column<CompareRow>[] = [
    {
      key: "class",
      header: "کلاس",
      render: (row) => (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{row.class_name}</span>
          {row.drop_flag && (
            <Badge tone="danger" dot>
              کلاس دارای افت
            </Badge>
          )}
        </div>
      ),
    },
    { key: "teacher", header: "معلم", align: "center", render: (row) => row.teacher?.full_name ?? "—" },
    {
      key: "mastery",
      header: "تسط",
      align: "center",
      render: (row) => <span className="num font-bold text-ink">{row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}</span>,
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num">{row.avg_retention !== null ? `${fa(row.avg_retention * 100)}٪` : "—"}</span>,
    },
    {
      key: "gap",
      header: "اختلاف با میانگین",
      align: "center",
      render: (row) => (
        <span className={`num font-semibold ${row.drop_flag ? "text-danger-600" : "text-ink-muted"}`}>
          {row.gap_vs_school_avg !== null ? `${row.gap_vs_school_avg > 0 ? "+" : ""}${fa(row.gap_vs_school_avg)} واحد` : "—"}
        </span>
      ),
    },
    { key: "errors", header: "خطاها", align: "center", render: (row) => <span className="num">{fa(row.total_errors)}</span> },
    {
      key: "act",
      header: "",
      align: "end",
      render: (row) => (
        <Button size="sm" variant="soft" onClick={() => openDiagnosis(row.class_id)}>
          تشخیص ضعف
        </Button>
      ),
    },
  ];

  const profileColumns: Column<TeacherProfile>[] = [
    { key: "name", header: "معلم", render: (row) => <span className="font-semibold text-ink">{row.teacher_name ?? "—"}</span> },
    { key: "class", header: "درس / کلاس", align: "center", render: (row) => `${subjectFa(row.subject)} · کلاس ${row.class_name}` },
    { key: "students", header: "دانش‌آموز", align: "center", render: (row) => <span className="num">{fa(row.students_count)}</span> },
    {
      key: "mastery",
      header: "تسط کلاس",
      align: "center",
      render: (row) => <span className="num font-bold text-ink">{row.class_mastery !== null ? `${fa(row.class_mastery)}٪` : "—"}</span>,
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num">{row.class_retention !== null ? `${fa(row.class_retention * 100)}٪` : "—"}</span>,
    },
    { key: "exams", header: "آزمون ثبت‌شده", align: "center", render: (row) => <span className="num">{fa(row.platform.exam_sessions_recorded)}</span> },
  ];

  return (
      <div className="space-y-6">
        <PageHeader
          title={loading ? "مدیریت مدرسه" : ov?.school.name ?? "مدیریت مدرسه"}
          description={
            ov
              ? `داشبورد کلان مدرسه — ${ov.school.ownership === "public" ? "دولتی" : ov.school.ownership} · ${role === "district_admin" ? "دید ناحیه" : "دید مدرسه"}`
              : "داشبورد کلان مدرسه، مقایسه کلاس‌ها و کارتابل استخدام"
          }
          crumbs={[{ label: "دانشیار" }, { label: "مدیریت" }, { label: "مدرسه" }]}
          badge={role ? <Badge tone="primary" dot>{role === "district_admin" ? "دید ناحیه" : "دید مدرسه"}</Badge> : undefined}
          actions={
            <div className="flex items-center gap-2">
              {mySchools.length > 1 && (
                <select
                  className="rounded-xl border border-line bg-surface px-2.5 py-1.5 text-xs font-semibold text-ink"
                  value={schoolId ?? ""}
                  onChange={(e) => {
                    const next = Number(e.target.value);
                    setSchoolId(next);
                    setLoading(true);
                    loadAll(next);
                  }}
                  aria-label="انتخاب مدرسه"
                >
                  {mySchools.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              )}
              <Button variant="ghost" size="sm" icon={<IconRefresh size={15} />} onClick={() => { setLoading(true); loadAll(schoolId); }}>
                به‌روزرسانی
              </Button>
            </div>
          }
        />

        {error && !ov && <Alert variant="danger" title="خطا در دریافت اطلاعات">{error}</Alert>}

        {loading && !ov && tab === "overview" && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <SkeletonStats count={2} />
          </div>
        )}

        {ov && (
          <>
            {/* نمای کلی — کارت‌های آمار + نمودارها */}
            {tab === "overview" && (
              <>
                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <StatCard label="دانش‌آموزان" value={fa(ov.students_count)} tone="primary" icon={<IconUsers size={20} />} hint={ov.school.name} />
                  <StatCard
                    label="میانگین تسط مؤثر"
                    value={ov.avg_effective_mastery !== null ? `${fa(ov.avg_effective_mastery, 1)}٪` : "—"}
                    tone="success"
                    icon={<IconTarget size={20} />}
                    hint="همه مباحث"
                  />
                  <StatCard
                    label="رشد نسبت به دوره قبل"
                    value={ov.growth_vs_prev !== null ? `${ov.growth_vs_prev > 0 ? "+" : ""}${fa(ov.growth_vs_prev, 1)}٪` : "—"}
                    tone={ov.growth_vs_prev !== null && ov.growth_vs_prev < 0 ? "danger" : "accent"}
                    icon={<IconChart size={20} />}
                    hint={ov.note_fa ?? "تغییر تسط مؤثر"}
                  />
                  <StatCard
                    label="ماندگاری"
                    value={ov.avg_retention !== null ? `${fa(ov.avg_retention * 100)}٪` : "—"}
                    tone="sky"
                    icon={<IconLayers size={20} />}
                    hint="میانگین R مباحث"
                  />
                  <StatCard label="نیازمند مداخله" value={fa(ov.needs_intervention)} tone="danger" icon={<IconAlert size={20} />} hint="برنامه ترمیمی لازم دارد" />
                  <StatCard
                    label="مباحث بحرانی"
                    value={fa(ov.critical_topics_count)}
                    tone="warning"
                    icon={<IconLayers size={20} />}
                    hint="تعداد مبحث بحرانیِ یکتا"
                  />
                  <button
                    type="button"
                    onClick={() => setTab("compare")}
                    className="block w-full text-right"
                    title="برای ریشه‌یابی به مقایسه کلاس‌ها بروید"
                  >
                    <StatCard
                      label="کلاس دارای افت"
                      value={fa(ov.drop_classes_count)}
                      tone="danger"
                      icon={<IconShield size={20} />}
                      hint="≥۱۰ واحد زیر میانگین هم‌درس — کلیک برای ریشه‌یابی"
                    />
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab("flags")}
                    className="block w-full text-right"
                    title="برای دیدن پرچم‌ها به تب «نیازمند بررسی» بروید"
                  >
                    <StatCard
                      label="معلم نیازمند بررسی"
                      value={fa(ov.teachers_flagged_count)}
                      tone="warning"
                      icon={<IconShield size={20} />}
                      hint="پرچم هشداری، نه ارزیابی — کلیک برای مشاهده"
                    />
                  </button>
                </section>

                <section className="grid gap-5 lg:grid-cols-3">
                  <Card className="lg:col-span-2">
                    <CardHeader title="مقایسه تسط کلاس‌ها" subtitle={`درس ${cmp?.subject ?? "ریاضی"} — قرمزها کلاس دارای افت`} icon={<IconChart size={17} />} />
                    {classChartData.length > 0 ? (
                      <BarChart data={classChartData} height={220} id="admin-classes" format={(v) => `${fa(v)}٪`} />
                    ) : (
                      <EmptyState compact title="داده‌ای برای مقایسه نیست" />
                    )}
                  </Card>
                  <Card>
                    <CardHeader title="توزیع وضعیت مباحث" icon={<IconLayers size={17} />} />
                    {statusData.length > 0 ? (
                      <DonutChart data={statusData} size={140} thickness={20} centerSubtitle="مبحث" />
                    ) : (
                      <EmptyState compact title="داده‌ای ثبت نشده" />
                    )}
                  </Card>
                </section>
              </>
            )}

            {/* §7 مقایسه کلاس‌ها */}
            {tab === "compare" && (
              <Section>
                {cmp && !cmp.comparison_valid && <Alert variant="warning">{cmp.min_group_note}</Alert>}
                <DataTable
                  columns={compareColumns}
                  rows={cmp?.rows ?? []}
                  keyOf={(r) => r.class_id}
                  empty={<EmptyState compact title="کلاسی برای مقایسه نیست" />}
                />
                <p className="text-[11px] leading-6 text-ink-faint">
                  پرچم «کلاس دارای افت» یعنی اختلاف ≥ ۱۰ واحد با میانگین هم‌درس‌ها — فقط پرچم است، نه حکم درباره معلم.
                </p>
              </Section>
            )}

            {/* §5 نیازمند بررسی */}
            {tab === "flags" && (
              <Section>
                <Alert variant="info">این موارد هشدار هستند، نه ارزیابی قطعی از معلم. (سند مدیر مدرسه §5)</Alert>
                {flags.length === 0 && (
                  <EmptyState
                    icon={<IconShield size={26} />}
                    title="هیچ مورد نیازمند بررسی وجود ندارد"
                    description="همه شاخص‌ها در محدوده عادی هستند."
                  />
                )}
                <div className="grid gap-4 md:grid-cols-2">
                  {flags.map((f, i) => (
                    <Card key={i} className="space-y-2">
                      <div className="flex items-start justify-between gap-3">
                        <span className="flex items-center gap-2 text-sm font-bold text-ink">
                          <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${FLAG_STYLE[f.flag_type] ?? "bg-slate-100 text-ink-muted"}`}>
                            <IconAlert size={16} />
                          </span>
                          {f.title_fa}
                        </span>
                        <Badge tone="neutral">کلاس {f.class_name}</Badge>
                      </div>
                      <p className="text-xs leading-6 text-ink-muted">{f.evidence_fa}</p>
                      <p className="rounded-xl bg-primary-50 px-3 py-2 text-[11px] leading-6 text-primary-800">
                        <b>اقدام:</b> {f.action_fa}
                      </p>
                      <p className="num text-[11px] text-ink-faint">
                        {subjectFa(f.subject)} · {f.teacher_name ?? "—"}
                      </p>
                      <Button size="sm" variant="soft" onClick={() => openDiagnosis(f.class_id)}>
                        تشخیص چندعاملی این کلاس
                      </Button>
                    </Card>
                  ))}
                </div>
              </Section>
            )}

            {/* §4 نمایه معلمان */}
            {tab === "teachers" && (
              <Section>
                <DataTable columns={profileColumns} rows={profiles} keyOf={(p) => p.teacher_id} empty={<EmptyState compact title="نمایه‌ای ثبت نشده" />} />
                <p className="text-[11px] leading-6 text-ink-faint">
                  شاخص عینی کلاس هر معلم است؛ بدون امتیاز عددی کلی. قضاوت نیاز به بررسی زمینه‌ای دارد (§4 و §8).
                </p>
              </Section>
            )}

            {/* ثبت‌نام دانش‌آموزان */}
            {tab === "admissions" && <AdmissionsSection schoolId={schoolId} />}

            {/* رکورد کامل: همه دانش‌آموزان با جایگاه کلاسی + کلاس‌ها + معلمان */}
            {tab === "roster" && <RosterSection schoolId={schoolId} />}

            {/* شیفت‌های مدرسه + برنامه هفتگی هر کلاس + کادر آموزشی */}
            {tab === "schedule" && <ScheduleSection schoolId={schoolId} />}

            {/* §8 مقایسه معلم با معلم — با احتیاط */}
            {tab === "teachercmp" && <TeachersCompareSection schoolId={schoolId} />}

            {/* §13 نمای فردی دانش‌آموز */}
            {tab === "students" && <StudentViewSection schoolId={schoolId} />}

            {/* §16/§18 دستیار هوشمند مدیر مدرسه */}
            {tab === "copilot" && <SchoolCopilotSection schoolId={schoolId} />}

            {/* §6 تشخیص چندعاملی */}
            <Modal
              open={diagnosis !== null}
              onClose={() => setDiagnosis(null)}
              title={diagnosis ? `تشخیص چندعاملی — کلاس ${diagnosis.class_id}` : ""}
              size="lg"
              footer={
                <Button variant="ghost" onClick={() => setDiagnosis(null)}>
                  بستن
                </Button>
              }
            >
              {diagnosis && (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Badge tone="primary">تسط کلاس: {diagnosis.class_mastery !== null ? `${fa(diagnosis.class_mastery)}٪` : "—"}</Badge>
                    <Badge tone="danger">تعداد خطا: {fa(diagnosis.total_errors)}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(diagnosis.error_causes).map(([c, n]) => (
                      <Badge key={c} tone="neutral">
                        {CAUSE_SHORT[c] ?? c}: {fa(n)}
                      </Badge>
                    ))}
                  </div>
                  {diagnosis.weak_topics.length > 0 && (
                    <div className="rounded-xl bg-surface-sunken p-3">
                      <p className="mb-2 text-xs font-bold text-ink">مباحث ضعیف</p>
                      <ul className="space-y-1 text-xs">
                        {diagnosis.weak_topics.map((t) => (
                          <li key={t.topic_id} className="flex items-center justify-between">
                            <span>{t.title}</span>
                            <span className="num text-ink-faint">{fa(t.weak_students)} دانش‌آموز</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div>
                    <p className="mb-2 text-xs font-bold text-ink">اقدامات پیشنهادی</p>
                    <ul className="space-y-1.5 text-xs leading-6">
                      {diagnosis.grounded_actions_fa.map((a, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-success-50 text-success-600">
                            <IconCheckCircle size={11} />
                          </span>
                          {a}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <p className="text-[11px] leading-6 text-ink-faint">{diagnosis.note_fa}</p>
                </div>
              )}
            </Modal>
          </>
        )}

        {/* ——— استخدام معلم (ویزارد + کارتابل) ——— */}
        {tab === "employment" && <EmploymentSection canDecide={canDecide} onChanged={loadAll} />}
      </div>
  );
}
