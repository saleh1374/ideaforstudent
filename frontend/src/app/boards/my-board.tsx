"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/labels";
import { Card, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { DataTable, type Column } from "@/components/ui/table";
import { SkeletonStats, SkeletonTable } from "@/components/ui/skeleton";
import { IconChart, IconShield, IconUsers, IconSparkles } from "@/components/ui/icons";

type LensRow = { rank: number; alias: string; value: number | null; is_me: boolean };
type Lens = {
  key: string;
  label_fa: string;
  unit: string;
  my_rank: number | null;
  count: number;
  eligible: boolean;
  rows: LensRow[];
};
type Agg = { value: number | null; count: number; suppressed: boolean };
type TopicCompare = {
  topic_id: number;
  title: string;
  school_mean: number | null;
  school_count: number;
  province_mean: number | null;
  province_count: number;
  gap: number | null;
  suppressed: boolean;
};
type MyBoard = {
  available: boolean;
  note_fa?: string;
  min_group: number;
  me: {
    alias: string;
    performance: number | null;
    prev_performance: number | null;
    growth: number | null;
    growth_pct: number | null;
    growth_hidden: boolean;
    growth_hidden_fa: string | null;
    mastery: number | null;
    official_count: number;
    ranks: Record<string, number | null>;
    counts: Record<string, number>;
  };
  lenses: Lens[];
  averages: { school: Agg; province: Agg; national_percentile: Agg };
  topic_compare: TopicCompare[];
  notes_fa: string[];
};
type BadgeItem = {
  key: string;
  title_fa: string;
  description_fa: string;
  earned: boolean;
  progress: number | null;
  progress_label_fa: string;
};
type Badges = { badges: BadgeItem[]; earned_count: number; note_fa: string };

const LENS_KEY_FA: Record<string, string> = {
  performance: "عملکرد",
  growth: "رشد",
  mastery: "تسط",
};

export function MyBoard() {
  const [board, setBoard] = useState<MyBoard | null>(null);
  const [badges, setBadges] = useState<Badges | null>(null);
  const [lens, setLens] = useState<string>("performance");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [b, g] = await Promise.all([api<MyBoard>("/boards/me"), api<Badges>("/boards/me/badges")]);
      setBoard(b);
      setBadges(g);
      if (b.lenses?.length && !b.lenses.some((l) => l.key === lens)) setLens(b.lenses[0].key);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
    } finally {
      setLoading(false);
    }
  }, [lens]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <div className="space-y-5">
        <SkeletonStats count={4} />
        <SkeletonTable rows={5} cols={4} />
      </div>
    );
  }

  if (error) return <Alert variant="danger" title="خطا در دریافت برد">{error}</Alert>;

  if (!board || !board.available) {
    return (
      <EmptyState
        icon={<IconShield size={26} />}
        title="برد شخصی در دسترس نیست"
        description={board?.note_fa ?? "برای این حساب پروندهٔ دانش‌آموز ثبت نشده است."}
      />
    );
  }

  const active = board.lenses.find((l) => l.key === lens) ?? board.lenses[0];
  const me = board.me;
  const growthValue = me.growth_pct !== null && me.growth_pct !== undefined ? `${me.growth_pct > 0 ? "+" : ""}${fa(me.growth_pct)}٪` : "—";

  const columns: Column<LensRow>[] = [
    {
      key: "rank",
      header: "رتبه",
      align: "center",
      render: (row) => (
        <span className={`num font-bold ${row.rank <= 3 ? "text-primary-600" : "text-ink-muted"}`}>{fa(row.rank)}</span>
      ),
    },
    {
      key: "alias",
      header: "نام مستعار",
      render: (row) => (
        <span className={row.is_me ? "font-bold text-primary-700" : "font-semibold text-ink"}>
          {row.alias}
          {row.is_me && <Badge tone="accent">تو</Badge>}
        </span>
      ),
    },
    {
      key: "value",
      header: active?.label_fa ?? "مقدار",
      align: "center",
      render: (row) => (
        <span className="num font-bold text-ink">
          {row.value === null ? "—" : `${fa(row.value)}٪`}
        </span>
      ),
    },
  ];

  const topicColumns: Column<TopicCompare>[] = [
    { key: "title", header: "مبحث", render: (r) => <span className="font-semibold text-ink">{r.title}</span> },
    {
      key: "school",
      header: "مدرسهٔ من",
      align: "center",
      render: (r) => (
        <span className="num">{r.school_mean === null ? "زیر حد جمعیت" : `${fa(r.school_mean)}٪`}</span>
      ),
    },
    {
      key: "province",
      header: "استان",
      align: "center",
      render: (r) => (
        <span className="num">{r.province_mean === null ? "زیر حد جمعیت" : `${fa(r.province_mean)}٪`}</span>
      ),
    },
    {
      key: "gap",
      header: "شکاف (مدرسه − استان)",
      align: "center",
      render: (r) =>
        r.gap === null ? (
          <span className="text-ink-faint">—</span>
        ) : (
          <span className={`num font-bold ${r.gap >= 0 ? "text-success-600" : "text-danger-600"}`}>
            {r.gap > 0 ? "+" : ""}
            {fa(r.gap)}٪
          </span>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <Section className="animate-fade-in">
        <Alert variant="info">سه نما، نه یک عدد (§8.1) — بین «عملکرد»، «رشد» و «تسط» جابه‌جا شو.</Alert>

        <div className="flex flex-wrap gap-2">
          {board.lenses.map((l) => (
            <button
              key={l.key}
              onClick={() => setLens(l.key)}
              className={`rounded-xl px-4 py-2 text-sm font-bold transition ${
                lens === l.key
                  ? "bg-brand-gradient text-white shadow-soft"
                  : "border border-line bg-surface text-ink-muted hover:border-primary-300"
              }`}
            >
              {l.label_fa}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="جایگاه من در مدرسه"
            value={active?.my_rank ? `${fa(active.my_rank)} از ${fa(active.count)}` : "بدون رتبه"}
            tone="primary"
            icon={<IconUsers size={20} />}
          />
          <StatCard
            label="عملکرد (آخرین آزمون رسمی)"
            value={me.performance !== null ? `${fa(me.performance)}٪` : "—"}
            tone="success"
            icon={<IconChart size={20} />}
          />
          <StatCard label="رشد نسبت به آزمون قبل" value={growthValue} tone="accent" icon={<IconChart size={20} />} />
          <StatCard
            label="صدک من در کشور"
            value={
              board.averages.national_percentile.suppressed
                ? `زیر حد جمعیت (${fa(board.averages.national_percentile.count)})`
                : fa(board.averages.national_percentile.value ?? 0)
            }
            tone="warning"
            icon={<IconSparkles size={20} />}
          />
        </div>

        {me.growth_hidden && me.growth_hidden_fa && <Alert variant="warning">{me.growth_hidden_fa}</Alert>}

        <div className="grid gap-3 sm:grid-cols-3">
          <Card>
            <p className="text-xs text-ink-muted">میانگین مدرسهٔ من</p>
            <p className="num mt-1 text-lg font-bold text-ink">
              {board.averages.school.suppressed
                ? `زیر حد جمعیت (${fa(board.averages.school.count)} نفر)`
                : `${fa(board.averages.school.value ?? 0)}٪`}
            </p>
          </Card>
          <Card>
            <p className="text-xs text-ink-muted">میانگین استان</p>
            <p className="num mt-1 text-lg font-bold text-ink">
              {board.averages.province.suppressed
                ? `زیر حد جمعیت (${fa(board.averages.province.count)} نفر)`
                : `${fa(board.averages.province.value ?? 0)}٪`}
            </p>
          </Card>
          <Card>
            <p className="text-xs text-ink-muted">تسط مؤثر من (E)</p>
            <p className="num mt-1 text-lg font-bold text-ink">
              {me.mastery !== null ? `${fa(me.mastery)}٪` : "هنوز داده‌ای ثبت نشده"}
            </p>
          </Card>
        </div>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold text-ink">برد مدرسه — {active?.label_fa}</h2>
            <Badge tone="neutral">نام مستعار</Badge>
          </div>
          <DataTable
            columns={columns}
            rows={active?.rows ?? []}
            keyOf={(r) => `${r.rank}-${r.alias}`}
            empty={
              <EmptyState
                icon={<IconChart size={24} />}
                title="هنوز آزمون رسمی‌ای ثبت نشده"
                description="پس از تصحیح آزمون دوره‌ای، جایگاه تو اینجا نمایش داده می‌شود."
              />
            }
          />
          <p className="mt-3 text-[11px] leading-6 text-ink-faint">
            ده نفر برتر و جایگاه تو (با یک نفر بالا و پایین) نمایش داده می‌شود؛ پایینِ جدول برای جلوگیری از شرمندگی حذف
            شده است (§8.2).
          </p>
        </Card>

        <Card>
          <h2 className="mb-3 text-sm font-bold text-ink">مقایسهٔ مبحثی: مدرسهٔ من در برابر استان</h2>
          <DataTable
            columns={topicColumns}
            rows={board.topic_compare}
            keyOf={(r) => String(r.topic_id)}
            empty={
              <EmptyState
                icon={<IconChart size={24} />}
                title="داده‌ای برای مقایسه نیست"
                description="پس از ثبت شواهد یادگیری، مقایسهٔ مبحثی اینجا ظاهر می‌شود."
              />
            }
          />
          <p className="mt-3 text-[11px] leading-6 text-ink-faint">
            هر آماره فقط با حداقل {fa(board.min_group)} نفر جمعیت نمایش داده می‌شود (§8.2).
          </p>
        </Card>
      </Section>

      {badges && (
        <Section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold text-ink">نشان‌ها و تقدیر (§8.4)</h2>
            <Badge tone="accent">{fa(badges.earned_count)} از {fa(badges.badges.length)} کسب شده</Badge>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {badges.badges.map((b) => (
              <Card key={b.key} className={b.earned ? "border-success-200 bg-success-50" : ""}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-bold text-ink">{b.title_fa}</p>
                    <p className="mt-1 text-xs leading-6 text-ink-muted">{b.description_fa}</p>
                  </div>
                  <Badge tone={b.earned ? "success" : "neutral"}>{b.earned ? "کسب شد" : "در دسترس"}</Badge>
                </div>
                <p className="mt-3 text-[11px] text-ink-faint">{b.progress_label_fa}</p>
              </Card>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-6 text-ink-faint">{badges.note_fa}</p>
        </Section>
      )}

      <Section>
        <ul className="space-y-2">
          {board.notes_fa.map((n, i) => (
            <li key={i} className="text-[11px] leading-6 text-ink-faint">
              • {n}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
