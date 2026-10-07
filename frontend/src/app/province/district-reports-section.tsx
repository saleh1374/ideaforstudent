"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconInbox, IconRefresh, IconSend } from "@/components/ui/icons";

type DistrictReport = {
  id: number;
  district_id: number;
  district_name: string | null;
  title_fa: string;
  period_start: string;
  period_end: string;
  status: string;
  status_fa: string;
  created_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  review_note: string | null;
};

const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  submitted: "info",
  reviewed: "info",
  returned: "warning",
  approved: "success",
};

function faDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fa-IR");
}

/**
 * گزارش‌های ارسال‌شده ناحیه‌های استان (سند ناحیه §32) + تصمیم استان:
 * «تأیید» یا «برگشت برای اصلاح» (برگشت بدون دلیل اصلاح از سرور رد می‌شود).
 */
export function DistrictReportsSection({ provinceId }: { provinceId: number | null }) {
  const [reports, setReports] = useState<DistrictReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<DistrictReport | null>(null);
  const [decision, setDecision] = useState<"approve" | "return">("approve");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (provinceId === null) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await api<{ total: number; reports: DistrictReport[] }>(
        `/geo/province/${provinceId}/district-reports`
      );
      setReports(res.reports);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت گزارش‌ها");
    } finally {
      setLoading(false);
    }
  }, [provinceId]);

  useEffect(() => {
    load();
  }, [load]);

  function open(r: DistrictReport) {
    setSelected(r);
    setDecision("approve");
    setNote("");
  }

  async function submitDecision() {
    if (!selected || provinceId === null) return;
    if (decision === "return" && !note.trim()) {
      toast("دلیل اصلاح برای برگشت گزارش الزامی است.", "error");
      return;
    }
    setBusy(true);
    try {
      await api(`/geo/province/${provinceId}/district-reports/${selected.id}/decision`, {
        method: "POST",
        json: { decision, note_fa: note.trim() || null },
      });
      toast(decision === "approve" ? "گزارش تأیید شد." : "گزارش برای اصلاح برگشت خورد.", "success");
      setSelected(null);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ثبت تصمیم", "error");
    } finally {
      setBusy(false);
    }
  }

  const cols: Column<DistrictReport>[] = [
    {
      key: "district",
      header: "ناحیه",
      render: (r) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{r.district_name ?? `ناحیه ${fa(r.district_id)}`}</p>
          <p className="text-[11px] text-ink-faint">{r.title_fa}</p>
        </div>
      ),
    },
    {
      key: "period",
      header: "دوره",
      align: "center",
      render: (r) => (
        <span className="num text-xs">
          {faDate(r.period_start)} → {faDate(r.period_end)}
        </span>
      ),
    },
    { key: "submitted", header: "ارسال", align: "center", render: (r) => <span className="num text-xs">{faDate(r.submitted_at)}</span> },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (r) => (
        <Badge tone={STATUS_TONE[r.status] ?? "neutral"} dot>
          {r.status_fa}
        </Badge>
      ),
    },
    { key: "note", header: "نتیجه بررسی", render: (r) => <span className="text-[11px] leading-5 text-ink-muted">{r.review_note ?? "—"}</span> },
    {
      key: "act",
      header: "",
      align: "end",
      render: (r) =>
        r.status === "submitted" ? (
          <Button size="sm" variant="soft" onClick={() => open(r)}>
            بررسی
          </Button>
        ) : null,
    },
  ];

  const pending = reports.filter((r) => r.status === "submitted").length;

  return (
    <Section
      title="گزارش‌های ناحیه‌های استان"
      subtitle="ارسال ناحیه → بررسی استان: تأیید، یا برگشت برای اصلاح با دلیل الزامی (§32)."
      action={
        <Button size="sm" variant="ghost" icon={<IconRefresh size={15} />} onClick={load}>
          تازه‌سازی
        </Button>
      }
    >
      {provinceId === null ? (
        <Alert variant="warning">حوزه استانی شما تعیین نشده است؛ گزارش ناحیه‌ها در دسترس نیست.</Alert>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Badge tone={pending > 0 ? "warning" : "success"} dot>
              {pending > 0 ? `${fa(pending)} گزارش در انتظار بررسی` : "گزارش در انتظار بررسی نیست"}
            </Badge>
            <Badge tone="neutral">{fa(reports.length)} گزارش کل</Badge>
          </div>

          {error && <Alert variant="danger" title="خطا">{error}</Alert>}

          <DataTable
            columns={cols}
            rows={reports}
            keyOf={(r) => r.id}
            loading={loading}
            empty={
              <EmptyState
                compact
                icon={<IconInbox size={24} />}
                title="گزارشی از ناحیه‌ها نرسیده"
                description="وقتی ناحیه گزارش دوره را ارسال کند، اینجا برای بررسی شما ظاهر می‌شود."
              />
            }
          />

          <Modal
            open={selected !== null}
            onClose={() => setSelected(null)}
            title={selected ? `گزارش: ${selected.title_fa}` : ""}
            size="md"
            footer={
              <>
                <Button variant="ghost" onClick={() => setSelected(null)}>
                  انصراف
                </Button>
                <Button
                  variant={decision === "approve" ? "success" : "primary"}
                  loading={busy}
                  onClick={submitDecision}
                  icon={decision === "approve" ? <IconCheckCircle size={15} /> : <IconSend size={15} />}
                >
                  {decision === "approve" ? "تأیید گزارش" : "برگشت برای اصلاح"}
                </Button>
              </>
            }
          >
            {selected && (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge tone="accent">{selected.district_name ?? `ناحیه ${fa(selected.district_id)}`}</Badge>
                  <Badge tone={STATUS_TONE[selected.status] ?? "neutral"}>{selected.status_fa}</Badge>
                  <Badge tone="neutral">
                    دوره {faDate(selected.period_start)} تا {faDate(selected.period_end)}
                  </Badge>
                </div>

                {selected.review_note && (
                  <Alert variant="info">یادداشت قبلی بررسی: {selected.review_note}</Alert>
                )}

                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant={decision === "approve" ? "success" : "ghost"}
                    onClick={() => setDecision("approve")}
                  >
                    تأیید
                  </Button>
                  <Button
                    size="sm"
                    variant={decision === "return" ? "primary" : "ghost"}
                    onClick={() => setDecision("return")}
                  >
                    برگشت برای اصلاح
                  </Button>
                </div>

                <Field
                  label={decision === "return" ? "دلیل اصلاح (الزامی)" : "یادداشت (اختیاری)"}
                  required={decision === "return"}
                  hint="این متن برای ناحیه ارسال و در لاگ ممیزی ثبت می‌شود."
                >
                  <Textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder={decision === "return" ? "چه چیزی باید اصلاح شود؟" : "نکته‌ای برای ناحیه دارید؟"}
                  />
                </Field>
              </div>
            )}
          </Modal>
        </>
      )}
    </Section>
  );
}
