"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { login } from "@/lib/api";
import { homeFor } from "@/lib/roles";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/forms";
import { IconCheckCircle, IconGraduation, IconLock, IconSparkles, IconUser } from "@/components/ui/icons";

const DEMO_USERS = [
  { u: "student1", label: "دانش‌آموز" },
  { u: "teacher1", label: "معلم" },
  { u: "schooladmin", label: "مدیر مدرسه" },
  { u: "districtadmin", label: "مدیر ناحیه" },
  { u: "parent1", label: "والد" },
  { u: "provinceadmin", label: "مدیر استان" },
  { u: "ministry", label: "وزارت" },
  { u: "tutor1", label: "معلم خصوصی" },
];

const HIGHLIGHTS = [
  { icon: IconGraduation, text: "پنل دانش‌آموز با برنامه روزانه، دفترچه خطا و آزمون ترمیمی" },
  { icon: IconSparkles, text: "تحلیل ریشه‌ای ضعف با گراف پیش‌نیاز و هوش کلاس" },
  { icon: IconCheckCircle, text: "بردهای تحلیلی مدرسه، استان و کشور با حریم خصوصی" },
];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("student1");
  const [password, setPassword] = useState("pass123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(username, password);
      router.push(homeFor(data.user.role));
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطا در ورود");
      setLoading(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas p-4 sm:p-6">
      {/* background decor */}
      <div className="pointer-events-none absolute inset-0 bg-hero-gradient" aria-hidden="true" />
      <div className="pointer-events-none absolute -left-24 top-10 h-72 w-72 rounded-full bg-accent-400/15 blur-3xl" aria-hidden="true" />
      <div className="pointer-events-none absolute -right-24 bottom-0 h-72 w-72 rounded-full bg-primary-400/15 blur-3xl" aria-hidden="true" />

      <div className="relative grid w-full max-w-5xl overflow-hidden rounded-4xl border border-line bg-surface/90 shadow-card backdrop-blur-sm lg:grid-cols-[1.05fr_1fr]">
        {/* ——— brand panel ——— */}
        <section className="relative hidden flex-col justify-between bg-sidebar-gradient p-9 text-white lg:flex">
          <div className="absolute inset-0 bg-hero-gradient opacity-60" aria-hidden="true" />
          <div className="relative">
            <div className="flex items-center gap-3">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-brand-gradient text-xl font-black shadow-lift">د</span>
              <div>
                <p className="text-2xl font-extrabold">دانشیار</p>
                <p className="text-xs text-white/60">پلتفرم آموزشی تحلیلی</p>
              </div>
            </div>

            <h1 className="mt-10 text-2xl font-extrabold leading-10">
              از «خواندن» تا «جا افتادن»؛
              <br />
              <span className="bg-gradient-to-l from-accent-300 to-primary-300 bg-clip-text text-transparent">
                یادگیریِ اندازه‌گیری‌شده
              </span>
            </h1>
            <p className="mt-3 max-w-md text-sm leading-7 text-white/60">
              پیشرفت برنامه و تسلط واقعی دو شاخص جداست؛ دانشیار شکافشان را نشان می‌دهد و مسیر ترمیم را می‌سازد.
            </p>
          </div>

          <ul className="relative space-y-3.5">
            {HIGHLIGHTS.map((h) => {
              const Icon = h.icon;
              return (
                <li key={h.text} className="flex items-start gap-3 text-sm leading-6 text-white/75">
                  <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white/10 text-accent-300">
                    <Icon size={15} />
                  </span>
                  {h.text}
                </li>
              );
            })}
          </ul>

          <p className="relative text-[11px] text-white/35">ورود امن با توکن — داده‌های آموزشی مطابق حریم خصوصی دانش‌آموزان</p>
        </section>

        {/* ——— form panel ——— */}
        <section className="p-6 sm:p-9">
          <div className="mb-7 lg:hidden">
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-brand-gradient text-lg font-black text-white shadow-lift">د</span>
              <div>
                <p className="text-lg font-extrabold text-ink">دانشیار</p>
                <p className="text-[11px] text-ink-muted">پلتفرم آموزشی تحلیلی</p>
              </div>
            </div>
          </div>

          <h2 className="text-xl font-extrabold text-ink">ورود به حساب</h2>
          <p className="mt-1 text-xs leading-6 text-ink-muted">نام کاربری و رمز عبور خود را وارد کنید.</p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label="نام کاربری">
              <div className="relative">
                <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
                  <IconUser size={16} />
                </span>
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="pr-10"
                  autoComplete="username"
                  required
                />
              </div>
            </Field>

            <Field label="رمز عبور">
              <div className="relative">
                <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
                  <IconLock size={16} />
                </span>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pr-10"
                  autoComplete="current-password"
                  required
                />
              </div>
            </Field>

            {error && <Alert variant="danger">{error}</Alert>}

            <Button type="submit" loading={loading} size="lg" className="w-full">
              {loading ? "در حال ورود…" : "ورود به داشبورد"}
            </Button>
          </form>

          {/* ثبت‌نام عمومی دانش‌آموز */}
          <div className="mt-5 text-center">
            <Link
              href="/signup"
              className="text-xs font-bold text-primary-600 transition hover:text-primary-700 hover:underline"
            >
              ثبت‌نام دانش‌آموز جدید
            </Link>
          </div>

          {/* demo accounts */}
          <div className="mt-7 rounded-2xl border border-dashed border-line bg-surface-sunken p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-bold text-ink">حساب‌های نمونه</p>
              <span className="num text-[10px] text-ink-faint">رمز همه: pass123</span>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
              {DEMO_USERS.map((d) => (
                <button
                  key={d.u}
                  type="button"
                  onClick={() => {
                    setUsername(d.u);
                    setPassword("pass123");
                    setError("");
                  }}
                  className={`rounded-xl border px-2 py-2 text-[11px] font-semibold transition ${
                    username === d.u
                      ? "border-primary-300 bg-primary-50 text-primary-700"
                      : "border-line bg-surface text-ink-muted hover:border-primary-300 hover:text-primary-700"
                  }`}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
