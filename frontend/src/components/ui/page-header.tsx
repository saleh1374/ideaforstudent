import Link from "next/link";
import type { ReactNode } from "react";
import { IconChevronLeft } from "./icons";

export type Crumb = { label: string; href?: string };

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
  badge,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  crumbs?: Crumb[];
  actions?: ReactNode;
  badge?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`animate-fade-in-up ${className}`}>
      {crumbs && crumbs.length > 0 && (
        <nav className="mb-2 flex items-center gap-1.5 text-[11px] text-ink-faint" aria-label="مسیر">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 && <IconChevronLeft size={12} />}
              {c.href ? (
                <Link href={c.href} className="transition hover:text-primary-600">
                  {c.label}
                </Link>
              ) : (
                <span className="text-ink-muted">{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-extrabold leading-8 text-ink sm:text-2xl">{title}</h1>
            {badge}
          </div>
          {description && <p className="mt-1 max-w-3xl text-xs leading-6 text-ink-muted sm:text-sm">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
