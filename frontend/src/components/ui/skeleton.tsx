export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

/** Text lines placeholder */
export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2.5 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton h-3.5" style={{ width: `${100 - i * 12}%` }} />
      ))}
    </div>
  );
}

/** Card-shaped loading placeholder */
export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-2xl border border-line bg-surface p-5 ${className}`} aria-hidden="true">
      <div className="mb-4 flex items-center gap-3">
        <div className="skeleton h-9 w-9 rounded-xl" />
        <div className="flex-1 space-y-2">
          <div className="skeleton h-3.5 w-1/3" />
          <div className="skeleton h-3 w-1/2" />
        </div>
      </div>
      <SkeletonText lines={3} />
    </div>
  );
}

/** Stat-card row loading placeholder (matches StatCard geometry) */
export function SkeletonStats({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-2xl border border-line bg-surface p-5">
          <div className="skeleton h-3 w-24" />
          <div className="mt-3 skeleton h-8 w-20" />
          <div className="mt-3 skeleton h-3 w-32" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface" aria-hidden="true">
      <div className="border-b border-line bg-surface-sunken px-5 py-3">
        <div className="skeleton h-3 w-1/3" />
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 border-b border-line-soft px-5 py-3.5 last:border-0">
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="skeleton h-3 flex-1" style={{ maxWidth: `${70 - c * 8}%` }} />
          ))}
        </div>
      ))}
    </div>
  );
}
