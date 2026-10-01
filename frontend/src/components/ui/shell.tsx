"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "@/lib/api";
import { Avatar } from "./avatar";
import { Button } from "./button";
import { Modal } from "./modal";
import { Toaster } from "./toast";
import {
  IconAlert,
  IconBook,
  IconBriefcase,
  IconChart,
  IconCheckCircle,
  IconExam,
  IconFamily,
  IconHome,
  IconLogout,
  IconMap,
  IconMenu,
  IconSchool,
  IconSparkles,
  IconTasks,
  IconUsers,
  IconX,
} from "./icons";

type Me = { id: number; username: string; full_name: string; role: string };

export const ROLE_FA: Record<string, string> = {
  student: "دانش‌آموز",
  teacher: "معلم",
  school_admin: "مدیر مدرسه",
  district_admin: "مدیر ناحیه",
  province_admin: "مدیر کل استان",
  ministry: "وزارت",
  parent: "والد",
  platform_admin: "مدیر پلتفرم",
};

type NavItem = { href: string; label: string; icon: typeof IconHome; roles?: string[] };
type NavGroup = { title: string; items: NavItem[] };

/** Navigation is built exclusively from existing routes — no dead links. */
const NAV: NavGroup[] = [
  {
    title: "دانش‌آموز",
    items: [
      { href: "/student", label: "خانه من", icon: IconHome, roles: ["student"] },
      { href: "/student/tasks", label: "برنامه امروز", icon: IconTasks, roles: ["student"] },
      { href: "/student/books", label: "کتاب‌های من", icon: IconBook, roles: ["student"] },
      { href: "/student/errors", label: "دفترچه خطا", icon: IconAlert, roles: ["student"] },
      { href: "/student/exams", label: "آزمون‌ها", icon: IconExam, roles: ["student"] },
    ],
  },
  {
    title: "آموزشی",
    items: [
      { href: "/teacher", label: "هوش کلاس", icon: IconUsers, roles: ["teacher"] },
      { href: "/tutor", label: "بازار معلم خصوصی", icon: IconBriefcase, roles: ["student", "teacher", "parent"] },
    ],
  },
  {
    title: "ناحیه",
    items: [{ href: "/district", label: "پنل مدیر ناحیه", icon: IconSchool, roles: ["district_admin"] }],
  },
  {
    title: "مدیریت",
    items: [
      { href: "/admin", label: "مدیریت مدرسه", icon: IconSchool, roles: ["school_admin"] },
      { href: "/province", label: "پنل مدیر کل استان", icon: IconMap, roles: ["province_admin"] },
      { href: "/geo", label: "استان و کشور", icon: IconMap, roles: ["ministry"] },
    ],
  },
  {
    title: "عمومی",
    items: [
      { href: "/assistant", label: "دستیار هوشمند", icon: IconSparkles },
      { href: "/boards", label: "بردهای تحلیلی", icon: IconChart },
      { href: "/parent", label: "پنل والدین", icon: IconFamily, roles: ["parent"] },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  if (pathname === href) return true;
  return href !== "/student" && pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [dateLabel, setDateLabel] = useState("");

  // close mobile sidebar on navigation
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    setDateLabel(
      new Date().toLocaleDateString("fa-IR", { weekday: "long", year: "numeric", month: "long", day: "numeric" })
    );
    if (!getToken()) return;
    // instant paint from cache, then refresh identity
    try {
      const cachedRole = localStorage.getItem("daneshyar_role");
      const cachedName = localStorage.getItem("daneshyar_name");
      if (cachedRole) setMe({ id: 0, username: "", full_name: cachedName ?? "", role: cachedRole });
    } catch {
      /* storage unavailable */
    }
    api<Me>("/auth/me")
      .then((m) => {
        setMe(m);
        try {
          localStorage.setItem("daneshyar_role", m.role);
          localStorage.setItem("daneshyar_name", m.full_name);
        } catch {
          /* storage unavailable */
        }
      })
      .catch(() => {
        /* صفحه خودش مدیریت می‌کند */
      });
  }, []);

  const role = me?.role ?? "";
  const groups = useMemo(
    () =>
      NAV.map((g) => ({
        ...g,
        items: g.items.filter((it) => !it.roles || (!!role && it.roles.includes(role))),
      })).filter((g) => g.items.length > 0),
    [role]
  );

  const logout = useCallback(() => {
    setToken(null);
    try {
      localStorage.removeItem("daneshyar_role");
      localStorage.removeItem("daneshyar_name");
    } catch {
      /* storage unavailable */
    }
    window.location.href = "/login";
  }, []);

  const roleName = role ? (ROLE_FA[role] ?? role) : "…";
  const displayName = me?.full_name || me?.username || "کاربر دانشیار";

  return (
    <div className="min-h-screen">
      {/* ——— Sidebar ——— */}
      <aside
        className={`fixed inset-y-0 right-0 z-50 flex w-64 flex-col bg-sidebar-gradient text-white shadow-sidebar transition-transform duration-300 md:translate-x-0 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* brand */}
        <div className="flex items-center justify-between gap-2 px-5 py-5">
          <Link href="/" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-gradient text-lg font-black text-white shadow-lift">
              د
            </span>
            <span>
              <span className="block text-base font-extrabold tracking-tight">دانشیار</span>
              <span className="block text-[10px] text-white/50">پلتفرم آموزشی تحلیلی</span>
            </span>
          </Link>
          <button
            onClick={() => setOpen(false)}
            className="grid h-8 w-8 place-items-center rounded-lg text-white/60 hover:bg-white/10 hover:text-white md:hidden"
            aria-label="بستن منو"
          >
            <IconX size={16} />
          </button>
        </div>

        {/* nav */}
        <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
          {groups.map((g) => (
            <div key={g.title}>
              <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-wider text-white/35">{g.title}</p>
              <ul className="space-y-1">
                {g.items.map((it) => {
                  const active = isActive(pathname, it.href);
                  const Icon = it.icon;
                  return (
                    <li key={it.href}>
                      <Link
                        href={it.href}
                        aria-current={active ? "page" : undefined}
                        className={[
                          "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-semibold transition",
                          active
                            ? "bg-white/10 text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,.08)]"
                            : "text-white/60 hover:bg-white/5 hover:text-white",
                        ].join(" ")}
                      >
                        {active && (
                          <span className="absolute inset-y-2 -right-3 w-1 rounded-full bg-accent-400" aria-hidden="true" />
                        )}
                        <Icon size={18} className={active ? "text-accent-300" : "text-white/45 group-hover:text-white/80"} />
                        <span className="truncate">{it.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {groups.length === 0 && (
            <p className="px-3 text-xs leading-6 text-white/40">در حال شناسایی سطح دسترسی…</p>
          )}
        </nav>

        {/* user footer */}
        <div className="m-3 rounded-2xl bg-white/5 p-3">
          <div className="flex items-center gap-3">
            <Avatar name={displayName} size="sm" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-bold text-white">{displayName}</p>
              <p className="truncate text-[10px] text-white/50">{roleName}</p>
            </div>
            <button
              onClick={() => setConfirmLogout(true)}
              className="grid h-8 w-8 place-items-center rounded-lg text-white/50 transition hover:bg-white/10 hover:text-white"
              aria-label="خروج"
              title="خروج"
            >
              <IconLogout size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* mobile overlay */}
      {open && <div className="fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-sm md:hidden" onClick={() => setOpen(false)} />}

      {/* ——— Content column ——— */}
      <div className="md:mr-64">
        {/* topbar */}
        <header className="sticky top-0 z-30 border-b border-line bg-canvas/85 backdrop-blur-md">
          <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setOpen(true)}
                className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-surface text-ink-muted transition hover:text-primary-600 md:hidden"
                aria-label="باز کردن منو"
              >
                <IconMenu size={18} />
              </button>
              <span className="hidden text-xs font-semibold text-ink-faint sm:block">{dateLabel}</span>
            </div>

            <div className="flex items-center gap-2">
              <span className="hidden items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 sm:flex">
                <span className="grid h-5 w-5 place-items-center rounded-md bg-success-50 text-success-600">
                  <IconCheckCircle size={13} />
                </span>
                <span className="text-[11px] font-bold text-ink-muted">{roleName}</span>
              </span>
              <Button variant="ghost" size="sm" onClick={() => setConfirmLogout(true)} icon={<IconLogout size={15} />}>
                خروج
              </Button>
            </div>
          </div>
        </header>

        {/* page content */}
        <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8 lg:px-8">{children}</main>

        <footer className="pb-8 text-center text-[11px] text-ink-faint">دانشیار — پلتفرم آموزشی تحلیلی</footer>
      </div>

      <Modal
        open={confirmLogout}
        onClose={() => setConfirmLogout(false)}
        title="خروج از حساب"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmLogout(false)}>
              انصراف
            </Button>
            <Button variant="danger" onClick={logout} icon={<IconLogout size={15} />}>
              خروج
            </Button>
          </>
        }
      >
        از حساب کاربری خارج می‌شوید؟ برای ورود مجدد به نام کاربری و رمز عبور نیاز دارید.
      </Modal>

      <Toaster />
    </div>
  );
}
