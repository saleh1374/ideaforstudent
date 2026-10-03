"use client";

import { useCallback, useEffect, useState, Suspense } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Tabs, useTabParam } from "@/components/ui/tabs";
import { BarChart, DonutChart } from "@/components/ui/charts";
import { SkeletonStats, SkeletonCard } from "@/components/ui/skeleton";
import {
  IconAlert,
  IconChart,
  IconCheckCircle,
  IconLayers,
  IconRefresh,
  IconSchool,
  IconShield,
  IconTasks,
  IconUsers,
} from "@/components/ui/icons";
import { SchoolsSection } from "./schools-section";
import { StaffSection } from "./staff-section";
import { EmploymentSection } from "./employment-section";
import { QualificationsSection } from "./qualifications-section";
import { AdmissionsSection } from "./admissions-section";
import { ExamsSection } from "./exams-section";
import { InterventionsSection } from "./interventions-section";

type Overview = {
  district: { id: number; name: string | null };
  schools_count: number;
  students_count: number;
  classes_count: number;
  teachers_count: number;
  pending_employment_requests: number;
  educational: {
    avg_mastery: number | null;
    suppressed: boolean;
    min_group: number;
    status_counts: Record<string, number> | null;
    needs_intervention: number | null;
  };
  worst_topics: { topic_id: number; title: string; students_count: number; avg_mastery: number }[];
  note_fa: string;
};

type Tab =
  | "overview"
  | "schools"
  | "staff"
  | "employment"
  | "qualifications"
  | "admissions"
  | "exams"
  | "interventions";

const TAB_KEYS: readonly string[] = [
  "overview",
  "schools",
  "staff",
  "employment",
  "qualifications",
  "exams",
  "interventions",
  "admissions",
];

const STATUS_FA: Record<string, string> = {
  mastered: "مسلط",
  consolidating: "در حال تثبیت",
  weak: "ضعیف",
  critical: "بحرانی",
  unknown: "نامشخص",
};

const STATUS_COLOR: Record<string, string> = {
  mastered: "#10b981",
  consolidating: "#0ea5e9",
  weak: "#f59e0b",
  critical: "#f43f5e",
  unknown: "#cbd5e1",
};

export default function DistrictPage() {
  return (
    <AppShell>
      {/* بخش فعال از query آدرس می‌آید → باید داخل یک Suspense باشد */}
      <Suspense fallback={null}>
        <DistrictInner />
      </Suspense>
    </AppShell>
  );
}

