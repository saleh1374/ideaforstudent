"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, getToken } from "@/lib/api";
import { SUBJECT_FA, fa, subjectFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { Field, Input, Select, Textarea } from "@/components/ui/forms";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/ui/table";
import { ProgressBar } from "@/components/ui/progress";
import { SkeletonCard, SkeletonStats } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import {
  IconBriefcase,
  IconChart,
  IconInbox,
  IconLayers,
  IconPlus,
  IconRefresh,
  IconShield,
} from "@/components/ui/icons";

/**
 * امور مالی (سند پنل والدین §18 + تصمیم باز §10.۲ سند دانش‌آموز):
 * بسته‌های جلسات، پرداخت‌ها/فاکتورها و درخواست بازپرداخت — پرداخت فعلاً
 * خارج از سیستم (گزینه الف) ثبت می‌شود؛ این صفحه فقط واسط نمایش است.
 * والد: سه زبانه کامل + ثبت پرداخت/بازپرداخت. معلم: بسته‌ها + دریافتی‌ها.
 */

type Child = { id: number; full_name: string };

type Pack = {
  id?: number;
  tutor_name?: string | null;
  student_name?: string | null;
  subject?: string | null;
  purchased?: number;
  used?: number;
  remaining?: number;
  price_per_session?: number | null;
  status?: string;
  status_fa?: string | null;
  created_at?: string | null;
};

type Payment = {
  id?: number;
  invoice_no?: string | null;
  amount?: number;
  method_fa?: string | null;
  status?: string;
  status_fa?: string | null;
  tutor_name?: string | null;
  student_name?: string | null;
  description?: string | null;
  created_at?: string | null;
  session_pack_id?: number | null;
};

type Refund = {
  id?: number;
  payment_id?: number;
  invoice_no?: string | null;
  amount?: number | null;
  reason?: string | null;
  status?: string;
  status_fa?: string | null;
  created_at?: string | null;
  decision_note?: string | null;
};

type Earnings = {
  by_status: { status?: string; status_fa?: string | null; count?: number; total?: number }[];
  total_earned?: number;
  pending_amount?: number;
  refunded_amount?: number;
  payments_count?: number;
  note_fa?: string | null;
};

type Overview = {
  children: Child[];
  packs: Pack[];
  payments: Payment[];
  refunds: Refund[];
  stats: Record<string, number>;
  payment_mode?: string | null;
  mode_note_fa?: string | null;
  note_fa?: string | null;
};

type TabKey = "packs" | "payments" | "refunds" | "earnings";

/* ---------------- نگاشت‌های برچسب/رنگ (نمای فارسی) ---------------- */

const PAY_FA: Record<string, string | undefined> = {
  paid: "پرداخت‌شده",
  pending: "در انتظار",
  failed: "ناموفق",
  refunded: "بازپرداخت‌شده",
};
const PAY_TONE: Record<string, Tone | undefined> = {
  paid: "success",
  pending: "warning",
  failed: "danger",
  refunded: "neutral",
};
const PACK_FA: Record<string, string | undefined> = {
  active: "فعال",
  exhausted: "تمام‌شده",
  cancelled: "لغوشده",
};
const PACK_TONE: Record<string, Tone | undefined> = {
  active: "success",
  exhausted: "neutral",
  cancelled: "danger",
};
const REFUND_FA: Record<string, string | undefined> = {
  requested: "درخواست‌شده",
  approved: "تأییدشده",
  rejected: "ردشده",
};
const REFUND_TONE: Record<string, Tone | undefined> = {
  requested: "warning",
  approved: "success",
  rejected: "danger",
};

const MODE_NOTE_FALLBACK =
  "پرداخت فعلاً خارج از سیستم ثبت می‌شود (گزینه الف بخش ۱۰.۲)؛ امکان پرداخت داخلی با امانی در نسخه‌های آینده.";

/* ---------------- کمک‌کننده‌های تدافعی (شکل پاسخ را تضمین می‌کنند) ---------------- */

const rec = (v: unknown): Record<string, unknown> =>
  v !== null && typeof v === "object" ? (v as Record<string, unknown>) : {};
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);

