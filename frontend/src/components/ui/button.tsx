import type { ButtonHTMLAttributes, ReactNode } from "react";
import Link from "next/link";
import type { LinkProps } from "next/link";

type Variant = "primary" | "soft" | "ghost" | "outline" | "danger" | "success";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-gradient text-white shadow-lift hover:brightness-[1.08] active:scale-[.98]",
  soft: "bg-primary-50 text-primary-700 border border-primary-100 hover:bg-primary-100 active:scale-[.98]",
  ghost:
    "bg-surface text-ink-muted border border-line hover:border-primary-300 hover:bg-primary-50/70 hover:text-primary-700",
  outline: "border border-primary-500 text-primary-700 hover:bg-primary-50",
  danger: "bg-danger-600 text-white shadow-soft hover:bg-danger-500 active:scale-[.98]",
  success: "bg-success-600 text-white shadow-soft hover:bg-success-500 active:scale-[.98]",
};

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-xs rounded-lg gap-1.5",
  md: "px-4 py-2.5 text-sm rounded-xl gap-2",
  lg: "px-6 py-3 text-base rounded-xl gap-2",
  icon: "h-9 w-9 p-0 rounded-lg",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className = "",
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center font-semibold transition focus-visible:ring-2 focus-visible:ring-primary-500/50 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
      )}
      {!loading && icon}
      {children}
    </button>
  );
}

/** Anchor-style button that navigates with the Next router (no nested interactive elements). */
export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  icon,
  className = "",
  children,
  ...rest
}: Omit<LinkProps, "href"> & {
  href: string;
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center font-semibold transition focus-visible:ring-2 focus-visible:ring-primary-500/50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {icon}
      {children}
    </Link>
  );
}