function DistrictInner() {
  const [tab, setTab] = useTabParam(TAB_KEYS, "overview");
  const [role, setRole] = useState(""); // "" = هنوز بررسی نشده
  const [denied, setDenied] = useState(false);
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadOverview = useCallback(async () => {
    setRefreshing(true);
    try {
      setOv(await api<Overview>("/district/overview"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت نمای کلان");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    (async () => {
      try {
        const me = await api<{ role: string }>("/auth/me");
        setRole(me.role);
        if (me.role !== "district_admin") {
          setDenied(true);
          setLoading(false);
          return;
        }
        await loadOverview();
      } catch (e) {
        setError(e instanceof Error ? e.message : "خطا");
        setLoading(false);
      }
    })();
  }, [loadOverview]);

  /* ---------------- سرصفحه مشترک ---------------- */
  const header = (
    <PageHeader
      title={ov?.district.name ?? "پنل مدیر ناحیه"}
      description="مدیریت مدارس، کارکنان، درخواست‌های استخدام و صلاحیت معلم در محدوده ناحیه — همه اعداد تجمیعی با رعایت حداقل جمعیت."
      crumbs={[{ label: "دانشیار" }, { label: "مدیریت" }, { label: "ناحیه" }]}
      badge={role ? <Badge tone="accent" dot>ناحیه {fa(ov?.district.id ?? 1)}</Badge> : undefined}
      actions={
        role === "district_admin" && (
          <Button variant="soft" size="sm" loading={refreshing} icon={<IconRefresh size={15} />} onClick={loadOverview}>
            به‌روزرسانی
          </Button>
        )
      }
    />
  );

  /* ---------------- غیر از مدیر ناحیه ---------------- */
  if (denied) {
    return (
      <div className="space-y-6">
        {header}
        <Alert variant="warning" title="دسترسی محدود">
          این صفحه ویژه مدیر ناحیه است. با حساب مدیر ناحیه وارد شوید؛ سرور نیز دامنه دسترسی را جداگانه کنترل می‌کند.
        </Alert>
        <EmptyState
          icon={<IconShield size={26} />}
          title="نقش شما به این صفحه دسترسی ندارد"
          description={`نقش فعلی: ${role || "—"}`}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}

        {error && <Alert variant="danger" title="خطا در دریافت داده">{error}</Alert>}

        <Tabs
          items={[
            { key: "overview", label: "نمای کلان" },
            { key: "schools", label: "مدارس ناحیه" },
            { key: "staff", label: "کارکنان ناحیه" },
            { key: "employment", label: "درخواست‌های استخدام" },
            { key: "qualifications", label: "صلاحیت معلم" },
            { key: "exams", label: "آزمون‌های رسمی" },
            { key: "interventions", label: "مداخله و مأموریت‌ها" },
            { key: "admissions", label: "ثبت‌نام دانش‌آموزان" },
          ]}
          value={tab}
          onChange={(k) => setTab(k)}
        />

        {/* ---------------- نمای کلان ---------------- */}
        {tab === "overview" && (
          <>
            {loading && !ov && (
              <div className="space-y-5">
                <SkeletonStats count={4} />
                <SkeletonCard />
              </div>
            )}

            {ov && (
              <div className="space-y-6">
                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <StatCard label="مدارس ناحیه" value={fa(ov.schools_count)} tone="primary" icon={<IconSchool size={20} />} hint={ov.district.name ?? "—"} />
                  <StatCard label="دانش‌آموزان" value={fa(ov.students_count)} tone="accent" icon={<IconUsers size={20} />} hint={`${fa(ov.classes_count)} کلاس`} />
                  <StatCard label="معلمان" value={fa(ov.teachers_count)} tone="sky" icon={<IconUsers size={20} />} hint="تخصیص فعال" />
                  <StatCard
                    label="میانگین تسط ناحیه"
                    value={ov.educational.suppressed ? "زیر حد نصاب" : ov.educational.avg_mastery !== null ? `${fa(ov.educational.avg_mastery)}٪` : "—"}
                    tone={ov.educational.suppressed ? "warning" : "success"}
                    icon={<IconChart size={20} />}
                    hint={ov.educational.suppressed ? `کمتر از ${fa(ov.educational.min_group)} دانش‌آموز دارای داده` : "همه مباحث دارای داده"}
                  />
                </section>

                <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                  <StatCard
                    label="نیازمند مداخله"
                    value={ov.educational.needs_intervention === null ? (ov.educational.suppressed ? "زیر حد نصاب" : "—") : fa(ov.educational.needs_intervention)}
                    tone="danger"
                    icon={<IconAlert size={20} />}
                    hint="مباحث ضعیف + بحرانی"
                  />
                  <StatCard
                    label="درخواست‌های استخدام"
                    value={fa(ov.pending_employment_requests)}
                    tone={ov.pending_employment_requests > 0 ? "warning" : "primary"}
                    icon={<IconTasks size={20} />}
                    hint="در انتظار تأیید"
                  />
                  <StatCard label="مباحث قابل گزارش" value={fa(ov.worst_topics.length)} tone="accent" icon={<IconLayers size={20} />} hint="بالای حداقل جمعیت" />
                  <StatCard label="کلاس‌ها" value={fa(ov.classes_count)} tone="primary" icon={<IconSchool size={20} />} hint="در همه مدارس" />
                </section>

                <Alert variant="info">{ov.note_fa}</Alert>

                <section className="grid gap-5 lg:grid-cols-3">
                  <Card className="lg:col-span-2">
                    <CardHeader title="ضعیف‌ترین مباحث ناحیه" subtitle="بر اساس میانگین تسط — فقط مباحث بالای حداقل جمعیت" icon={<IconChart size={17} />} />
                    {ov.worst_topics.length > 0 ? (
                      <BarChart
                        id="district-worst"
                        height={230}
                        format={(v) => `${fa(v)}٪`}
                        data={ov.worst_topics.map((t) => ({
                          label: t.title,
                          value: Math.round(t.avg_mastery),
                          color: t.avg_mastery < 50 ? "#f43f5e" : t.avg_mastery < 65 ? "#f59e0b" : "#6366f1",
                        }))}
                      />
                    ) : (
                      <EmptyState compact title="داده‌ای زیر حد نصاب نیست" description="برای این ناحیه مبحث قابل نمایشی ثبت نشده است." />
                    )}
                  </Card>
                  <Card>
                    <CardHeader title="توزیع وضعیت مباحث" icon={<IconLayers size={17} />} />
                    {ov.educational.status_counts && Object.keys(ov.educational.status_counts).length > 0 ? (
                      <DonutChart
                        size={140}
                        thickness={20}
                        centerSubtitle="مبحث"
                        data={Object.entries(ov.educational.status_counts).map(([k, v]) => ({
                          label: STATUS_FA[k] ?? k,
                          value: v,
                          color: STATUS_COLOR[k] ?? "#cbd5e1",
                        }))}
                      />
                    ) : (
                      <EmptyState compact title="زیر حد نصاب" description={`حداقل ${fa(ov.educational.min_group)} دانش‌آموز دارای داده لازم است.`} />
                    )}
                    <p className="mt-3 text-[11px] leading-6 text-ink-faint">
                      اعداد تجمیعی فقط با حداقل {fa(ov.educational.min_group)} دانش‌آموز دارای داده نمایش داده می‌شود.
                    </p>
                  </Card>
                </section>
              </div>
            )}
          </>
        )}

        {/* ---------------- سایر بخش‌ها (بارگذاری تنبل) ---------------- */}
        {tab === "schools" && <SchoolsSection onChanged={loadOverview} />}
        {tab === "staff" && <StaffSection />}
        {tab === "employment" && <EmploymentSection onChanged={loadOverview} />}
        {tab === "qualifications" && <QualificationsSection />}
        {tab === "exams" && <ExamsSection />}
        {tab === "interventions" && <InterventionsSection />}
        {tab === "admissions" && <AdmissionsSection onChanged={loadOverview} />}
      </div>
  );
}
