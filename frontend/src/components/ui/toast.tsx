"use client";

import { useEffect, useState } from "react";
import { IconAlert, IconCheckCircle, IconInfo, IconX } from "./icons";

export type ToastKind = "success" | "error" | "info" | "warning";

type ToastItem = { id: number; kind: ToastKind; text: string };

/** Fire a toast from anywhere (page code) — the <Toaster /> inside AppShell renders it. */
export function toast(text: string, kind: ToastKind = "info") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ToastItem>("daneshyar:toast", { detail: { id: Date.now() + Math.random(), kind, text } }));
}

const SKIN: Record<ToastKind, { wrap: string; icon: string; Icon: typeof IconInfo }> = {
  success: { wrap: "border-success-100", icon: "bg-success-50 text-success-600", Icon: IconCheckCircle },
  error: { wrap: "border-danger-100", icon: "bg-danger-50 text-danger-600", Icon: IconAlert },
  warning: { wrap: "border-warning-100", icon: "bg-warning-50 text-warning-600", Icon: IconAlert },
  info: { wrap: "border-primary-100", icon: "bg-primary-50 text-primary-600", Icon: IconInfo },
};

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    function onToast(e: Event) {
      const item = (e as CustomEvent<ToastItem>).detail;
      setItems((prev) => [...prev, item]);
      window.setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== item.id)), 5000);
    }
    window.addEventListener("daneshyar:toast", onToast);
    return () => window.removeEventListener("daneshyar:toast", onToast);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 left-4 z-[60] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
      {items.map((t) => {
        const skin = SKIN[t.kind];
        const Icon = skin.Icon;
        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex animate-fade-in-up items-start gap-2.5 rounded-2xl border bg-surface p-3.5 text-sm shadow-card ${skin.wrap}`}
            role="status"
          >
            <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-lg ${skin.icon}`}>
              <Icon size={14} />
            </span>
            <p className="flex-1 leading-6 text-ink">{t.text}</p>
            <button
              className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-ink-faint transition hover:bg-slate-100 hover:text-ink"
              onClick={() => setItems((prev) => prev.filter((x) => x.id !== t.id))}
              aria-label="بستن"
            >
              <IconX size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
