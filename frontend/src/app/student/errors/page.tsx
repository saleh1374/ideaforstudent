"use client";

import { useEffect, useMemo, useState } from "react";
import { api, getToken, ErrorOut } from "@/lib/api";
import { CAUSE_FA, CAUSE_SHORT, fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Select } from "@/components/ui/forms";
import { HorizontalBars } from "@/components/ui/charts";
import { SkeletonCard } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconCheckCircle, IconClock, IconHome, IconRefresh, IconTarget } from "@/components/ui/icons";

const STATUS_FA: Record<string, string> = {
  open: "باز",
  in_remediation: "در حال ترمیم",
  resolved: "رفع‌شده",
  relapsed: "بازگشته",
};

const STATUS_FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "همه" },
  { key: "open", label: "باز" },
  { key: "in_remediation", label: "در حال ترمیم" },
  { key: "resolved", label: "رفع‌شده" },
  { key: "relapsed", label: "بازگشته" },
];

/** کلیدهای شش‌گانهٔ علت — همان SIX_CAUSES سمت سرور (POST /errors/{id}/reflect). */
const SIX_CAUSES = Object.keys(CAUSE_FA);

/** ردیف دفترچهٔ خطا + فیلدهای توضیحی که سرور برای «اندیشیدن دربارهٔ خطا» می‌فرستد. */
type ErrorRow = ErrorOut & {
  cause_fa?: string;
  predicted_cause?: string | null;
  declared_cause?: string | null;
  certainty?: number | null;
  unclear?: boolean;
  needs_reflection?: boolean;
};

type RetestPlan = {
  targets: { topic_id: number; title: string; causes: Record<string, number>; error_ids: number[] }[];
  can_build: boolean;
  note_fa: string;
};

