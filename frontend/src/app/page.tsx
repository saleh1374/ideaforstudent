"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "@/lib/api";
import { homeFor } from "@/lib/roles";
import {
  IconAlert,
  IconBook,
  IconBriefcase,
  IconChart,
  IconChat,
  IconCheckCircle,
  IconFamily,
  IconGraduation,
  IconLayers,
  IconLock,
  IconMap,
  IconSchool,
  IconShield,
  IconSparkles,
  IconTarget,
  IconUsers,
} from "@/components/ui/icons";

/** شش اصلِ محصول که در README و اسناد مرجع تکرار شده‌اند. */
const PRINCIPLES = [
  {
    icon: IconTarget,
    title: "دو شاخص جدا",
    body: "پیشرفت در برنامه با تسلط واقعی فرق دارد؛ وقتی شکاف بیش از ۱۵ واحد شود پیام «خوانده اما جا نیفتاده» می‌آید.",
  },
  {
    icon: IconAlert,
    title: "۶ علت خطا",
    body: "هر گزینهٔ غلط به یک کج‌فهمی مشخص نگاشت می‌شود تا دفترچه خطا به‌جای نمره، علت تکرار خطا را نشان دهد.",
  },
  {
    icon: IconShield,
    title: "قاعدهٔ طلایی RBAC",
    body: "هیچ‌کس بیشتر از دسترسی خودش تفویض نمی‌کند؛ هر تفویض، هر انقضا و هر تصمیم با لاگ ممیزی ثبت می‌شود.",
  },
  {
    icon: IconChart,
    title: "کفِ فراموشی ۴۰٪",
    body: "ماندگاری با E = M × (0.6 + 0.4×R) محاسبه می‌شود و هر حکم حداقل به ۳ شاهد نیاز دارد.",
  },
  {
    icon: IconUsers,
    title: "حریم خصوصی داده",
    body: "بردها و تجمیع‌های استان و کشور با حداقل جمعیت ۱۰ سرکوب می‌شوند و هیچ دانش‌آموزی به‌تنهایی قابل شناسایی نیست.",
  },
  {
    icon: IconSparkles,
    title: "تحلیل قاعده‌محور",
    body: "رادار مباحث، ریشه‌یابی گراف پیش‌نیاز، گروه‌بندی ۵گانهٔ نیاز و پرچم‌های «نیازمند بررسی» — پرچم است، نه حکم.",
  },
];

const PANELS = [
  { href: "/student", icon: IconGraduation, title: "دانش‌آموز", body: "برنامهٔ روزانه، آزمون، دفترچه خطا، بازآزمون ترمیمی و تقویم ۱۴ روزه." },
  { href: "/teacher", icon: IconUsers, title: "معلم", body: "هوش کلاس، ریشه‌یابی پیش‌نیاز، سازندهٔ آزمون، تحلیل سؤال و دستیار کلاس." },
  { href: "/admin", icon: IconSchool, title: "مدیر مدرسه", body: "مقایسهٔ کلاس‌ها، سامانهٔ «نیازمند بررسی»، نمایهٔ معلمان، ثبت‌نام و استخدام." },
  { href: "/district", icon: IconMap, title: "مدیر ناحیه", body: "مدارس ناحیه، کارکنان، صلاحیت معلم، آزمون‌های رسمی و مداخلات." },
  { href: "/province", icon: IconLayers, title: "استان و وزارت", body: "تجمیع ملی و استانی، رتبه‌بندی استان‌ها و توصیه‌های اولویت‌دار." },
  { href: "/parent", icon: IconFamily, title: "والدین", body: "گزارش هفتگی، نتایج آزمون، برنامهٔ فرزند و هشدارهای به‌موقع — بدون رتبه‌بندی." },
  { href: "/assistant", icon: IconChat, title: "دستیار هوشمند", body: "نرمال‌سازی فارسی، کش معنایی، بازیابی منابع و مسیریابی مدل کوچک/بزرگ." },
  { href: "/tutor", icon: IconBriefcase, title: "بازار معلم خصوصی", body: "درخواست جلسه، چت گروهی ایمن، تأیید هویت و گردش کار مالی." },
];

