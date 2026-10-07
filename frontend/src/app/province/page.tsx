"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";
import { homeFor } from "@/lib/roles";
import { AppShell, ROLE_FA } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { IconMap, IconRefresh, IconShield } from "@/components/ui/icons";
import { GeoOverviewPanel } from "@/components/geo/overview-panel";
import { GeoInsightsPanel } from "@/components/geo/insights-panel";
import { ProvinceRankingTable } from "@/components/geo/province-ranking";
import { DistrictReportsSection } from "./district-reports-section";
import type { Insights, Overview, TopicRow } from "@/components/geo/types";

/** حوزهٔ تماس‌گیرنده — GET /geo/me (در صورت نبود، از /auth/me فقط نقش خوانده می‌شود). */
type GeoMe = {
  province_id: number | null;
  district_id: number | null;
  role: string;
  /** بعضی سرورها نام استان را هم می‌فرستند — اختیاری و دفاعی. */
  province_name?: string | null;
};

export default function ProvincePage() {
  const [me, setMe] = useState<GeoMe | null>(null);
  const [ov, setOv] = useState<Overview | null>(null);
  const [rows, setRows] = useState<TopicRow[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [national, setNational] = useState<Insights | null>(null);
  const [role, setRole] = useState(""); // "" = هنوز بررسی نشده
  const [denied, setDenied] = useState(false);
  const [scopeMissing, setScopeMissing] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setLoading(true);
    setError("");
    try {
      // ۱) حوزهٔ استانی تماس‌گیرنده
      let scope: GeoMe | null = null;
      try {
        scope = await api<GeoMe>("/geo/me");
      } catch {
        // /geo/me ممکن است در دسترس نباشد — نقش را از /auth/me می‌گیریم
        try {
          const auth = await api<{ role: string }>("/auth/me");
          scope = { province_id: null, district_id: null, role: auth.role };
        } catch (e) {
          throw e;
        }
      }
      setMe(scope);
      const callerRole = scope.role ?? "";
      setRole(callerRole);

      // ۲) فقط مدیر کل استان
      if (callerRole !== "province_admin") {
        setDenied(true);
        setLoading(false);
        window.location.href = homeFor(callerRole);
        return;
      }

      // ۳) حوزهٔ استانی تعیین شده؟
      const provinceId = scope.province_id;
      if (provinceId == null) {
        setScopeMissing(true);
        setLoading(false);
        return;
      }
      setScopeMissing(false);

      // ۴) داده‌های تجمیعی استان
      const [o, s] = await Promise.all([
        api<Overview>(`/geo/province/${provinceId}/overview`),
        api<{ rows: TopicRow[] }>(`/geo/province/${provinceId}/topics`),
      ]);
      setOv(o);
      setRows(s.rows);

      // ۵) بینش تحلیلی استان (403 بی‌صدا نادیده گرفته می‌شود)
      try {
        setInsights(await api<Insights>(`/geo/province/${provinceId}/insights`));
      } catch {
        setInsights(null);
      }

      // ۶) رتبه‌بندی ملی استان‌ها — در صورت 403 بی‌صدا حذف می‌شود (بدون toast)
      try {
        setNational(await api<Insights>("/geo/national/insights"));
      } catch {
        setNational(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت داده");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const provinceId = me?.province_id ?? null;
  const provinceName =
    me?.province_name ??
    national?.province_ranking.find((p) => p.province_id === provinceId)?.name ??
    (provinceId !== null ? `استان #${fa(provinceId)}` : "—");

  /* ---------------- غیر از مدیر کل استان ---------------- */
  if (denied) {
    return (
      <AppShell>
        <div className="space-y-6">
          <PageHeader
            title="پنل مدیر کل استان"
            crumbs={[{ label: "دانشیار" }, { label: "مدیریت" }, { label: "استان" }]}
          />
          <Alert variant="warning" title="دسترسی محدود">
            این صفحه ویژه مدیر کل استان است؛ در حال انتقال به پنل نقش شما (
            {role ? (ROLE_FA[role] ?? role) : "—"}) هستیم.
          </Alert>
          <EmptyState icon={<IconShield size={26} />} title="نقش شما به این صفحه دسترسی ندارد" description={`نقش فعلی: ${role || "—"}`} />
        </div>
      </AppShell>
    );
  }

  const header = (
    <PageHeader
      title="پنل مدیر کل استان"
      description="نمای تجمیعی استان، بینش تحلیلی و جایگاه استان در میان استان‌های کشور — همه اعداد تابع حداقل جمعیت."
      crumbs={[{ label: "دانشیار" }, { label: "مدیریت" }, { label: "استان" }]}
      badge={role ? <Badge tone="accent" dot>{ROLE_FA[role] ?? role}</Badge> : undefined}
      actions={
        role === "province_admin" && (
          <Button variant="soft" size="sm" loading={refreshing} icon={<IconRefresh size={15} />} onClick={() => { setRefreshing(true); load().finally(() => setRefreshing(false)); }}>
            به‌روزرسانی
          </Button>
        )
      }
    />
  );

  return (
    <AppShell>
      <div className="space-y-6">
        {header}

        {/* ——— هیروی نام استان ——— */}
        <Card variant="gradient" className="relative overflow-hidden">
          <div className="flex flex-wrap items-center gap-4">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white/20">
              <IconMap size={24} />
            </span>
            <div className="min-w-0">
              <p className="text-xs text-white/70">حوزهٔ استانی شما</p>
              <p className="truncate text-xl font-extrabold leading-8">{provinceName}</p>
            </div>
            <div className="mr-auto flex flex-wrap items-center gap-2">
              {me?.district_id !== null && me?.district_id !== undefined && (
                <span className="num rounded-full bg-white/15 px-3 py-1 text-[11px] font-bold">ناحیه {fa(me.district_id)}</span>
              )}
              {provinceId !== null && <span className="num rounded-full bg-white/15 px-3 py-1 text-[11px] font-bold">کد استان {fa(provinceId)}</span>}
            </div>
          </div>
        </Card>

        {error && <Alert variant="danger" title="خطا در دریافت داده">{error}</Alert>}

        {scopeMissing && (
          <Alert variant="warning" title="حوزه استانی تعریف نشده">
            حوزه استانی شما تعیین نشده؛ لطفاً با مدیر سامانه تماس بگیرید تا استان شما ثبت شود.
          </Alert>
        )}

        {loading && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <SkeletonTable rows={6} cols={6} />
          </div>
        )}

        {/* ۱) آمار و نمودارهای استان (همان دادهٔ «دید استان» در /geo) */}
        {ov && !loading && (
          <GeoOverviewPanel
            ov={ov}
            rows={rows}
            scopeLabel="استانی"
            chartId="province-worst"
            topicsTitle="مباحث با کمترین تسط (تجمیع استانی)"
          />
        )}

        {/* ۲) بینش تحلیلی استان */}
        {insights && !loading && <GeoInsightsPanel data={insights} title="بینش تحلیلی استان" />}

        {/* ۳) حس رقابت — رتبه‌بندی استان‌های کشور (در صورت 403 بی‌صدا پنهان می‌شود) */}
        {national && !loading && national.province_ranking.length > 0 && (
          <Section
            title="رتبه‌بندی استان‌های کشور"
            subtitle="حس رقابت — جایگاه استان شما میان استان‌های کشور؛ ردیف‌های زیر حد نصاب بدون عدد و کم‌رنگ می‌مانند."
            action={<Badge tone="accent" dot>سطح ملی</Badge>}
          >
            <ProvinceRankingTable data={national} highlightProvinceId={provinceId} title={null} />
          </Section>
        )}

        {/* ۴) گزارش‌های ناحیه‌ها + تصمیم استان (§32) — در صورت 403 با پیام جدا نمایش داده می‌شود */}
        {!loading && role === "province_admin" && <DistrictReportsSection provinceId={provinceId} />}
      </div>
    </AppShell>
  );
}
