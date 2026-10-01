import type { ReactNode } from "react";

type Tone = "primary" | "success" | "warning" | "danger" | "accent" | "sky";

const BAR: Record<Tone, string> = {
  primary: "bg-primary-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-rose-500",
  accent: "bg-accent-500",
  sky: "bg-sky-500",
};

export function ProgressBar({
  value,
  max = 100,
  tone = "primary",
  label,
  showValue = false,
  size = "md",
  className = "",
}: {
  value: number;
  max?: number;
  tone?: Tone;
  label?: ReactNode;
  showValue?: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={className}>
      {(label || showValue) && (
        <div className="mb-1.5 flex items-center justify-between text-xs">
          {label && <span className="font-semibold text-ink-muted">{label}</span>}
          {showValue && <span className="num font-bold text-ink">{Math.round(pct)}٪</span>}
        </div>
      )}
      <div className={`w-full overflow-hidden rounded-full bg-slate-200/80 ${size === "sm" ? "h-1.5" : "h-2.5"}`}>
        <div
          className={`h-full rounded-full transition-[width] duration-700 ease-out ${BAR[tone]}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** Segmented multi-status bar (e.g. status distribution of topics) */
export function SegmentedBar({
  segments,
  className = "",
}: {
  segments: { value: number; color: string; label: string }[];
  className?: string;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  return (
    <div className={`flex h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70 ${className}`}>
      {segments
        .filter((s) => s.value > 0)
        .map((s, i) => (
          <div
            key={`${s.label}-${i}`}
            className={`h-full transition-[width] duration-700 ${s.color}`}
            style={{ width: `${(s.value / total) * 100}%` }}
            title={s.label}
          />
        ))}
    </div>
  );
}
