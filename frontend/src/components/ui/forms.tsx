import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { IconSearch } from "./icons";

const BASE =
  "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-faint shadow-soft transition focus:border-primary-400 focus:ring-2 focus:ring-primary-500/20 disabled:cursor-not-allowed disabled:bg-surface-sunken";

export function Field({
  label,
  hint,
  children,
  required,
  className = "",
}: {
  label?: ReactNode;
  hint?: ReactNode;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      {label && (
        <span className="mb-1.5 flex items-center gap-1 text-xs font-semibold text-ink-muted">
          {label}
          {required && <span className="text-danger-500">*</span>}
        </span>
      )}
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-5 text-ink-faint">{hint}</span>}
    </label>
  );
}

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${BASE} ${className}`} {...rest} />;
}

export function Textarea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${BASE} min-h-[92px] resize-y ${className}`} {...rest} />;
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={`${BASE} cursor-pointer ${className}`} {...rest}>
      {children}
    </select>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "جستجو…",
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
        <IconSearch size={16} />
      </span>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`${BASE} pr-10`}
      />
    </div>
  );
}
