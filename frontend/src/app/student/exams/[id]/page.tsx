"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, getToken, ExamItemOut } from "@/lib/api";
import { fa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress";
import { RadialProgress } from "@/components/ui/charts";
import { SkeletonCard } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconAlert, IconCheckCircle, IconExam, IconSend, IconTarget } from "@/components/ui/icons";

type Phase = "idle" | "starting" | "running" | "submitting" | "done";

/** وضعیت نشانگر «ذخیرهٔ خودکار» در نوار پیشرفت چسبان. */
type SaveState = "idle" | "saving" | "saved" | "error";

/** پاسخ یک سؤال در حین آزمون — «marked» برای علامت «برای بازبینی» (§5.6). */
type AnswerDraft = {
  selected: string;
  confidence: number;
  flagged_guess: boolean;
  time_spent_ms: number;
  marked?: boolean;
};

/** خروجی هر سؤال در POST /exams/{id}/start — بستهٔ ذخیرهٔ خودکارِ قبلی (draft). */
type ExamItemDraft = ExamItemOut & {
  draft: {
    selected: string | null;
    confidence: number | null;
    time_spent_ms: number;
    flagged_guess: boolean;
    marked: boolean;
  } | null;
};

type StartOut = {
  attempt_id: number;
  resumed: boolean;
  saved_count: number;
  items: ExamItemDraft[];
};

