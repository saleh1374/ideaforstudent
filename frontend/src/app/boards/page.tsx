"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { STATUS_FA, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { IconChart, IconShield, IconUsers } from "@/components/ui/icons";

type BoardRow = {
  key: string;
  kind: string;
  students_with_data: number;
  avg_mastery: number | null;
  avg_retention: number | null;
  weak_count: number | null;
  status_counts: Record<string, number> | null;
  suppressed: boolean;
};

type Board = {
  scope: string;
  min_group: number;
  note_fa: string;
  rows: BoardRow[];
  total?: BoardRow;
};

type Tab = "school" | "province" | "national";

const TAB_FA: Record<Tab, string> = {
  school: "مدرسه",
  province: "استان",
  national: "کشور",
};

export default function BoardsPage() {
  const [tab, setTab] = useState<Tab>("school");
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (t: Tab) => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    setBoard(null);
    setError("");
    setLoading(true);
    try {
      // MVP: شناسه‌های نمونه (مدرسه ۱، استان ۱)
      const path = t === "school" ? "/boards/school/1" : t === "province" ? "/boards/province/1" : "/boards/national";
      setBoard(await api<Board>(path));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  const columns: Column<BoardRow>[] = [
    { key: "key", header: "کد مستعار", render: (row) => <span className="font-semibold text-ink">{row.key}</span> },
    {
      key: "students",
      header: "دانش‌آموز دارای داده",
      align: "center",
      render: (row) => <span className="num">{fa(row.students_with_data)}</span>,
    },
    {
      key: "mastery",
      header: "تسط",
      align: "center",
      render: (row) =>
        row.suppressed ? (
          <Badge tone="neutral">زیر حد نصاب</Badge>
        ) : (
          <span className="num font-bold text-ink">{row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"}</span>
        ),
    },
    {
      key: "retention",
      header: "ماندگاری",
      align: "center",
      render: (row) => <span className="num">{row.suppressed || row.avg_retention === null ? "—" : `${fa(row.avg_retention * 100)}٪`}</span>,
    },
    {
      key: "weak",
      header: "ضعیف/بحرانی",
      align: "center",
      render: (row) => <span className="num font-semibold text-danger-600">{row.weak_count === null ? "—" : fa(row.weak_count)}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (row) =>
        row.status_counts ? (
          <span className="inline-flex flex-wrap justify-center gap-1">
            {Object.entries(row.status_counts).map(([k, v]) => (
              <span key={k} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-ink-muted">
                {STATUS_FA[k] ?? k}: {fa(v)}
              </span>
            ))}
          </span>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="بردهای تحلیلی"
          description="نام‌ها مستعار است و اعداد زیر حداقل جمعیت نمایش داده نمی‌شوند — نه تخمین، نه رنگ."
          crumbs={[{ label: "دانشیار" }, { label: "عمومی" }, { label: "بردها" }]}
          badge={
            <Badge tone="accent" dot>
              حریم خصوصی فعال
            </Badge>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت برد">{error}</Alert>}

        <Tabs
          items={(["school", "province", "national"] as Tab[]).map((t) => ({ key: t, label: TAB_FA[t] }))}
          value={tab}
          onChange={(k) => setTab(k as Tab)}
        />

        {loading && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <SkeletonTable rows={5} cols={6} />
          </div>
        )}

        {!loading && board && (
          <Section className="animate-fade-in">
            <Alert variant="info">{board.note_fa}</Alert>

            {board.total && (
              <Card>
                <div className="mb-4 flex items-center gap-2">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                    <IconChart size={17} />
                  </span>
                  <h2 className="text-sm font-bold text-ink">جمع کلی</h2>
                </div>
                <BoardAggregate row={board.total} />
              </Card>
            )}

            <DataTable
              columns={columns}
              rows={board.rows}
              keyOf={(r) => r.key}
              empty={
                <EmptyState
                  icon={<IconUsers size={26} />}
                  title="ردیفی برای نمایش نیست"
                  description="در این محدوده، داده‌ای زیر حد نصاب جمعیت ثبت نشده است."
                />
              }
            />

            <p className="text-[11px] leading-6 text-ink-faint">
              زیر حداقل جمعیت {fa(board.min_group)} نفر، عددی نمایش داده نمی‌شود — نه تخمین، نه رنگ (حریم خصوصی §8.2).
            </p>
          </Section>
        )}

        {!loading && !board && !error && (
          <EmptyState icon={<IconShield size={26} />} title="داده‌ای در دسترس نیست" description="برای این محدوده، بردی بازگردانده نشد." />
        )}
      </div>
    </AppShell>
  );
}

function BoardAggregate({ row }: { row: BoardRow }) {
  if (row.suppressed) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-surface-sunken p-6 text-center">
        <p className="text-xs leading-6 text-ink-muted">
          با جمعیت فعلی ({fa(row.students_with_data)} نفر دارای داده) زیر حد نصاب است.
        </p>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard label="دانش‌آموز" value={fa(row.students_with_data)} tone="primary" icon={<IconUsers size={20} />} />
      <StatCard label="تسط" value={row.avg_mastery !== null ? `${fa(row.avg_mastery)}٪` : "—"} tone="success" icon={<IconChart size={20} />} />
      <StatCard label="ماندگاری" value={row.avg_retention !== null ? `${fa(row.avg_retention * 100)}٪` : "—"} tone="accent" icon={<IconChart size={20} />} />
      <StatCard label="ضعیف/بحرانی" value={row.weak_count === null ? "—" : fa(row.weak_count)} tone="danger" icon={<IconShield size={20} />} />
    </div>
  );
}