/** صفحهٔ نخست: معرفی محصول + دکمهٔ ورود (یا ادامهٔ فعالیت اگر قبلاً وارد شده باشید). */
export default function Home() {
  const [authed, setAuthed] = useState<{ role: string } | null>(null);

  useEffect(() => {
    if (!getToken()) return;
    try {
      const role = localStorage.getItem("daneshyar_role");
      if (role) setAuthed({ role });
    } catch {
      /* storage unavailable */
    }
  }, []);

  const continueHref = authed ? homeFor(authed.role) : "/login";

  return (
    <div className="min-h-screen bg-canvas">
      {/* ——— نوار بالا ——— */}
      <header className="sticky top-0 z-30 border-b border-line bg-canvas/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-gradient text-lg font-black text-white shadow-lift">
              د
            </span>
            <span>
              <span className="block text-base font-extrabold leading-5 text-ink">دانشیار</span>
              <span className="block text-[10px] text-ink-faint">پلتفرم آموزشی تحلیلی</span>
            </span>
          </Link>
          <nav className="flex items-center gap-2">
            <Link href="/signup" className="btn-ghost hidden text-xs sm:inline-flex">
              ثبت‌نام
            </Link>
            <Link href={continueHref} className="btn-primary text-xs">
              {authed ? "ادامهٔ فعالیت" : "ورود"}
            </Link>
          </nav>
        </div>
      </header>

      {/* ——— Hero ——— */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-hero-gradient" aria-hidden="true" />
        <div className="relative mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
          <div className="max-w-3xl animate-fade-in-up">
            <span className="badge bg-white text-primary-700 shadow-soft ring-1 ring-primary-100">
              پایه‌های دهم تا دوازدهم — دانش‌آموز، معلم، مدرسه، ناحیه، استان و والدین
            </span>
            <h1 className="mt-4 text-3xl font-black leading-[1.25] text-ink sm:text-5xl sm:leading-[1.2]">
              یادگیری را با <span className="bg-brand-gradient bg-clip-text text-transparent">تحلیل</span> جلو ببر،
              <br className="hidden sm:block" /> نه با حدس.
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-ink-muted sm:text-base">
              دانشیار با مدل تحلیلی SLM روی هر پاسخ، تسلط، ماندگاری و پایداری یادگیری را جداگانه می‌سنجد، علت شش‌گانهٔ خطا را
              تشخیص می‌دهد و برنامهٔ مرور، بازآزمون ترمیمی و گزارش هر نقش را از همان داده می‌سازد.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link href={continueHref} className="btn-primary px-5 py-3 text-sm">
                {authed ? "رفتن به پنل من" : "شروع — ورود به حساب"}
              </Link>
              <Link href="/signup" className="btn-ghost px-5 py-3 text-sm">
                ساخت حساب جدید
              </Link>
            </div>
            <ul className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] font-semibold text-ink-muted">
              <li className="flex items-center gap-1.5">
                <IconCheckCircle size={14} className="text-success-600" /> ۶ علت خطا + دفترچهٔ خطا
              </li>
              <li className="flex items-center gap-1.5">
                <IconCheckCircle size={14} className="text-success-600" /> چرخهٔ ترمیم و بازآزمون
              </li>
              <li className="flex items-center gap-1.5">
                <IconCheckCircle size={14} className="text-success-600" /> حریم خصوصی و حداقل جمعیت ۱۰
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* ——— اصول ——— */}
      <section className="mx-auto max-w-6xl px-4 pb-8 sm:px-6">
        <h2 className="text-lg font-extrabold text-ink sm:text-xl">اصولی که پلتفرم روی آن ساخته شده</h2>
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PRINCIPLES.map((p) => {
            const Icon = p.icon;
            return (
              <article key={p.title} className="surface-card animate-fade-in-up p-5">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-gradient-soft text-primary-700">
                  <Icon size={19} />
                </span>
                <h3 className="mt-3 text-sm font-extrabold text-ink">{p.title}</h3>
                <p className="mt-1.5 text-xs leading-6 text-ink-muted">{p.body}</p>
              </article>
            );
          })}
        </div>
      </section>

      {/* ——— پنل‌ها ——— */}
      <section className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <h2 className="text-lg font-extrabold text-ink sm:text-xl">یک داده، ۸ دیدگاه متفاوت</h2>
        <p className="mt-1 text-xs leading-6 text-ink-muted">
          هر نقش فقط همان چیزی را می‌بیند که مجوزش را دارد؛ همان پاسخ آزمون، از دید دانش‌آموز تا دید وزارت.
        </p>
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PANELS.map((p) => {
            const Icon = p.icon;
            return (
              <Link
                key={p.href + p.title}
                href={p.href}
                className="surface-card group p-5 transition hover:-translate-y-0.5 hover:border-primary-200 hover:shadow-card"
              >
                <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-gradient text-white shadow-lift">
                  <Icon size={17} />
                </span>
                <h3 className="mt-3 text-sm font-extrabold text-ink group-hover:text-primary-700">{p.title}</h3>
                <p className="mt-1 text-[11px] leading-6 text-ink-muted">{p.body}</p>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ——— حریم خصوصی + CTA ——— */}
      <section className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <div className="overflow-hidden rounded-3xl bg-sidebar-gradient text-white shadow-sidebar">
          <div className="grid gap-6 p-7 sm:p-10 lg:grid-cols-[1.4fr_1fr] lg:items-center">
            <div>
              <span className="badge bg-white/10 text-accent-300">
                <IconLock size={13} /> حریم خصوصی در طراحی، نه در الحاقیه
              </span>
              <h2 className="mt-3 text-xl font-extrabold sm:text-2xl">دادهٔ دانش‌آموز شفاف است، هویتش نه</h2>
              <p className="mt-2 max-w-2xl text-xs leading-7 text-white/70">
                بردها با نام مستعار و حداقل جمعیت ۱۰ نمایش داده می‌شوند، تجمیع استان و کشور مجوز جدا می‌خواهد، دسترسی‌های
                موقت خودکار منقضی می‌شوند و همهٔ تصمیم‌ها در لاگ ممیزی ثبت می‌شوند.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 lg:justify-end">
              <Link href="/signup" className="btn-primary px-5 py-3 text-sm">
                ثبت‌نام مدرسه یا والد
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/10 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/20"
              >
                <IconBook size={16} /> ورود
              </Link>
            </div>
          </div>
        </div>
      </section>

      <footer className="border-t border-line py-8 text-center text-[11px] text-ink-faint">
        دانشیار — پلتفرم آموزشی تحلیلی مبتنی بر مدل یادگیری (SLM)
      </footer>
    </div>
  );
}
