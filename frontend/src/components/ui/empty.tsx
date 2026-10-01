import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  description,
  action,
  compact = false,
  className = "",
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center rounded-2xl border border-dashed border-line bg-surface-sunken text-center ${
        compact ? "gap-2 px-4 py-8" : "gap-3 px-6 py-14"
      } ${className}`}
    >
      <span className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-gradient-soft text-primary-500">
        {icon ?? <EmptyGlyph />}
      </span>
      <div className="space-y-1">
        <p className="text-sm font-bold text-ink">{title}</p>
        {description && <p className="mx-auto max-w-md text-xs leading-6 text-ink-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

function EmptyGlyph() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="14" rx="3" />
      <path d="M3.5 10h17" />
      <path d="M8 14.5h5" />
    </svg>
  );
}
