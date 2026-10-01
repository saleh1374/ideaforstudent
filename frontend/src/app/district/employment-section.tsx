"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa, EMPLOYMENT_TYPE_FA, REQUEST_STATUS_FA, subjectFa } from "@/lib/labels";
import { Section } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Select } from "@/components/ui/forms";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconCheckCircle, IconInbox, IconX } from "@/components/ui/icons";

type RequestRow = {
  id: number;
  school_id: number;
  full_name: string;
  employment_type: string;
  organization: string;
  subject: string | null;
  status: string;
  created_at: string;
};

type DecideResult = { ok: boolean; status?: string; reason?: string };

export function EmploymentSection({ onChanged }: { onChanged?: () => void }) {
  const [rows, setRows] = useState<RequestRow[]>([]);
  const [districtId, setDistrictId] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [schoolNames, setSchoolNames] = useState<Record<number, string>>({});

  const load = useCallback(async (st: string) => {
    setLoading(true);
    try {
      const res = await api<{ district_id: number; requests: RequestRow[] }>(
        `/district/employment-requests${st ? `?status=${encodeURIComponent(st)}` : ""}`
      );
      setRows(res.requests);
      setDistrictId(res.district_id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت درخواست‌ها");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(status);
  }, [status, load]);

  // نام مدرسه هر درخواست (برای نمایش بهتر) — شکست آن بی‌اثر است
  useEffect(() => {
    let alive = true;
    api<{ schools: { id: number; name: string }[] }>("/district/me/schools")
      .then((res) => {
        if (!alive) return;
        const map: Record<number, string> = {};
        for (const s of res.schools) map[s.id] = s.name;
        setSchoolNames(map);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  async function decide(row: RequestRow, approve: boolean) {
    setBusyId(row.id);
    try {
      // سرور برای درخواستِ غیرفعال/تصمیم‌گرفته‌شده به‌جای خطا 200 با {ok:false} برمی‌گرداند
      const res = await api<DecideResult>(`/admin/employment-requests/${row.id}/decide`, {
        method: "POST",
        json: { approve },
      });
      if (!res.ok) {
        toast(res.reason ?? "این درخواست قابل تصمیم‌گیری نیست", "warning");
      } else {
        toast(approve ? `درخواست «${row.full_name}» تأیید شد.` : `درخواست «${row.full_name}» رد شد.`, approve ? "success" : "info");
        onChanged?.();
      }
      await load(status);
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در تصمیم‌گیری", "error");
    } finally {
      setBusyId(null);
    }
  }

  const columns: Column<RequestRow>[] = [
    {
      key: "name",
      header: "درخواست‌دهنده",
      render: (row) => (
        <div className="space-y-1">
          <p className="font-semibold text-ink">{row.full_name}</p>
          <p className="text-[11px] text-ink-faint">
            {schoolNames[row.school_id] ?? `مدرسه #${row.school_id}`} · {row.organization}
          </p>
        </div>
      ),
    },
    {
      key: "type",
      header: "نوع استخدام",
      align: "center",
      render: (row) => <Badge tone="neutral">{EMPLOYMENT_TYPE_FA[row.employment_type] ?? row.employment_type}</Badge>,
    },
    {
      key: "subject",
      header: "درس",
      align: "center",
      render: (row) => <span className="text-xs">{row.subject ? subjectFa(row.subject) : "—"}</span>,
    },
    {
      key: "created",
      header: "تاریخ ثبت",
      align: "center",
      render: (row) => <span className="num text-xs">{faDate(row.created_at)}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) => (
        <Badge tone={statusTone(row.status)} dot>
          {REQUEST_STATUS_FA[row.status] ?? row.status}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (row) =>
        row.status === "pending" ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              size="sm"
              variant="success"
              loading={busyId === row.id}
              onClick={() => decide(row, true)}
              icon={<IconCheckCircle size={14} />}
            >
              تأیید
            </Button>
            <Button size="sm" variant="ghost" loading={busyId === row.id} onClick={() => decide(row, false)} icon={<IconX size={14} />}>
              رد
            </Button>
          </div>
        ) : (
          <span className="text-[11px] text-ink-faint">بسته شده</span>
        ),
    },
  ];

  return (
    <Section
      title="درخواست‌های استخدام مدارس ناحیه"
      subtitle="تصمیم فقط در سطح ناحیه و بالاتر مجاز است؛ درخواست‌های خودکار (سیاست) نیازی به تأیید ندارند."
      action={
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-52">
          <option value="">همه وضعیت‌ها</option>
          <option value="pending">در انتظار تأیید</option>
          <option value="approved">تأییدشده</option>
          <option value="rejected">ردشده</option>
          <option value="auto_approved">تأیید خودکار (سیاست)</option>
        </Select>
      }
    >
      {districtId !== null && <Alert variant="info">ناحیه فعال: شناسه {fa(districtId)}</Alert>}

      {error && <Alert variant="danger" title="خطا">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={4} cols={6} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          keyOf={(r) => r.id}
          empty={
            <EmptyState
              compact
              icon={<IconInbox size={24} />}
              title="درخواستی در این وضعیت نیست"
              description="درخواست‌های جدید استخدام از مدرسه‌های ناحیه اینجا نمایش داده می‌شود."
            />
          }
        />
      )}

      <p className="text-[11px] leading-6 text-ink-faint">
        اگر درخواستی قبلاً تصمیم گرفته شده باشد سرور به‌جای خطا پاسخ «قابل تصمیم نیست» می‌دهد و هشدار نمایش داده می‌شود.
      </p>
    </Section>
  );
}

function faDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fa-IR", { dateStyle: "short" });
}
