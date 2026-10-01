import type { HTMLAttributes, ReactNode } from "react";

type Variant = "plain" | "sunken" | "brand" | "gradient" | "outline";

const VARIANTS: Record<Variant, string> = {
  plain: "bg-surface border border-line shadow-soft",
  sunken: "bg-surface-sunken border border-line",
  brand: "bg-primary-50/70 border border-primary-100",
  gradient: "text-white border-0 bg-brand-gradient shadow-lift",
  outline: "bg-transparent border border-dashed border-line",
};

export type CardProps = HTMLAttributes<HTMLDivElement> & {
  variant?: Variant;
  hover?: boolean;
  padded?: boolean;
};

export function Card({ variant = "plain", hover = false, padded = true, className = "", ...rest }: CardProps) {
  return (
    <div
      className={[
        "rounded-2xl transition",
        VARIANTS[variant],
        padded ? "p-5" : "",
        hover ? "hover:-translate-y-0.5 hover:shadow-card" : "",
        className,
      ].join(" ")}
      {...rest}
    />
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        {icon && (
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-gradient-soft text-primary-600">
            {icon}
          </span>
        )}
        <div>
          <h3 className="text-sm font-bold text-ink">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs leading-5 text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function Section({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`space-y-4 ${className}`}>
      {title && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-ink">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs leading-5 text-ink-muted">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