function normOverview(x: unknown): Overview {
  const o = rec(x);
  const stats: Record<string, number> = {};
  for (const [k, v] of Object.entries(rec(o.stats))) stats[k] = num(v);
  return {
    children: arr<unknown>(o.children)
      .map((c) => ({ id: num(rec(c).id), full_name: str(rec(c).full_name) || "—" }))
      .filter((c) => c.id > 0),
    packs: arr<Pack>(o.packs),
    payments: arr<Payment>(o.payments),
    refunds: arr<Refund>(o.refunds),
    stats,
    payment_mode: str(o.payment_mode) || null,
    mode_note_fa: str(o.mode_note_fa) || null,
    note_fa: str(o.note_fa) || null,
  };
}

function normPacks(x: unknown): Pack[] {
  const o = rec(x);
  return Array.isArray(o.packs) ? arr<Pack>(o.packs) : arr<Pack>(x);
}

function normEarnings(x: unknown): Earnings {
  const o = rec(x);
  return {
    by_status: arr<unknown>(o.by_status).map((b) => ({
      status: str(rec(b).status),
      status_fa: str(rec(b).status_fa) || null,
      count: num(rec(b).count),
      total: num(rec(b).total),
    })),
    total_earned: num(o.total_earned),
    pending_amount: num(o.pending_amount),
    refunded_amount: num(o.refunded_amount),
    payments_count: num(o.payments_count),
    note_fa: str(o.note_fa) || null,
  };
}

function faDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fa-IR", { dateStyle: "short" });
}

const money = (v?: number | null): string => (typeof v === "number" ? `${fa(v)} تومان` : "—");

/* ---------------- صفحه ---------------- */

