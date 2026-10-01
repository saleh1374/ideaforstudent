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

  const load = useCallback(async (t: Tab) => {
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
      const base = t === "province" ? "/geo/province/1" : "/geo/national";
      const [o, s] = await Promise.all([
        api<Overview>(`${base}/overview`),
        api<{ rows: TopicRow[] }>(`${base}/topics`),
      ]);
      setOv(o);
      setRows(s.rows);

      // روایت تحلیلی سطح ملی — 403 بی‌صدا نادیده گرفته می‌شود
      try {
        setInsights(await api<Insights>("/geo/national/insights"));
      } catch {
        setInsights(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  async function refresh() {
    setRefreshing(true);
    try {
      const res = await api<{ national: { written: number; suppressed: number } }>("/geo/national/refresh", { method: "POST" });
      await load(tab);
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

        <Tabs
          items={[
            { key: "province", label: "دید استان" },
            { key: "national", label: "دید کشور" },
          ]}
          value={tab}
          onChange={(k) => setTab(k as Tab)}
        />

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