export default function ErrorNotebookPage() {
  const [errors, setErrors] = useState<ErrorRow[]>([]);
  const [byCause, setByCause] = useState<Record<string, number>>({});
  const [causeFilter, setCauseFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState<RetestPlan | null>(null);
  const [building, setBuilding] = useState(false);
  const [reflectCause, setReflectCause] = useState<Record<number, string>>({});
  const [reflectingId, setReflectingId] = useState<number | null>(null);

  /** اندیشیدن دربارهٔ خطا (§6.2): POST /student/errors/{id}/reflect با { cause }. */
  async function reflect(e: ErrorRow) {
    const cause = reflectCause[e.id];
    if (!cause) return;
    setReflectingId(e.id);
    try {
      const res = await api<{ ok: boolean; cause: string; cause_fa: string; message_fa: string }>(
        `/student/errors/${e.id}/reflect`,
        { method: "POST", json: { cause } }
      );
      toast(res.message_fa, "success");
      setErrors((prev) =>
        prev.map((x) =>
          x.id === e.id
            ? { ...x, cause: res.cause, cause_fa: res.cause_fa, declared_cause: res.cause, needs_reflection: false }
            : x
        )
      );
      // توزیع علت‌ها را هم به‌روز نگه می‌داریم (عدد فیلترها از سرور تغییر نمی‌کند)
      setByCause((prev) => {
        if (e.cause === res.cause) return prev;
        const next = { ...prev };
        if (typeof next[e.cause] === "number") next[e.cause] = Math.max(0, next[e.cause] - 1);
        if (next[e.cause] === 0) delete next[e.cause];
        next[res.cause] = (next[res.cause] ?? 0) + 1;
        return next;
      });
      setReflectCause((prev) => {
        const copy = { ...prev };
        delete copy[e.id];
        return copy;
      });
    } catch (err) {
      toast(err instanceof Error ? err.message : "خطا در ثبت علت خطا", "error");
    } finally {
      setReflectingId(null);
    }
  }

  async function loadPlan() {
    try {
      setPlan(await api<RetestPlan>("/student/retest/plan"));
    } catch {
      /* بی‌رابط */
    }
  }

  async function buildRetest() {
    setBuilding(true);
    try {
      const out = await api<{ exam_id: number }>("/student/retest/build", { method: "POST" });
      toast("بازآزمون ترمیمی ساخته شد", "success");
      await loadPlan();
      window.location.href = `/student/exams/${out.exam_id}`;
    } catch (e) {
      toast(e instanceof Error ? e.message : "خطا در ساخت بازآزمون", "error");
      setBuilding(false);
    }
  }

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ errors: ErrorRow[]; by_cause: Record<string, number> }>("/student/errors")
      .then((d) => {
        setErrors(d.errors);
        setByCause(d.by_cause);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    loadPlan();
  }, []);

  const stats = useMemo(() => {
    const open = errors.filter((e) => e.status === "open").length;
    const relapsed = errors.filter((e) => e.status === "relapsed").length;
    const resolved = errors.filter((e) => e.status === "resolved").length;
    return { total: errors.length, open, relapsed, resolved };
  }, [errors]);

  const visible = useMemo(
    () =>
      errors.filter(
        (e) => (causeFilter === "all" || e.cause === causeFilter) && (statusFilter === "all" || e.status === statusFilter)
      ),
    [errors, causeFilter, statusFilter]
  );

  const causeData = Object.entries(byCause).map(([c, n]) => ({ label: CAUSE_FA[c] ?? c, value: n }));

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="دفترچه خطا"
          description="هر خطا یک سیگنال است؛ علت‌ها را ببین و با بازآزمون ترمیمی تثبیت کن."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "دفترچه خطا" }]}
          actions={
            <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
              خانه
            </ButtonLink>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت دفترچه">{error}</Alert>}

        {!loading && !error && (
          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="کل خطاها" value={fa(stats.total)} tone="primary" icon={<IconAlert size={20} />} />
            <StatCard label="خطای باز" value={fa(stats.open)} tone="warning" icon={<IconClock size={20} />} hint="نیازمند کار" />
            <StatCard label="در حال ترمیم" value={fa(stats.relapsed)} tone="danger" icon={<IconRefresh size={20} />} hint="بازگشته یا در جریان" />
            <StatCard label="رفع‌شده" value={fa(stats.resolved)} tone="success" icon={<IconCheckCircle size={20} />} />
          </section>
        )}

        {/* ——— retest plan ——— */}
        {plan && plan.can_build && (
          <Card variant="gradient" className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/20 text-white">
                  <IconTarget size={19} />
                </span>
                <div>
                  <h2 className="text-sm font-extrabold text-white">بازآزمون ترمیمی پیشنهادی</h2>
                  <p className="mt-1 text-xs leading-6 text-white/75">{plan.note_fa}</p>
                </div>
              </div>
              <Button size="sm" variant="ghost" className="border-white/30 bg-white/15 text-white hover:bg-white/25 hover:text-white" loading={building} onClick={buildRetest}>
                ساخت و شروع بازآزمون
              </Button>
            </div>
            <ul className="flex flex-wrap gap-2">
              {plan.targets.map((t) => (
                <li key={t.topic_id} className="rounded-xl bg-white/15 px-3 py-2 text-[11px] font-semibold text-white">
                  {t.title}
                  <span className="mr-2 font-normal text-white/70">
                    {Object.entries(t.causes)
                      .map(([c, n]) => `${CAUSE_FA[c] ?? c}: ${fa(n)}`)
                      .join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {/* ——— cause distribution ——— */}
        <div className="grid gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader title="توزیع علت خطاها" subtitle="روی هر مورد بزن تا فیلتر شود" icon={<IconAlert size={17} />} />
            {causeData.length === 0 ? (
              <EmptyState compact title="هنوز خطایی ثبت نشده" description="با شروع آزمون‌ها، علت خطاها اینجا دسته‌بندی می‌شود." />
            ) : (
              <HorizontalBars data={causeData} showTotal />
            )}
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader
              title="لیست خطاها"
              subtitle={`${fa(visible.length)} مورد`}
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-auto py-1.5 text-xs">
                    {STATUS_FILTERS.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                </div>
              }
            />

            {/* cause chips */}
            <div className="mb-4 flex flex-wrap gap-2">
              <button
                onClick={() => setCauseFilter("all")}
                className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition ${
                  causeFilter === "all" ? "bg-primary-600 text-white shadow-soft" : "bg-slate-100 text-ink-muted hover:bg-primary-50 hover:text-primary-700"
                }`}
              >
                همه علت‌ها
              </button>
              {Object.entries(byCause).map(([c, n]) => (
                <button
                  key={c}
                  onClick={() => setCauseFilter(causeFilter === c ? "all" : c)}
                  className={`num rounded-full px-3 py-1.5 text-[11px] font-semibold transition ${
                    causeFilter === c ? "bg-primary-600 text-white shadow-soft" : "bg-slate-100 text-ink-muted hover:bg-primary-50 hover:text-primary-700"
                  }`}
                >
                  {CAUSE_FA[c] ?? c} · {fa(n)}
                </button>
              ))}
            </div>

            {loading && <div className="space-y-3"><SkeletonCard /><SkeletonCard /></div>}

            {!loading && visible.length === 0 && (
              <EmptyState
                compact
                title="خطایی با این فیلترها نیست"
                description="فیلترها را تغییر بده یا صبر کن تا آزمون‌های جدید ثبت شوند."
                action={
                  <Button size="sm" variant="soft" type="button" onClick={() => { setCauseFilter("all"); setStatusFilter("all"); }}>
                    حذف فیلترها
                  </Button>
                }
              />
            )}

            <div className="space-y-3">
              {visible.map((e) => (
                <div
                  key={e.id}
                  className={`rounded-2xl border p-4 transition ${
                    e.status === "relapsed"
                      ? "border-danger-100 bg-danger-50/50"
                      : "border-line bg-surface hover:border-primary-200 hover:shadow-soft"
                  }`}
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge tone={causeFilter === e.cause ? "primary" : "neutral"}>{CAUSE_FA[e.cause] ?? e.cause}</Badge>
                      <Badge tone={statusTone(e.status)} dot>
                        {STATUS_FA[e.status] ?? e.status}
                      </Badge>
                    </div>
                    <span className="num text-[11px] text-ink-faint">مبحث #{e.topic_id}</span>
                  </div>
                  <p className="text-sm font-semibold leading-7 text-ink">{e.item?.body}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-4 text-[11px] text-ink-muted">
                    <span>
                      پاسخ درست: <b className="text-success-600">{e.item?.correct}</b>
                    </span>
                    {e.item?.options && e.item.options[e.item.correct] && (
                      <span className="text-ink-faint">{e.item.options[e.item.correct]}</span>
                    )}
                  </div>

                  {/* ——— اندیشیدن دربارهٔ خطا (§6.2) — فقط برای خطای باز ——— */}
                  {e.status === "open" && (
                    <div className="mt-3 rounded-xl border border-line bg-surface-sunken p-3">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-bold text-ink">اندیشیدن دربارهٔ خطا</p>
                        <p className="text-[11px] text-ink-faint">
                          {e.needs_reflection
                            ? "علت تشخیص داده نشده؛ خودت علت را اعلام کن تا برنامهٔ ترمیمی دقیق شود."
                            : "با خودت فکر کن: واقعاً چرا این سؤال غلط شد؟"}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {SIX_CAUSES.map((c) => {
                          const active = reflectCause[e.id] === c;
                          return (
                            <button
                              key={c}
                              type="button"
                              onClick={() => setReflectCause((prev) => ({ ...prev, [e.id]: c }))}
                              className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition ${
                                active
                                  ? "bg-primary-600 text-white shadow-soft"
                                  : "bg-slate-100 text-ink-muted hover:bg-primary-50 hover:text-primary-700"
                              }`}
                              aria-pressed={active}
                            >
                              {CAUSE_SHORT[c] ?? CAUSE_FA[c] ?? c}
                            </button>
                          );
                        })}
                      </div>
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-[11px] text-ink-muted">
                          {reflectCause[e.id]
                            ? `علت انتخابی: ${CAUSE_FA[reflectCause[e.id]] ?? reflectCause[e.id]}`
                            : e.declared_cause
                              ? `علت اعلامی: ${CAUSE_FA[e.declared_cause] ?? e.declared_cause}`
                              : "یکی از شش علت را انتخاب کن."}
                        </p>
                        <Button
                          size="sm"
                          variant="soft"
                          disabled={!reflectCause[e.id]}
                          loading={reflectingId === e.id}
                          onClick={() => reflect(e)}
                        >
                          ثبت علت خطا
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
