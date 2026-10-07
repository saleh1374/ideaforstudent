"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { fa } from "@/lib/labels";
import { homeFor } from "@/lib/roles";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconRefresh } from "@/components/ui/icons";
import { GeoOverviewPanel } from "@/components/geo/overview-panel";
import { GeoInsightsPanel } from "@/components/geo/insights-panel";
import type { Insights, Overview, TopicRow } from "@/components/geo/types";

type Tab = "province" | "national";

export default function GeoPage() {
  const [tab, setTab] = useState<Tab>("province");
  const [ov, setOv] = useState<Overview | null>(null);
  const [rows, setRows] = useState<TopicRow[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // استانِ انتخابی از فهرست rank استان‌ها می‌آید — هیچ id هاردکد نمی‌شود
  const [provinces, setProvinces] = useState<{ id: number; name: string }[]>([]);
  const [provinceId, setProvinceId] = useState<number | null>(null);

  const load = useCallback(async (t: Tab, pid: number | null) => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setOv(null);
    setInsights(null);
    setLoading(true);
    setError("");
    try {
      const me = await api<{ role: string }>("/auth/me");
      setRole(me.role);
      // این صفحه فقط ویژه وزارت است؛ بقیه نقش‌ها به پنل خودشان می‌روند
      if (me.role !== "ministry") {
        window.location.href = homeFor(me.role);
        return;
      }

      // فهرست استان‌ها از rank تجمیع ملی ساخته می‌شود (بدون hardcode)
      let list: { id: number; name: string }[] = [];
      let nat: Insights | null = null;
      try {
        nat = await api<Insights>("/geo/national/insights");
        setInsights(t === "national" ? nat : null);
        const seen = new Set<number>();
        list = [...(nat?.province_ranking ?? []), ...(nat?.suppressed_provinces ?? [])]
          .filter((p) => {
            if (!p.province_id || seen.has(p.province_id)) return false;
            seen.add(p.province_id);
            return true;
          })
          .map((p) => ({ id: p.province_id, name: p.name }));
      } catch {
        nat = null;
      }
      if (list.length > 0) setProvinces(list);

      // اولین بار: روی اولین استانِ رتبه‌بندی می‌رویم و اثر دوباره اجرا می‌شود
      if (t === "province" && pid === null) {
        if (list.length > 0) {
          setProvinceId(list[0].id);
          return;
        }
        setError("فهرست استان‌ها در دسترس نیست؛ دید کشوری نمایش داده می‌شود.");
        setTab("national");
        return;
      }

      const base = t === "province" ? `/geo/province/${pid}` : "/geo/national";
      const [o, s] = await Promise.all([
        api<Overview>(`${base}/overview`),
        api<{ rows: TopicRow[] }>(`${base}/topics`),
      ]);
      setOv(o);
      setRows(s.rows);

      // روایت تحلیلی — برای دید استان، insights همان استان است
      if (t === "province") {
        try {
          setInsights(await api<Insights>(`/geo/province/${pid}/insights`));
        } catch {
          setInsights(null);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(tab, provinceId);
  }, [tab, provinceId, load]);

  async function refresh() {
    setRefreshing(true);
    try {
      const res = await api<{ national: { written: number; suppressed: number } }>("/geo/national/refresh", { method: "POST" });
      await load(tab, provinceId);
      toast(`بازمحاسبه شد: ${fa(res.national.written)} مبحث (${fa(res.national.suppressed)} سرکوب‌شده)`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در بازمحاسبه", "error");
    } finally {
      setRefreshing(false);
    }
  }

  const title = tab === "province" ? "مدیر کل استان" : "وزارت / سطح ملی";

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title={title}
          description="تجمیع‌های province / national_topic_stats — عددها تابع حداقل جمعیت ۱۰ هستند."
          crumbs={[{ label: "دانشیار" }, { label: "مدیریت" }, { label: title }]}
          badge={role ? <Badge tone="accent" dot>{role === "ministry" ? "وزارت" : "مدیر کل استان"}</Badge> : undefined}
          actions={
            role === "ministry" && (
              <Button variant="soft" size="sm" loading={refreshing} icon={<IconRefresh size={15} />} onClick={refresh}>
                بازمحاسبه تجمیع‌ها
              </Button>
            )
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت داده">{error}</Alert>}

        <div className="flex flex-wrap items-center gap-3">
          <Tabs
            items={[
              { key: "province", label: "دید استان" },
              { key: "national", label: "دید کشور" },
            ]}
            value={tab}
            onChange={(k) => setTab(k as Tab)}
          />

          {/* انتخاب استان — از rank تجمیع ملی، بدون هیچ id هاردکد */}
          {tab === "province" && (
            <label className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-soft">
              <span className="font-semibold text-ink-muted">استان:</span>
              <select
                className="bg-transparent font-bold text-ink outline-none"
                value={provinceId ?? ""}
                onChange={(e) => setProvinceId(Number(e.target.value))}
              >
                {provinces.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
                {provinces.length === 0 && <option value="">—</option>}
              </select>
            </label>
          )}
        </div>

        {loading && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <SkeletonTable rows={6} cols={6} />
          </div>
        )}

        {ov && !loading && (
          <GeoOverviewPanel
            ov={ov}
            rows={rows}
            scopeLabel={tab === "province" ? "استانی" : "ملی"}
            chartId="geo-worst"
            topicsTitle="مباحث با کمترین تسط (تجمیع ملی/استانی)"
          />
        )}

        {/* ---------------- روایت تحلیلی نقاط ضعف (سطح ملی) ---------------- */}
        {insights && !loading && <GeoInsightsPanel data={insights} />}
      </div>
    </AppShell>
  );
}
