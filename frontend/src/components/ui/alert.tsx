import type { ReactNode } from "react";
import { IconAlert, IconCheckCircle, IconInfo } from "./icons";

type Variant = "info" | "success" | "warning" | "danger";

const STYLES: Record<Variant, { wrap: string; icon: string; Icon: typeof IconInfo }> = {
  info: {
    wrap: "border-primary-100 bg-primary-50/70 text-primary-800",
    icon: "bg-primary-100 text-primary-700",
    Icon: IconInfo,
  },
  success: {
    wrap: "border-success-100 bg-success-50 text-success-700",
    icon: "bg-success-100 text-success-700",
    Icon: IconCheckCircle,
  },
  warning: {
    wrap: "border-warning-100 bg-warning-50 text-warning-700",
    icon: "bg-warning-100 text-warning-700",
    Icon: IconAlert,
  },
  danger: {
    wrap: "border-danger-100 bg-danger-50 text-danger-700",
    icon: "bg-danger-100 text-danger-700",
    Icon: IconAlert,
  },
};

export function Alert({
  variant = "info",
  title,
  children,
  className = "",
}: {
  variant?: Variant;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const s = STYLES[variant];
  const Icon = s.Icon;
  return (
    <div className={`flex items-start gap-3 rounded-2xl border p-4 text-sm leading-6 ${s.wrap} ${className}`} role="alert">
      <span className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg ${s.icon}`}>
        <Icon size={15} />
      </span>
      <div className="min-w-0">
        {title && <p className="mb-0.5 font-bold">{title}</p>}
        <div className="[&_b]:font-semibold">{children}</div>
      </div>
    </div>
  );
}
