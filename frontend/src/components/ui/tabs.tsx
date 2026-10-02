"use client";

import { useCallback, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export type TabItem = { key: string; label: ReactNode; count?: number; disabled?: boolean };

export function Tabs({
  items,
  value,
  onChange,
  className = "",
}: {
  items: TabItem[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div
      className={`inline-flex max-w-full flex-wrap items-center gap-1 rounded-2xl border border-line bg-surface-sunken p-1.5 shadow-soft ${className}`}
      role="tablist"
    >
      {items.map((t) => {
        const active = t.key === value;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={active}
            disabled={t.disabled}
            onClick={() => onChange(t.key)}
            className={[
              "inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition",
              active
                ? "bg-surface text-primary-700 shadow-soft ring-1 ring-primary-100"
                : "text-ink-muted hover:bg-white/70 hover:text-ink",
              t.disabled ? "cursor-not-allowed opacity-50" : "",
            ].join(" ")}
          >
            {t.label}
            {typeof t.count === "number" && (
              <span
                className={`num rounded-md px-1.5 py-0.5 text-[10px] ${
                  active ? "bg-primary-100 text-primary-700" : "bg-slate-200/70 text-ink-muted"
                }`}
              >
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * جایگاه بخش فعال را در query آدرس (؟tab=…) نگه می‌دارد تا لینک منو مستقیم آن بخش را باز کند،
 * رفرش جایگاه را از دست ندهد و دکمه‌ی Back مرورگر کار کند.
 *
 * منبع حقیقت همان آدرس است؛ `go` فقط آدرس را عوض می‌کند.
 * چون از `useSearchParams` استفاده می‌شود، باید داخل یک `<Suspense>` باشد.
 */
export function useTabParam(keys: readonly string[], fallback: string) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();

  const raw = search.get("tab");
  const value = raw !== null && keys.includes(raw) ? raw : fallback;

  const go = useCallback(
    (k: string) => {
      if (!keys.includes(k) || k === value) return;
      router.push(`${pathname}?tab=${encodeURIComponent(k)}`, { scroll: false });
    },
    [router, pathname, value, keys]
  );

  return [value, go] as const;
}
