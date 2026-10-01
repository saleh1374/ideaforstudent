const PALETTE = [
  "from-indigo-500 to-violet-500",
  "from-sky-500 to-cyan-500",
  "from-emerald-500 to-teal-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
  "from-accent-500 to-primary-500",
];

function hashIndex(seed: string, mod: number): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return h % mod;
}

export function Avatar({
  name,
  size = "md",
  className = "",
}: {
  name: string;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
}) {
  const initial = (name || "?").trim().charAt(0);
  const bg = PALETTE[hashIndex(name || "?", PALETTE.length)];
  const dims = {
    xs: "h-6 w-6 text-[10px]",
    sm: "h-8 w-8 text-xs",
    md: "h-10 w-10 text-sm",
    lg: "h-14 w-14 text-lg",
  }[size];
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br ${bg} font-bold text-white shadow-soft ${dims} ${className}`}
      aria-hidden="true"
    >
      {initial}
    </span>
  );
}
