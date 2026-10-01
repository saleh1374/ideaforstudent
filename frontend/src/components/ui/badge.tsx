import type { ReactNode } from "react";

export type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600 ring-slate-200/70",
  primary: "bg-primary-50 text-primary-700 ring-primary-200/70",
  accent: "bg-accent-50 text-accent-700 ring-accent-200/70",
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200/70",
  warning: "bg-amber-50 text-amber-700 ring-amber-200/70",
  danger: "bg-rose-50 text-rose-700 ring-rose-200/70",
  info: "bg-sky-50 text-sky-700 ring-sky-200/70",
};

const DOT: Record<Tone, string> = {
  neutral: "bg-slate-400",
  primary: "bg-primary-500",
  accent: "bg-accent-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-rose-500",
  info: "bg-sky-500",
};

export function Badge({
  children,
  tone = "neutral",
  dot = false,
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${TONES[tone]} ${className}`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${DOT[tone]}`} />}
      {children}
    </span>
  );
}

const PILL: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  primary: "bg-primary-50 text-primary-700",
  accent: "bg-accent-50 text-accent-700",
  success: "bg-emerald-50 text-emerald-700",
  warning: "bg-amber-50 text-amber-700",
  danger: "bg-rose-50 text-rose-700",
  info: "bg-sky-50 text-sky-700",
};

export function Pill({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold ${PILL[tone]} ${className}`}>
      {children}
    </span>
  );
}

/** Maps the app's domain status keys onto design-system tones. */
export function statusTone(status: string): Tone {
  switch (status) {
    case "mastered":
    case "resolved":
    case "done":
    case "approved":
    case "accepted":
      return "success";
    case "consolidating":
    case "in_remediation":
    case "pending":
    case "auto_approved":
      return "info";
    case "weak":
    case "relapsed":
    case "critical":
    case "rejected":
      return "danger";
    case "open":
      return "warning";
    default:
      return "neutral";
  }
}