export default function ExamPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const examId = Number(params.id);

  const [phase, setPhase] = useState<Phase>("idle");
  const [items, setItems] = useState<ExamItemDraft[]>([]);
  const [answers, setAnswers] = useState<Record<number, AnswerDraft>>({});
  const [startedAt, setStartedAt] = useState<number>(0);
  const [result, setResult] = useState<{ raw_score: number; percent: number } | null>(null);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // مراجعِ تازه برای رویدادهای قبل از ترک صفحه (visibilitychange / beforeunload)
  const answersRef = useRef(answers);
  const itemsRef = useRef(items);
  const phaseRef = useRef<Phase>(phase);

  useEffect(() => {
    answersRef.current = answers;
  }, [answers]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);
  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
    }
  }, []);

  async function start() {
    setError("");
    setPhase("starting");
    try {
      const d = await api<StartOut>(`/student/exams/${examId}/start`, { method: "POST" });
      setItems(d.items);

      // بازیابی ذخیرهٔ خودکارِ تلاش نیمه‌تمام (§5.6) — پاسخ‌های ذخیره‌شده برمی‌گردند
      const restored: Record<number, AnswerDraft> = {};
      for (const it of d.items) {
        if (!it.draft) continue;
        restored[it.exam_item_id] = {
          selected: it.draft.selected ?? "",
          confidence: it.draft.confidence ?? 3,
          flagged_guess: it.draft.flagged_guess,
          time_spent_ms: it.draft.time_spent_ms ?? 0,
          marked: it.draft.marked,
        };
      }
      setAnswers(restored);
      setSaveState(Object.keys(restored).length > 0 ? "saved" : "idle");
      if (d.resumed && d.saved_count > 0) {
        toast(`ادامهٔ تلاش قبلی — ${fa(d.saved_count)} پاسخ ذخیره‌شده بازیابی شد`, "info");
      }
      setStartedAt(Date.now());
      setPhase("running");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
      setPhase("idle");
    }
  }

  /** POST /student/exams/{id}/save — بدنه: { answers: [DraftIn] } (بدون آن ذخیره انجام نمی‌شود). */
  async function saveDraft(keepalive = false) {
    if (phaseRef.current !== "running") return;
    const current = answersRef.current;
    const touched = itemsRef.current.filter((it) => current[it.exam_item_id]);
    if (touched.length === 0) return;
    setSaveState("saving");
    try {
      await api(`/student/exams/${examId}/save`, {
        method: "POST",
        // هنگام ترک صفحه فقط fetch با keepalive می‌ماند؛ sendBeacon چون هدر
        // Authorization نمی‌فرستد و سرور با 401 رد می‌کند، استفاده نمی‌شود.
        keepalive,
        json: {
          answers: touched.map((it) => {
            const a = current[it.exam_item_id];
            return {
              exam_item_id: it.exam_item_id,
              selected: a.selected || null,
              confidence: a.confidence,
              time_spent_ms: a.time_spent_ms,
              flagged_guess: a.flagged_guess,
              marked: a.marked ?? false,
            };
          }),
        },
      });
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  /* ذخیرهٔ خودکار با تأخیر ~۴ ثانیه پس از هر تغییر */
  useEffect(() => {
    if (phase !== "running" || Object.keys(answers).length === 0) return;
    const timer = window.setTimeout(() => void saveDraft(), 4000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answers, phase]);

  /* بهترین تلاش برای ذخیرهٔ پاسخ‌ها هنگام مخفی شدن/بستن برگه */
  useEffect(() => {
    const flush = () => {
      if (phaseRef.current !== "running") return;
      void saveDraft(true);
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("beforeunload", flush);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("beforeunload", flush);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setAnswer(eid: number, patch: Partial<Pick<AnswerDraft, "selected" | "confidence" | "flagged_guess" | "marked">>) {
    setAnswers((prev) => {
      const current = prev[eid] ?? { selected: "", confidence: 3, flagged_guess: false, time_spent_ms: 0, marked: false };
      return { ...prev, [eid]: { ...current, ...patch } };
    });
  }

  async function submit() {
    setError("");
    setPhase("submitting");
    try {
      const perItemMs = Math.floor((Date.now() - startedAt) / Math.max(items.length, 1));
      const payload = items.map((it) => {
        const a: Partial<AnswerDraft> = answers[it.exam_item_id] ?? {};
        const { marked: _marked, ...rest } = a;
        return {
          exam_item_id: it.exam_item_id,
          ...rest,
          time_spent_ms: perItemMs,
        };
      });
      const res = await api<{ raw_score: number; percent: number }>(`/student/exams/${examId}/submit`, {
        method: "POST",
        json: { answers: payload },
      });
      setResult(res);
      setPhase("done");
      toast("پاسخ‌ها ثبت شد", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا");
      setPhase("running");
      toast(e instanceof Error ? e.message : "خطا در ثبت آزمون", "error");
    }
  }

  /* ——— result ——— */
  if (phase === "done") {
    const pct = result?.percent ?? 0;
    const good = pct >= 60;
    return (
      <AppShell>
        <div className="mx-auto max-w-2xl space-y-6">
          <PageHeader
            title="کارنامه آزمون"
            crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "آزمون‌ها", href: "/student/exams" }, { label: "کارنامه" }]}
          />
          <Card className="animate-fade-in-up space-y-6 p-8 text-center">
            <span className={`mx-auto grid h-14 w-14 place-items-center rounded-2xl ${good ? "bg-success-50 text-success-600" : "bg-warning-50 text-warning-600"}`}>
              <IconCheckCircle size={26} />
            </span>
            <div className="grid place-items-center">
              <RadialProgress
                value={pct}
                size={168}
                thickness={14}
                color={good ? "#12b76a" : "#f79009"}
                format={(v) => `${fa(v, 1)}٪`}
                label="درصد نهایی"
              />
            </div>
            <div className="flex items-center justify-center gap-3 text-sm">
              <Badge tone="primary">نمره: {fa(result?.raw_score ?? 0, 2)}</Badge>
              <Badge tone={good ? "success" : "warning"}>{good ? "عملکرد خوب" : "نیازمند مرور"}</Badge>
            </div>
            <p className="text-xs leading-6 text-ink-muted">
              تحلیل خطاها وارد دفترچه خطا شد؛ مباحث ضعیف در برنامه مرور و بازآزمون ترمیمی قرار می‌گیرند.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              <Button onClick={() => router.push("/student/errors")} icon={<IconAlert size={15} />}>
                دفترچه خطا
              </Button>
              <Button variant="ghost" onClick={() => router.push("/student")}>
                خانه
              </Button>
            </div>
          </Card>
        </div>
      </AppShell>
    );
  }

  /* ——— idle / intro ——— */
  if (phase === "idle") {
    return (
      <AppShell>
        <div className="mx-auto max-w-2xl space-y-6">
          <PageHeader
            title="آزمون آماده است"
            crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "آزمون‌ها", href: "/student/exams" }, { label: `آزمون ${fa(examId)}` }]}
          />
          <Card className="overflow-hidden p-0">
            <div className="bg-brand-gradient px-8 py-7 text-center text-white">
              <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-white/20">
                <IconExam size={26} />
              </span>
              <h2 className="mt-3 text-lg font-extrabold">قبل از شروع</h2>
              <p className="mx-auto mt-1 max-w-md text-xs leading-6 text-white/80">
                پاسخ‌ها، میزان اطمینان و زمان پاسخ ذخیره می‌شود تا تحلیل دقیق‌تری داشته باشی.
              </p>
            </div>
            <div className="space-y-4 p-6">
              <ul className="space-y-2 text-xs leading-6 text-ink-muted">
                <li className="flex items-start gap-2">
                  <IconTarget size={15} className="mt-0.5 shrink-0 text-primary-500" />
                  برای هر سؤال میزان اطمینان خود را (۱ تا ۵) مشخص کن.
                </li>
                <li className="flex items-start gap-2">
                  <IconAlert size={15} className="mt-0.5 shrink-0 text-warning-500" />
                  اگر حدس زدی، گزینه «حدس زدم» را بزن تا کیفیت تحلیل بالا برود.
                </li>
                <li className="flex items-start gap-2">
                  <IconCheckCircle size={15} className="mt-0.5 shrink-0 text-success-600" />
                  بعد از ثبت، خطاها خودکار وارد دفترچه خطا می‌شود.
                </li>
                <li className="flex items-start gap-2">
                  <IconCheckCircle size={15} className="mt-0.5 shrink-0 text-primary-500" />
                  پاسخ‌ها به‌صورت خودکار ذخیره می‌شوند؛ اگر نیمه‌کاره رها کنی، از همان‌جا ادامه می‌دهی.
                </li>
              </ul>
              {error && <Alert variant="danger">{error}</Alert>}
              <Button size="lg" className="w-full" onClick={start} icon={<IconSend size={16} />}>
                شروع آزمون
              </Button>
              <ButtonLink href="/student/exams" variant="ghost" className="w-full">
                بازگشت به فهرست آزمون‌ها
              </ButtonLink>
            </div>
          </Card>
        </div>
      </AppShell>
    );
  }

  if (phase === "starting" || items.length === 0) {
    return (
      <AppShell>
        <div className="mx-auto max-w-2xl space-y-5">
          <PageHeader title="در حال آماده‌سازی آزمون…" crumbs={[{ label: "دانشیار" }, { label: "آزمون‌ها", href: "/student/exams" }]} />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </AppShell>
    );
  }

  /* ——— running ——— */
  const answeredCount = Object.values(answers).filter((a) => a.selected).length;

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-5">
        <PageHeader
          title="در حال آزمون"
          description="پیشرفت خود را زیر نظر داشته باش؛ هر سؤال را با اطمینان ثبت کن."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "آزمون‌ها", href: "/student/exams" }, { label: "در حال آزمون" }]}
          badge={<Badge tone="primary" dot>{fa(answeredCount)} از {fa(items.length)} پاسخ</Badge>}
        />

        <div className="sticky top-16 z-20 rounded-2xl border border-line bg-surface/95 p-4 shadow-soft backdrop-blur">
          <ProgressBar
            value={answeredCount}
            max={items.length}
            tone={answeredCount === items.length ? "success" : "primary"}
            label="پیشرفت آزمون"
            showValue
          />
          <p
            className={`mt-2 flex items-center gap-1.5 text-[11px] font-semibold ${
              saveState === "error" ? "text-danger-600" : saveState === "saved" ? "text-success-600" : "text-ink-muted"
            }`}
            role="status"
          >
            {saveState === "saving" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary-500" />}
            {saveState === "saving" && "در حال ذخیره…"}
            {saveState === "saved" && "ذخیره خودکار ✓"}
            {saveState === "error" && "ذخیره خودکار ناموفق؛ اتصال اینترنت را بررسی کن"}
            {saveState === "idle" && "ذخیره خودکار پاسخ‌ها فعال است"}
          </p>
        </div>

        <div className="space-y-4">
          {items.map((it) => {
            const a = answers[it.exam_item_id];
            return (
              <Card key={it.exam_item_id} className="space-y-4">
                <div className="flex items-start gap-3">
                  <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-gradient-soft text-xs font-bold text-primary-700">
                    {fa(it.order)}
                  </span>
                  <p className="text-sm font-semibold leading-8 text-ink">{it.body}</p>
                </div>

                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {Object.entries(it.options).map(([k, v]) => {
                    const selected = a?.selected === k;
                    return (
                      <button
                        key={k}
                        onClick={() => setAnswer(it.exam_item_id, { selected: k })}
                        className={`flex items-start gap-2 rounded-xl border px-3.5 py-3 text-right text-sm transition ${
                          selected
                            ? "border-primary-400 bg-primary-50 text-primary-800 shadow-soft"
                            : "border-line bg-surface text-ink-muted hover:border-primary-200 hover:bg-primary-50/40"
                        }`}
                      >
                        <span
                          className={`num grid h-6 w-6 shrink-0 place-items-center rounded-lg text-xs font-bold ${
                            selected ? "bg-primary-600 text-white" : "bg-slate-100 text-ink-muted"
                          }`}
                        >
                          {k}
                        </span>
                        <span className="leading-6">{v}</span>
                      </button>
                    );
                  })}
                </div>

                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl bg-surface-sunken px-3.5 py-2.5 text-xs text-ink-muted">
                  <span className="font-semibold">میزان اطمینان:</span>
                  <div className="flex items-center gap-1.5">
                    {[1, 2, 3, 4, 5].map((c) => (
                      <button
                        key={c}
                        onClick={() => setAnswer(it.exam_item_id, { confidence: c })}
                        className={`num h-7 w-7 rounded-lg border text-xs font-bold transition ${
                          a?.confidence === c
                            ? "border-primary-500 bg-primary-600 text-white"
                            : "border-line bg-surface text-ink-muted hover:border-primary-300"
                        }`}
                        aria-label={`اطمینان ${fa(c)}`}
                      >
                        {fa(c)}
                      </button>
                    ))}
                  </div>
                  <label className="mr-auto flex cursor-pointer items-center gap-2 font-medium">
                    <input
                      type="checkbox"
                      checked={a?.flagged_guess ?? false}
                      onChange={(e) => setAnswer(it.exam_item_id, { flagged_guess: e.target.checked })}
                      className="h-4 w-4 rounded border-line text-primary-600 focus:ring-primary-500/40"
                    />
                    حدس زدم
                  </label>
                </div>
              </Card>
            );
          })}
        </div>

        {error && <Alert variant="danger">{error}</Alert>}

        <div className="sticky bottom-4 rounded-2xl border border-line bg-surface/95 p-4 shadow-card backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="num text-xs text-ink-muted">
              {answeredCount === items.length ? "همه سؤالات پاسخ داده شده ✓" : `${fa(items.length - answeredCount)} سؤال بدون پاسخ`}
            </p>
            <Button onClick={submit} loading={phase === "submitting"} disabled={answeredCount === 0} icon={<IconCheckCircle size={15} />}>
              ثبت نهایی
            </Button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
