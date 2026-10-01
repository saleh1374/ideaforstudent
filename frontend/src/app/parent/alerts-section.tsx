"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { fa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { StatCard } from "@/components/ui/stat";
import { SkeletonStats } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconCheckCircle, IconInfo, IconRefresh, IconTarget } from "@/components/ui/icons";

/** هشدارهای هوشمند — GET /parent/children/{id}/alerts (سند §13) */
type AlertRow = {
  code: string;
  severity: "info" | "warning" | "danger";
  title: string;
  message: string;
  action: string;
  topic_id: number | null;
};

type AlertsData = {
  student_id: number;
  alerts: AlertRow[];
  counts: { danger: number; warning: number; info: number; total: number };
  thresholds: { gap_units: number; inactive_days: number; repeat_error_min: number };
  note_fa: string;
};

const VARIANT: Record<AlertRow["severity"], "info" | "warning" | "danger"> = {
  info: "info",
  warning: "warning",
  danger: "danger",
};

const TONE: Record<AlertRow["severity"], Tone> = {
  info: "info",
  warning: "warning",
  danger: "danger",
};

const SEVERITY_FA: Record<AlertRow["severity"], string> = {
  info: "اطلاع‌رسانی",
  warning: "نیازمند توجه",
  danger: "اولویت بالا",
};

export function AlertsSection({ childId }: { childId: number }) {
  const [data, setData] = useState<AlertsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api<AlertsData>(`/parent/children/${childId}/alerts`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) toast(e.detail ?? "این فرزند به شما متصل نیست", "error");
      else setError(e instanceof Error ? e.message : "خطا در دریافت هشدارها");
    } finally {
      setLoading(false);
    }
  }, [childId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !data) return <SkeletonStats count={4} />;

  return (
    <Section
      title="هشدارهای هوشمند"
      subtitle="سیگنال‌های معنادار بر پایه داده‌های همین فرزند؛ هر هشدار آرام و همراه با یک اقدام مشخص است."
      action={
        <Button variant="soft" size="sm" icon={<IconRefresh size={14} />} loading={loading} onClick={() => void load()}>
          تازه‌سازی
        </Button>
      }
    >
      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {data && (
        <>
          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label="هشدارها"
              value={fa(data.counts.total)}
              tone="primary"
              icon={<IconAlert size={20} />}
              hint="مجموع همه سطوح"
            />
            <StatCard
              label="اولویت بالا"
              value={fa(data.counts.danger)}
              tone={data.counts.danger > 0 ? "danger" : "success"}
              icon={<IconAlert size={20} />}
              hint={data.counts.danger > 0 ? "زودتر بررسی شود" : "مورد فوری نیست"}
            />
            <StatCard
              label="نیازمند توجه"
              value={fa(data.counts.warning)}
              tone={data.counts.warning > 0 ? "warning" : "success"}
              icon={<IconTarget size={20} />}
              hint="برای این هفته"
            />
            <StatCard
              label="اطلاع‌رسانی"
              value={fa(data.counts.info)}
              tone="sky"
              icon={<IconCheckCircle size={20} />}
              hint="پیشرفت‌ها و یادداشت‌ها"
            />
          </section>

          {data.alerts.length === 0 ? (
            <EmptyState
              icon={<IconCheckCircle size={26} />}
              title="هشداری ثبت نشده است"
              description="سیگنال نگران‌کننده‌ای در برنامه، آزمون‌ها و مباحث فرزندتان دیده نمی‌شود."
            />
          ) : (
            <ul className="space-y-3">
              {data.alerts.map((a, i) => (
                <li key={`${a.code}-${i}`}>
                  <Alert variant={VARIANT[a.severity]} title={a.title}>
                    <div className="space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={TONE[a.severity]} dot>
                          {SEVERITY_FA[a.severity]}
                        </Badge>
                        <span className="text-xs">{a.message}</span>
                      </div>
                      <p className="flex items-start gap-1.5 rounded-lg bg-white/60 px-2.5 py-1.5 text-[11px] font-semibold leading-5">
                        <IconTarget size={13} />
                        اقدام پیشنهادی: {a.action}
                      </p>
                    </div>
                  </Alert>
                </li>
              ))}
            </ul>
          )}

          <Alert variant="info" title="چگونه ساخته می‌شود؟">
            <p className="text-xs leading-6">
              {data.note_fa}
              <br />
              آستانه‌ها: شکاف پیشرفت/تسط {fa(data.thresholds.gap_units)} واحد · «بدون فعالیت» بیش از{" "}
              {fa(data.thresholds.inactive_days)} روز · «خطای تکراری» از {fa(data.thresholds.repeat_error_min)} مورد
              همسان. بدون هوش مصنوعی بیرونی و بدون مقایسه با فرزندان دیگر.
            </p>
          </Alert>

          {data.counts.info > 0 && (
            <p className="flex items-center gap-1.5 text-[11px] leading-6 text-ink-faint">
              <IconInfo size={13} /> هشدارهای سطح «اطلاع‌رسانی» پیشرفت‌ها را نشان می‌دهند؛ لحن همه هشدارها آرام است و
              هشدار بی‌پاسخ داده نمی‌شود.
            </p>
          )}
        </>
      )}
    </Section>
  );
}
