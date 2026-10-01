import type { ReactNode } from "react";
import { IconArrowDown, IconArrowUp } from "./icons";
import { Sparkline } from "./charts";

type Tone = "primary" | "success" | "danger" | "warning" | "accent" | "sky";

const TONE = {
  primary: { icon: "bg-primary-50 text-primary-600", bar: "bg-primary-500", deltaUp: "text-success-600", deltaDown: "text-danger-600" },
  success: { icon: "bg-emerald-50 text-emerald-600", bar: "bg-emerald-500", deltaUp: "text-success-600", deltaDown: "text-danger-600" },
  danger: { icon: "bg-rose-50 text-rose-600", bar: "bg-rose-500", deltaUp: "text-success-600", deltaDown: "text-danger-600" },
  warning: { icon: "bg-amber-50 text-amber-600", bar: "bg-amber-500", deltaUp: "text-success-600", deltaDown: "text-danger-600" },
  accent: { icon: "bg-accent-50 text-accent-600", bar: "bg-accent-500", deltaUp: "text-success-600", deltaDown: "text-danger-600" },
  sky: { icon: "bg-sky-50 text-sky-600", bar: "bg-sky-500", deltaUp: "text-success-600", deltaDown: "text-danger-600" },
} as const;

export function StatCard({
  label,
  value,
  hint,
  delta,
  icon,
  tone = "primary",
  spark,
  gradient = false,
  className = "",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  delta?: { value: string; direction: "up" | "down"; label?: string };
  icon?: ReactNode;
  tone?: Tone;
  spark?: number[];
  gradient?: boolean;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <div
      className={[
        "group relative overflow-hidden rounded-2xl border p-5 transition",
        gradient
          ? "border-0 bg-brand-gradient text-white shadow-lift"
          : "border-line bg-surface shadow-soft hover:-translate-y-0.5 hover:shadow-card",
        className,
      ].join(" ")}
    >
      {/* accent bar */}
      <span className={`absolute inset-x-0 top-0 h-1 ${gradient ? "bg-white/40" : t.bar}`} aria-hidden="true" />

      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`text-xs font-semibold ${gradient ? "text-white/80" : "text-ink-muted"}`}>{label}</p>
          <p className={`num mt-2 text-2xl font-extrabold leading-9 ${gradient ? "text-white" : "text-ink"}`}>{value}</p>
        </div>
        {icon && (
          <span
            className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl transition group-hover:scale-105 ${
              gradient ? "bg-white/20 text-white" : t.icon
            }`}
          >
            {icon}
          </span>
        )}
      </div>

      {(hint || delta || spark) && (
        <div className="mt-3 flex items-end justify-between gap-2">
          <div className="min-w-0 space-y-1">
            {delta && (
              <span
                className={`num inline-flex items-center gap-1 text-[11px] font-bold ${
                  gradient ? "text-white/90" : delta.direction === "up" ? t.deltaUp : t.deltaDown
                }`}
              >
                {delta.direction === "up" ? <IconArrowUp size={13} /> : <IconArrowDown size={13} />}
                {delta.value}
                {delta.label && <span className={`font-medium ${gradient ? "text-white/70" : "text-ink-faint"}`}>{delta.label}</span>}
              </span>
            )}
            {hint && <p className={`truncate text-[11px] ${gradient ? "text-white/75" : "text-ink-faint"}`}>{hint}</p>}
          </div>
          {spark && spark.length > 1 && <Sparkline points={spark} stroke={gradient ? "#ffffff" : "#6366f1"} width={92} height={34} />}
        </div>
      )}
    </div>
  );
}
