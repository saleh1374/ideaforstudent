"use client";

import type { ReactNode } from "react";
import { fa } from "@/lib/labels";

/** Lightweight hand-rolled SVG charts — no external charting dependency. */

export const CHART_COLORS = [
  "#6366f1", // indigo
  "#8b5cf6", // violet
  "#10b981", // emerald
  "#f59e0b", // amber
  "#f43f5e", // rose
  "#0ea5e9", // sky
  "#14b8a6", // teal
  "#a855f7", // purple
];

export function chartColor(i: number): string {
  return CHART_COLORS[i % CHART_COLORS.length];
}

export type Datum = { label: string; value: number; color?: string };

/* ————————————————————————————————————————————
   Vertical bar chart
   ———————————————————————————————————————————— */
export function BarChart({
  data,
  height = 220,
  format = (v: number) => fa(v),
  showValues = true,
  rtl = true,
  id = "bar",
}: {
  data: Datum[];
  height?: number;
  format?: (v: number) => string;
  showValues?: boolean;
  rtl?: boolean;
  id?: string;
}) {
  const W = 640;
  const H = height;
  const padX = 10;
  const padTop = 30;
  const padBottom = 34;
  const max = Math.max(1, ...data.map((d) => d.value));
  const chartH = H - padTop - padBottom;
  const slot = (W - padX * 2) / Math.max(data.length, 1);
  const barW = Math.min(56, slot * 0.56);
  const order = rtl ? [...data].reverse() : data;
  const gridCount = 4;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} role="img" aria-label="نمودار میله‌ای">
      <defs>
        <linearGradient id={`${id}-g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#818cf8" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
      </defs>

      {/* gridlines */}
      {Array.from({ length: gridCount + 1 }).map((_, i) => {
        const y = padTop + (chartH / gridCount) * i;
        return <line key={i} x1={padX} x2={W - padX} y1={y} y2={y} stroke="#e9edf6" strokeWidth="1" strokeDasharray={i === gridCount ? "" : "4 5"} />;
      })}

      {order.map((d, i) => {
        const cx = padX + slot * i + slot / 2;
        const h = (d.value / max) * chartH;
        const y = padTop + chartH - h;
        const color = d.color ?? `url(#${id}-g)`;
        const label = d.label.length > 11 ? `${d.label.slice(0, 10)}…` : d.label;
        return (
          <g key={`${d.label}-${i}`}>
            <rect
              x={cx - barW / 2}
              y={y}
              width={barW}
              height={Math.max(h, 2)}
              rx={8}
              fill={color}
              opacity={0.95}
              style={{ transformOrigin: `center ${padTop + chartH}px`, animation: "grow-bar .6s cubic-bezier(.22,1,.36,1) both" }}
            />
            {showValues && (
              <text x={cx} y={Math.max(y - 9, 14)} textAnchor="middle" fontSize="15" fontWeight="700" fill="#101828">
                {format(d.value)}
              </text>
            )}
            <text x={cx} y={H - 12} textAnchor="middle" fontSize="14" fill="#5a6478">
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ————————————————————————————————————————————
   Line chart (with area fill)
   ———————————————————————————————————————————— */
export function LineChart({
  points,
  labels,
  height = 200,
  format = (v: number) => fa(v),
  rtl = true,
  id = "line",
}: {
  points: number[];
  labels?: string[];
  height?: number;
  format?: (v: number) => string;
  rtl?: boolean;
  id?: string;
}) {
  const W = 640;
  const H = height;
  const padX = 16;
  const padTop = 22;
  const padBottom = labels ? 32 : 14;
  if (points.length < 2) return null;
  const chartH = H - padTop - padBottom;
  const n = Math.max(points.length, 2);
  const max = Math.max(1, ...points);
  const min = Math.min(0, ...points);
  const range = max - min || 1;
  const xs = (i: number) => padX + ((W - padX * 2) / (n - 1)) * i;
  const order = rtl ? [...points].map((_, i) => points[points.length - 1 - i]) : points;
  const coords = order.map((v, i) => [xs(i), padTop + chartH - ((v - min) / range) * chartH] as const);
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)} ${padTop + chartH} L${coords[0][0].toFixed(1)} ${padTop + chartH} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} role="img" aria-label="نمودار خطی">
      <defs>
        <linearGradient id={`${id}-area`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#6366f1" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
        </linearGradient>
      </defs>

      {[0, 1, 2, 3].map((i) => {
        const y = padTop + (chartH / 3) * i;
        return <line key={i} x1={padX} x2={W - padX} y1={y} y2={y} stroke="#e9edf6" strokeWidth="1" strokeDasharray="4 5" />;
      })}

      <path d={area} fill={`url(#${id}-area)`} />
      <path d={line} fill="none" stroke="#6366f1" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {coords.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="4.5" fill="#fff" stroke="#6366f1" strokeWidth="2.5" />
      ))}

      {labels &&
        order.map((_, i) => {
          if (labels.length > 8 && i % 2 !== 0) return null;
          const src = rtl ? labels[labels.length - 1 - i] : labels[i];
          return (
            <text key={i} x={xs(i)} y={H - 10} textAnchor="middle" fontSize="13" fill="#98a1b3">
              {src}
            </text>
          );
        })}
      {points.length > 0 && (
        <text x={coords[coords.length - 1][0]} y={Math.max(coords[coords.length - 1][1] - 12, 14)} textAnchor="middle" fontSize="15" fontWeight="700" fill="#4f46e5">
          {format(order[order.length - 1])}
        </text>
      )}
    </svg>
  );
}