export default function BillingPage() {
  const [tab, setTab] = useState<TabKey>("packs");
  const [role, setRole] = useState(""); // "" = هنوز بررسی نشده
  const [denied, setDenied] = useState(false);
  const [ov, setOv] = useState<Overview | null>(null);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  /* ---------------- بارگذاری ---------------- */

  const loadFor = useCallback(async (r: string) => {
    setRefreshing(true);
    setError("");
    try {
      if (r === "parent") {
        setOv(normOverview(await api<unknown>("/billing/parent/overview")));
        setPacks([]);
        setEarnings(null);
      } else if (r === "teacher") {
        setPacks(normPacks(await api<unknown>("/billing/packs")));
        setEarnings(normEarnings(await api<unknown>("/billing/tutor/earnings")));
        setOv(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در دریافت اطلاعات مالی");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    (async () => {
      try {
        const me = await api<{ role?: string }>("/auth/me");
        const r = typeof me?.role === "string" ? me.role : "";
        setRole(r);
        if (r !== "parent" && r !== "teacher") {
          setDenied(true);
          setLoading(false);
          return;
        }
        await loadFor(r);
      } catch (e) {
        setError(e instanceof Error ? e.message : "خطا");
        setLoading(false);
      }
    })();
  }, [loadFor]);

  const isParent = role === "parent";
  const isTeacher = role === "teacher";
  const children: Child[] = ov?.children ?? [];
  const packRows: Pack[] = isParent ? (ov?.packs ?? []) : packs;
  const paymentRows: Payment[] = ov?.payments ?? [];
  const refundRows: Refund[] = ov?.refunds ?? [];
  const hasOpenRefund = (paymentId?: number) =>
    !!paymentId && refundRows.some((r) => r.payment_id === paymentId && r.status === "requested");

  /* ---------------- ثبت پرداخت (والد) ---------------- */

  const [payOpen, setPayOpen] = useState(false);
  const [payChild, setPayChild] = useState("");
  const [payTutor, setPayTutor] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [paySessions, setPaySessions] = useState("");
  const [paySubject, setPaySubject] = useState("math");
  const [payDesc, setPayDesc] = useState("");
  const [payBusy, setPayBusy] = useState(false);
  const [payError, setPayError] = useState("");
  const [tutors, setTutors] = useState<{ user_id: number; name: string }[]>([]);
  const [tutorsLoaded, setTutorsLoaded] = useState(false);

  const loadTutors = useCallback(async () => {
    if (tutorsLoaded) return;
    try {
      const res = await api<unknown>("/tutor/market");
      const list = arr<unknown>(rec(res).tutors)
        .map((t) => ({ user_id: num(rec(t).user_id), name: str(rec(t).name) || `#${num(rec(t).user_id)}` }))
        .filter((t) => t.user_id > 0);
      setTutors(list);
      setTutorsLoaded(true);
    } catch {
      /* در مودال خطای جدا نمایش داده می‌شود */
    }
  }, [tutorsLoaded]);

  function openPay() {
    setPayChild(children[0]?.id ? String(children[0].id) : "");
    setPayTutor("");
    setPayAmount("");
    setPaySessions("");
    setPaySubject("math");
    setPayDesc("");
    setPayError("");
    void loadTutors();
    setPayOpen(true);
  }

  async function submitPay() {
    const studentId = Number(payChild);
    const tutorId = Number(payTutor);
    const amount = Number(payAmount.replace(/[^\d]/g, ""));
    if (!studentId) {
      setPayError("فرزند را انتخاب کنید.");
      return;
    }
    if (!tutorId) {
      setPayError("معلم خصوصی را انتخاب کنید.");
      return;
    }
    if (!amount || amount <= 0) {
      setPayError("مبلغ را به تومان وارد کنید.");
      return;
    }
    const sessionsRaw = paySessions.replace(/[^\d]/g, "");
    const sessions = sessionsRaw ? Number(sessionsRaw) : null;
    if (sessions !== null && sessions < 1) {
      setPayError("تعداد جلسات باید حداقل ۱ باشد.");
      return;
    }
    setPayBusy(true);
    setPayError("");
    try {
      const res = await api<{ ok?: boolean; invoice_no?: string }>("/billing/payments", {
        method: "POST",
        json: {
          student_user_id: studentId,
          tutor_user_id: tutorId,
          amount,
          subject: paySubject || undefined,
          description: payDesc.trim() || undefined,
          ...(sessions !== null ? { session_count: sessions } : {}),
        },
      });
      if (res?.ok === false) {
        setPayError("ثبت پرداخت انجام نشد؛ دوباره تلاش کنید.");
        return;
      }
      toast(`پرداخت ثبت شد — فاکتور ${res?.invoice_no ?? ""}`, "success");
      setPayOpen(false);
      await loadFor(role);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) toast(e.detail ?? "خارج از حوزه دسترسی شماست", "error");
      else setPayError(e instanceof Error ? e.message : "خطا در ثبت پرداخت");
    } finally {
      setPayBusy(false);
    }
  }

  /* ---------------- درخواست بازپرداخت (والد) ---------------- */

  const [refTarget, setRefTarget] = useState<Payment | null>(null);
  const [refReason, setRefReason] = useState("");
  const [refBusy, setRefBusy] = useState(false);
  const [refError, setRefError] = useState("");

  function openRefund(p: Payment) {
    setRefTarget(p);
    setRefReason("");
    setRefError("");
  }

  async function submitRefund() {
    if (!refTarget?.id) return;
    if (!refReason.trim()) {
      setRefError("دلیل بازپرداخت را بنویسید (جلسه لغوشده یا برگزارنشده).");
      return;
    }
    setRefBusy(true);
    setRefError("");
    try {
      await api(`/billing/payments/${refTarget.id}/refund`, {
        method: "POST",
        json: { reason: refReason.trim() },
      });
      toast("درخواست بازپرداخت ثبت شد و در انتظار بررسی است", "success");
      setRefTarget(null);
      await loadFor(role);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          toast(e.detail ?? "درخواست بازپرداخت تکراری است", "error");
          setRefTarget(null);
          await loadFor(role);
        } else if (e.status === 403) {
          toast(e.detail ?? "به این پرداخت دسترسی ندارید", "error");
          setRefTarget(null);
        } else setRefError(e.detail ?? e.message);
      } else {
        setRefError(e instanceof Error ? e.message : "خطا در ثبت درخواست");
      }
    } finally {
      setRefBusy(false);
    }
  }

  /* ---------------- ستون‌های جدول ---------------- */

  const packCols: Column<Pack>[] = [
    {
      key: "tutor",
      header: "معلم خصوصی",
      render: (p) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{p?.tutor_name ?? "—"}</p>
          <p className="text-[11px] text-ink-faint">{p?.student_name ?? "—"}</p>
        </div>
      ),
    },
    {
      key: "subject",
      header: "درس",
      align: "center",
      render: (p) => <Badge tone="primary">{subjectFa(p?.subject)}</Badge>,
    },
    {
      key: "sessions",
      header: "جلسات (مصرف‌شده / خریداری‌شده)",
      render: (p) => {
        const purchased = Math.max(num(p?.purchased), 0);
        const used = Math.min(Math.max(num(p?.used), 0), purchased);
        const remaining = Math.max(num(p?.remaining), purchased - used);
        return (
          <div className="min-w-[170px] space-y-1.5">
            <span className="num text-xs font-semibold text-ink">
              {fa(used)} / {fa(purchased)} — {fa(remaining)} جلسه باقی‌مانده
            </span>
            <ProgressBar
              value={used}
              max={Math.max(purchased, 1)}
              size="sm"
              tone={remaining > 0 ? "primary" : "success"}
            />
          </div>
        );
      },
    },
    {
      key: "price",
      header: "مبلغ هر جلسه",
      align: "center",
      render: (p) => <span className="num text-xs">{p?.price_per_session ? `${fa(p.price_per_session)} تومان` : "—"}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (p) => (
        <Badge tone={PACK_TONE[p?.status ?? ""] ?? "neutral"} dot>
          {p?.status_fa ?? PACK_FA[p?.status ?? ""] ?? "—"}
        </Badge>
      ),
    },
  ];

  const paymentCols: Column<Payment>[] = [
    {
      key: "date",
      header: "تاریخ",
      align: "center",
      render: (p) => <span className="num text-xs">{faDate(p?.created_at)}</span>,
    },
    {
      key: "tutor",
      header: "معلم / دانش‌آموز",
      render: (p) => (
        <div className="space-y-0.5">
          <p className="font-semibold text-ink">{p?.tutor_name ?? "—"}</p>
          <p className="text-[11px] text-ink-faint">{p?.student_name ?? "—"}</p>
        </div>
      ),
    },
    {
      key: "amount",
      header: "مبلغ",
      align: "end",
      render: (p) => <span className="num text-xs font-bold text-ink">{money(p?.amount)}</span>,
    },
    {
      key: "invoice",
      header: "شماره فاکتور",
      align: "center",
      render: (p) => <span className="num text-xs">{p?.invoice_no ?? "—"}</span>,
    },
    {
      key: "method",
      header: "روش",
      align: "center",
      render: (p) => <Badge tone="neutral">{p?.method_fa ?? "خارج از سیستم"}</Badge>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (p) => (
        <Badge tone={PAY_TONE[p?.status ?? ""] ?? "neutral"} dot>
          {p?.status_fa ?? PAY_FA[p?.status ?? ""] ?? "—"}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (p) =>
        isParent && p?.status === "paid" ? (
          hasOpenRefund(p.id) ? (
            <span className="text-[11px] text-ink-faint">بازپرداخت در انتظار</span>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => openRefund(p)}>
              درخواست بازپرداخت
            </Button>
          )
        ) : null,
    },
  ];

  const refundCols: Column<Refund>[] = [
    {
      key: "invoice",
      header: "فاکتور",
      align: "center",
      render: (r) => <span className="num text-xs">{r?.invoice_no ?? "—"}</span>,
    },
    {
      key: "amount",
      header: "مبلغ",
      align: "end",
      render: (r) => <span className="num text-xs font-bold text-ink">{money(r?.amount)}</span>,
    },
    {
      key: "reason",
      header: "دلیل",
      render: (r) => <span className="text-xs">{r?.reason ?? "—"}</span>,
    },
    {
      key: "date",
      header: "تاریخ درخواست",
      align: "center",
      render: (r) => <span className="num text-xs">{faDate(r?.created_at)}</span>,
    },
    {
      key: "status",
      header: "وضعیت",
      align: "center",
      render: (r) => (
        <Badge tone={REFUND_TONE[r?.status ?? ""] ?? "neutral"} dot>
          {r?.status_fa ?? REFUND_FA[r?.status ?? ""] ?? "—"}
        </Badge>
      ),
    },
  ];

  /* ---------------- سرصفحه ---------------- */

  const header = (
    <PageHeader
      title="امور مالی"
      description="بسته‌های جلسات، پرداخت‌ها و فاکتورها و درخواست بازپرداخت — کاملاً جدا از داده آموزشی (سند پنل والدین §18)."
      crumbs={[{ label: "دانشیار" }, { label: "عمومی" }, { label: "امور مالی" }]}
      badge={role ? <Badge tone="accent" dot>{isParent ? "والد" : isTeacher ? "معلم" : role}</Badge> : undefined}
      actions={
        (isParent || isTeacher) && (
          <Button
            variant="soft"
            size="sm"
            loading={refreshing}
            icon={<IconRefresh size={15} />}
            onClick={() => loadFor(role)}
          >
            به‌روزرسانی
          </Button>
        )
      }
    />
  );

  if (denied) {
    return (
      <AppShell>
        <div className="space-y-6">
          {header}
          <Alert variant="warning" title="دسترسی محدود">
            این صفحه ویژه والد و معلم خصوصی است. با حساب والد یا معلم وارد شوید؛ سرور نیز دامنه دسترسی را جداگانه
            کنترل می‌کند.
          </Alert>
          <EmptyState
            icon={<IconShield size={26} />}
            title="نقش شما به این صفحه دسترسی ندارد"
            description={`نقش فعلی: ${role || "—"}`}
          />
        </div>
      </AppShell>
    );
  }

  const stats = ov?.stats ?? {};
  const packRemaining = packRows.reduce((s, p) => s + Math.max(num(p?.remaining), 0), 0);

  const tabItems: { key: TabKey; label: string; count?: number }[] = [
    { key: "packs", label: "بسته‌های جلسه", count: packRows.length },
    ...(isParent
      ? ([
          { key: "payments", label: "پرداخت‌ها و فاکتورها", count: paymentRows.length },
          { key: "refunds", label: "بازپرداخت", count: refundRows.length },
        ] as { key: TabKey; label: string; count?: number }[])
      : []),
    ...(isTeacher
      ? ([{ key: "earnings", label: "دریافتی‌های من", count: earnings?.payments_count ?? 0 }] as {
          key: TabKey;
          label: string;
          count?: number;
        }[])
      : []),
  ];

  const activeTab = tabItems.some((t) => t.key === tab) ? tab : ("packs" as TabKey);

  return (
    <AppShell>
      <div className="space-y-6">
        {header}

        <Alert variant="info" title="روش پرداخت">
          {ov?.mode_note_fa ?? MODE_NOTE_FALLBACK}
        </Alert>

        {error && <Alert variant="danger" title="خطا در دریافت داده">{error}</Alert>}

        {loading && !ov && packs.length === 0 && !error && (
          <div className="space-y-5">
            <SkeletonStats count={4} />
            <SkeletonCard />
          </div>
        )}

        {!loading && !error && (isParent ? ov !== null : true) && (
          <>
            {/* ---------------- شاخص‌ها ---------------- */}
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {isParent ? (
                <>
                  <StatCard
                    label="پرداخت‌شده"
                    value={money(stats.paid_total ?? 0)}
                    tone="success"
                    icon={<IconBriefcase size={20} />}
                    hint="جمع فاکتورهای پرداخت‌شده"
                  />
                  <StatCard
                    label="در انتظار"
                    value={money(stats.pending_total ?? 0)}
                    tone="warning"
                    icon={<IconInbox size={20} />}
                    hint="فاکتورهای ثبت‌شده بدون پرداخت"
                  />
                  <StatCard
                    label="جلسات باقی‌مانده"
                    value={fa(stats.sessions_remaining ?? 0)}
                    tone="primary"
                    icon={<IconLayers size={20} />}
                    hint={`از ${fa(stats.sessions_purchased ?? 0)} جلسه خریداری‌شده`}
                  />
                  <StatCard
                    label="بسته‌های جلسه"
                    value={fa(stats.packs_total ?? 0)}
                    tone="accent"
                    icon={<IconChart size={20} />}
                    hint={`بازپرداخت باز: ${fa(stats.refunds_open ?? 0)}`}
                  />
                </>
              ) : (
                <>
                  <StatCard
                    label="دریافتی پرداخت‌شده"
                    value={money(earnings?.total_earned ?? 0)}
                    tone="success"
                    icon={<IconBriefcase size={20} />}
                    hint="جمع پرداخت‌های ثبت‌شده"
                  />
                  <StatCard
                    label="در انتظار"
                    value={money(earnings?.pending_amount ?? 0)}
                    tone="warning"
                    icon={<IconInbox size={20} />}
                    hint="پرداخت‌های در جریان"
                  />
                  <StatCard
                    label="جلسات باقی‌مانده"
                    value={fa(packRemaining)}
                    tone="primary"
                    icon={<IconLayers size={20} />}
                    hint="در همه بسته‌های فعال"
                  />
                  <StatCard
                    label="تعداد تراکنش‌ها"
                    value={fa(earnings?.payments_count ?? 0)}
                    tone="accent"
                    icon={<IconChart size={20} />}
                    hint="تاریخچه کامل پرداخت‌ها"
                  />
                </>
              )}
            </section>

            <Tabs items={tabItems} value={activeTab} onChange={(k) => setTab(k as TabKey)} />

            {/* ---------------- بسته‌های جلسه ---------------- */}
            {activeTab === "packs" && (
              <Section
                title="بسته‌های جلسه"
                subtitle="شمارش دقیق خریداری‌شده / مصرف‌شده / باقی‌مانده برای هر معلم خصوصی"
                action={
                  isParent && (
                    <Button size="sm" icon={<IconPlus size={14} />} onClick={openPay}>
                      ثبت پرداخت
                    </Button>
                  )
                }
              >
                <DataTable
                  columns={packCols}
                  rows={packRows}
                  keyOf={(p, i) => p?.id ?? i}
                  loading={loading && packRows.length === 0}
                  empty={
                    <EmptyState
                      compact
                      icon={<IconLayers size={24} />}
                      title="بسته‌ای ثبت نشده است"
                      description={
                        isParent
                          ? "با ثبت پرداخت (خارج از سیستم) می‌توانید بسته جلسات بسازید."
                          : "هنوز بسته‌ای به شما اختصاص داده نشده است."
                      }
                    />
                  }
                />
                {packRows.length > 0 && (
                  <p className="text-[11px] leading-6 text-ink-faint">
                    مصرف جلسه توسط معلم ثبت می‌شود و از سقف بسته فراتر نمی‌رود.
                  </p>
                )}
              </Section>
            )}

            {/* ---------------- پرداخت‌ها و فاکتورها ---------------- */}
            {activeTab === "payments" && (
              <Section
                title="پرداخت‌ها و فاکتورها"
                subtitle="تاریخچه کامل تراکنش‌ها — وضعیت: پرداخت‌شده / در انتظار / ناموفق"
                action={
                  <Button size="sm" icon={<IconPlus size={14} />} onClick={openPay}>
                    ثبت پرداخت
                  </Button>
                }
              >
                <DataTable
                  columns={paymentCols}
                  rows={paymentRows}
                  keyOf={(p, i) => p?.id ?? i}
                  loading={loading && paymentRows.length === 0}
                  empty={
                    <EmptyState
                      compact
                      icon={<IconInbox size={24} />}
                      title="پرداختی ثبت نشده است"
                      description="پرداخت‌های انجام‌شده خارج از سیستم را با «ثبت پرداخت» اینجا بیاورید."
                    />
                  }
                />
                {ov?.note_fa && <Alert variant="info">{ov.note_fa}</Alert>}
              </Section>
            )}

            {/* ---------------- بازپرداخت ---------------- */}
            {activeTab === "refunds" && (
              <Section
                title="درخواست‌های بازپرداخت"
                subtitle="برای جلسات لغوشده یا برگزارنشده — از ستون آخر جدول پرداخت‌ها درخواست دهید"
              >
                <DataTable
                  columns={refundCols}
                  rows={refundRows}
                  keyOf={(r, i) => r?.id ?? i}
                  loading={loading && refundRows.length === 0}
                  empty={
                    <EmptyState
                      compact
                      title="درخواست بازپرداختی ثبت نشده است"
                      description="در تب «پرداخت‌ها و فاکتورها»، روبروی فاکتور پرداخت‌شده «درخواست بازپرداخت» را بزنید."
                    />
                  }
                />
              </Section>
            )}

            {/* ---------------- دریافتی‌های معلم ---------------- */}
            {activeTab === "earnings" && (
              <Section title="دریافتی‌های من" subtitle="تجمیع پرداخت‌های ثبت‌شده بر اساس وضعیت">
                <Card>
                  <CardHeader title="خلاصه مالی" icon={<IconChart size={17} />} />
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="rounded-2xl border border-line bg-surface-sunken p-4">
                      <p className="text-xs font-semibold text-ink-muted">پرداخت‌شده</p>
                      <p className="num mt-1 text-lg font-extrabold text-ink">{money(earnings?.total_earned ?? 0)}</p>
                    </div>
                    <div className="rounded-2xl border border-line bg-surface-sunken p-4">
                      <p className="text-xs font-semibold text-ink-muted">در انتظار</p>
                      <p className="num mt-1 text-lg font-extrabold text-ink">{money(earnings?.pending_amount ?? 0)}</p>
                    </div>
                    <div className="rounded-2xl border border-line bg-surface-sunken p-4">
                      <p className="text-xs font-semibold text-ink-muted">بازپرداخت‌شده</p>
                      <p className="num mt-1 text-lg font-extrabold text-ink">{money(earnings?.refunded_amount ?? 0)}</p>
                    </div>
                  </div>
                  {(earnings?.by_status?.length ?? 0) > 0 ? (
                    <div className="mt-4 space-y-2">
                      {earnings?.by_status.map((b, i) => (
                        <div
                          key={`${b.status ?? i}`}
                          className="flex items-center justify-between rounded-xl border border-line bg-surface-sunken px-4 py-2.5"
                        >
                          <Badge tone={PAY_TONE[b.status ?? ""] ?? "neutral"} dot>
                            {b.status_fa ?? PAY_FA[b.status ?? ""] ?? "—"}
                          </Badge>
                          <span className="num text-xs text-ink-muted">
                            {fa(b.count ?? 0)} تراکنش — {money(b.total ?? 0)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-4 text-xs text-ink-faint">هنوز پرداختی ثبت نشده است.</p>
                  )}
                  {earnings?.note_fa && <p className="mt-3 text-[11px] leading-6 text-ink-faint">{earnings.note_fa}</p>}
                </Card>
              </Section>
            )}
          </>
        )}
      </div>

      {/* ---------------- مودال ثبت پرداخت ---------------- */}
      <Modal
        open={payOpen}
        onClose={() => setPayOpen(false)}
        title="ثبت پرداخت (خارج از سیستم)"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPayOpen(false)} disabled={payBusy}>
              انصراف
            </Button>
            <Button loading={payBusy} onClick={submitPay}>
              ثبت و صدور فاکتور
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert variant="info">
            پول بین شما و معلم جا به جا می‌شود (گزینه الف بخش ۱۰.۲)؛ اینجا فقط ثبت و فاکتور صادر می‌شود.
          </Alert>

          {payError && <Alert variant="danger">{payError}</Alert>}

          {children.length === 0 ? (
            <Alert variant="warning">فرزندی به حساب شما متصل نیست؛ نخست اتصال فرزند را انجام دهید.</Alert>
          ) : (
            <Field label="فرزند" required>
              <Select value={payChild} onChange={(e) => setPayChild(e.target.value)}>
                <option value="">انتخاب کنید…</option>
                {children.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.full_name}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          <Field label="معلم خصوصی" required hint={tutorsLoaded ? undefined : "در حال بارگذاری فهرست معلمان…"}>
            <Select value={payTutor} onChange={(e) => setPayTutor(e.target.value)}>
              <option value="">انتخاب کنید…</option>
              {tutors.map((t) => (
                <option key={t.user_id} value={String(t.user_id)}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="مبلغ (تومان)" required>
              <Input
                inputMode="numeric"
                placeholder="مثلاً 400000"
                value={payAmount}
                onChange={(e) => setPayAmount(e.target.value)}
              />
            </Field>
            <Field label="تعداد جلسات (اختیاری)" hint="برای ساخت بسته جلسات">
              <Input
                inputMode="numeric"
                placeholder="مثلاً 4"
                value={paySessions}
                onChange={(e) => setPaySessions(e.target.value)}
              />
            </Field>
          </div>

          <Field label="درس">
            <Select value={paySubject} onChange={(e) => setPaySubject(e.target.value)}>
              {Object.keys(SUBJECT_FA).map((k) => (
                <option key={k} value={k}>
                  {SUBJECT_FA[k]}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="توضیح (اختیاری)">
            <Textarea
              placeholder="مثلاً: ۴ جلسه ریاضی — پرداخت حضوری"
              value={payDesc}
              onChange={(e) => setPayDesc(e.target.value)}
            />
          </Field>
        </div>
      </Modal>

      {/* ---------------- مودال بازپرداخت ---------------- */}
      <Modal
        open={refTarget !== null}
        onClose={() => setRefTarget(null)}
        title="درخواست بازپرداخت"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRefTarget(null)} disabled={refBusy}>
              انصراف
            </Button>
            <Button loading={refBusy} onClick={submitRefund}>
              ثبت درخواست
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="rounded-xl border border-line bg-surface-sunken px-4 py-3 text-xs text-ink-muted">
            فاکتور: <span className="num font-semibold text-ink">{refTarget?.invoice_no ?? "—"}</span> — مبلغ{" "}
            <span className="num font-semibold text-ink">{money(refTarget?.amount)}</span>
          </div>

          {refError && <Alert variant="danger">{refError}</Alert>}

          <Field label="دلیل بازپرداخت" required hint="جلسه لغوشده یا برگزارنشده را شرح دهید.">
            <Textarea
              placeholder="مثلاً: جلسه هفته گذشته لغو شد و برگزار نشد."
              value={refReason}
              onChange={(e) => setRefReason(e.target.value)}
            />
          </Field>
        </div>
      </Modal>
    </AppShell>
  );
}
