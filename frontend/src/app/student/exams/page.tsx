"use client";

import { useEffect, useMemo, useState } from "react";
import { api, getToken, ExamSummary } from "@/lib/api";
import { EXAM_TYPE_FA, fa, subjectFa, gradeFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { SearchInput, Select } from "@/components/ui/forms";
import { SkeletonCard } from "@/components/ui/skeleton";
import { IconExam, IconHome, IconSearch, IconSend } from "@/components/ui/icons";

function fmtDate(v: string | null): string | null {
  if (!v) return null;
  try {
    return new Date(v).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return v;
  }
}

export default function ExamsPage() {
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ exams: ExamSummary[] }>("/student/exams")
      .then((d) => setExams(d.exams))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const types = useMemo(() => Array.from(new Set(exams.map((e) => e.type))), [exams]);

  const visible = useMemo(
    () =>
      exams.filter(
        (e) => (typeFilter === "all" || e.type === typeFilter) && (query.trim() === "" || e.title.includes(query.trim()))
      ),
    [exams, query, typeFilter]
  );

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="آزمون‌ها"
          description="پاسخ‌ها و زمان پاسخ ثبت می‌شود تا تحلیل خطا و بازآزمون ترمیمی ساخته شود."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "آزمون‌ها" }]}
          actions={
            <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
              خانه
            </ButtonLink>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت آزمون‌ها">{error}</Alert>}

        {!loading && !error && (
          <>
            <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label="کل آزمون‌ها" value={fa(exams.length)} tone="primary" icon={<IconExam size={20} />} />
              <StatCard label="در دسترس" value={fa(visible.length)} tone="accent" icon={<IconSend size={20} />} hint="با فیلتر فعلی" />
              <StatCard
                label="مجموع سؤالات"
                value={fa(exams.reduce((s, e) => s + e.item_count, 0))}
                tone="sky"
                icon={<IconExam size={20} />}
              />
              <StatCard label="انواع آزمون" value={fa(types.length)} tone="success" icon={<IconExam size={20} />} />
            </section>

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <SearchInput value={query} onChange={setQuery} placeholder="جستجوی عنوان آزمون…" className="w-full max-w-sm" />
              <Select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="w-full sm:w-52">
                <option value="all">همه انواع</option>
                {types.map((t) => (
                  <option key={t} value={t}>
                    {EXAM_TYPE_FA[t] ?? t}
                  </option>
                ))}
              </Select>
            </div>

            {visible.length === 0 && !loading && (
              <EmptyState
                icon={<IconSearch size={26} />}
                title="آزمونی با این فیلترها نیست"
                description="فیلتر را تغییر بده یا صبر کن تا آزمون جدید منتشر شود."
                action={
                  <Button
                    type="button"
                    variant="soft"
                    size="sm"
                    onClick={() => {
                      setQuery("");
                      setTypeFilter("all");
                    }}
                  >
                    حذف فیلترها
                  </Button>
                }
              />
            )}

            <div className="grid gap-4 md:grid-cols-2">
              {visible.map((e) => {
                const opens = fmtDate(e.opens_at);
                const closes = fmtDate(e.closes_at);
                return (
                  <Card key={e.id} hover className="flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone="primary">{EXAM_TYPE_FA[e.type] ?? e.type}</Badge>
                          <Badge tone="neutral">{subjectFa(e.subject)}</Badge>
                        </div>
                        <h3 className="mt-2 text-sm font-bold text-ink">{e.title}</h3>
                      </div>
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
                        <IconExam size={19} />
                      </span>
                    </div>

                    <div className="mt-auto space-y-1.5 rounded-xl bg-surface-sunken px-3.5 py-3 text-[11px] text-ink-muted">
                      <p className="num">{fa(e.item_count)} سؤال · {gradeFa(e.grade)}</p>
                      {opens && <p>باز شدن: {opens}</p>}
                      {closes && <p>بسته شدن: {closes}</p>}
                    </div>

                    <ButtonLink href={`/student/exams/${e.id}`} size="sm" className="w-full" icon={<IconSend size={14} />}>
                      شروع آزمون
                    </ButtonLink>
                  </Card>
                );
              })}
            </div>
          </>
        )}

        {loading && (
          <div className="grid gap-4 md:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}
      </div>
    </AppShell>
  );
}
