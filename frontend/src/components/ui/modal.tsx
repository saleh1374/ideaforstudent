"use client";

import { useEffect, type ReactNode } from "react";
import { IconX } from "./icons";

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  const width = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 animate-fade-in bg-slate-950/45 backdrop-blur-sm" onClick={onClose} />
      <div
        className={`relative w-full ${width} animate-fade-in-up rounded-2xl border border-line bg-surface shadow-card`}
        role="dialog"
        aria-modal="true"
      >
        {title && (
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <h3 className="text-sm font-bold text-ink">{title}</h3>
            <button
              onClick={onClose}
              className="grid h-8 w-8 place-items-center rounded-lg text-ink-faint transition hover:bg-slate-100 hover:text-ink"
              aria-label="بستن"
            >
              <IconX size={16} />
            </button>
          </div>
        )}
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4 text-sm leading-7 text-ink-muted">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-4">{footer}</div>}
      </div>
    </div>
  );
}