/** Compact sparkline for stat cards */
export function Sparkline({
  points,
  width = 120,
  height = 40,
  stroke = "#6366f1",
  fill = true,
}: {
  points: number[];
  width?: number;
  height?: number;
  stroke?: string;
  fill?: boolean;
}) {
  if (points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const xs = (i: number) => (width / (points.length - 1)) * i;
  const ys = (v: number) => height - 4 - ((v - min) / range) * (height - 8);
  const coords = points.map((v, i) => [xs(i), ys(v)] as const);
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width} ${height} L0 ${height} Z`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      {fill && <path d={area} fill={stroke} opacity="0.12" />}
      <path d={line} fill="none" stroke={stroke} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ————————————————————————————————————————————
   Donut chart with legend
   ———————————————————————————————————————————— */
export function DonutChart({
  data,
  size = 168,
  thickness = 22,
  centerTitle,
  centerSubtitle,
  legend = true,
  format = (v: number) => fa(v),
}: {
  data: Datum[];
  size?: number;
  thickness?: number;
  centerTitle?: ReactNode;
  centerSubtitle?: ReactNode;
  /** نمایش فهرست کناری (پیش‌فرض روشن). */
  legend?: boolean;
  format?: (v: number) => string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  const visible = data.filter((d) => d.value > 0);

  return (
    <div className="flex flex-wrap items-center justify-center gap-6">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="نمودار دایره‌ای">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef1f8" strokeWidth={thickness} />
          {visible.map((d, i) => {
            const frac = total > 0 ? d.value / total : 0;
            const len = frac * c;
            const el = (
              <circle
                key={d.label}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={d.color ?? chartColor(i)}
                strokeWidth={thickness}
                strokeDasharray={`${len} ${c - len}`}
                strokeDashoffset={-offset}
                strokeLinecap="butt"
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              >
                <title>{`${d.label}: ${format(d.value)}`}</title>
              </circle>
            );
            offset += len;
            return el;
          })}
        </svg>
        <div className="absolute inset-0 grid place-content-center text-center">
          <p className="num text-2xl font-extrabold text-ink">{centerTitle ?? format(total)}</p>
          {centerSubtitle && <p className="mt-0.5 text-[11px] text-ink-muted">{centerSubtitle}</p>}
        </div>
      </div>

      {legend && (
        <ul className="min-w-[9rem] space-y-2">
          {data.map((d, i) => (
            <li key={d.label} className="flex items-center justify-between gap-4 text-xs">
              <span className="flex items-center gap-2 text-ink-muted">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color ?? chartColor(i) }} />
                {d.label}
              </span>
              <span className="num font-bold text-ink">{format(d.value)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ————————————————————————————————————————————
   Radial progress
   ———————————————————————————————————————————— */
export function RadialProgress({
  value,
  max = 100,
  size = 132,
  thickness = 12,
  label,
  color = "#6366f1",
  format = (v: number) => `${fa(v, 0)}٪`,
}: {
  value: number;
  max?: number;
  size?: number;
  thickness?: number;
  label?: ReactNode;
  color?: string;
  format?: (v: number) => string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="پیشرفت">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef1f8" strokeWidth={thickness} />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={thickness}
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={c - (pct / 100) * c}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            style={{ transition: "stroke-dashoffset .9s cubic-bezier(.22,1,.36,1)" }}
          />
        </svg>
        <div className="absolute inset-0 grid place-content-center text-center">
          <p className="num text-xl font-extrabold text-ink">{format(pct)}</p>
        </div>
      </div>
      {label && <p className="text-[11px] font-semibold text-ink-muted">{label}</p>}
    </div>
  );
}

/* ————————————————————————————————————————————
   Labeled horizontal bars (grows from the right in RTL)
   ———————————————————————————————————————————— */
export function HorizontalBars({
  data,
  format = (v: number) => fa(v),
  showTotal = false,
  className = "",
}: {
  data: Datum[];
  format?: (v: number) => string;
  showTotal?: boolean;
  className?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <ul className={`space-y-3 ${className}`}>
      {data.map((d, i) => (
        <li key={d.label}>
          <div className="mb-1 flex items-center justify-between gap-3 text-xs">
            <span className="truncate font-semibold text-ink">{d.label}</span>
            <span className="num shrink-0 text-ink-muted">
              {format(d.value)}
              {showTotal && total > 0 && <span className="text-ink-faint"> / {format(total)}</span>}
            </span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200/70">
            <div
              className="h-full rounded-full transition-[width] duration-700 ease-out"
              style={{ width: `${(d.value / max) * 100}%`, background: d.color ?? chartColor(i) }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
