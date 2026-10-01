"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { GRADE_OPTIONS, SCHOOL_TYPE_FA } from "@/lib/labels";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/forms";
import {
  IconCheckCircle,
  IconGraduation,
  IconLock,
  IconSchool,
  IconSparkles,
  IconUser,
  IconUsers,
} from "@/components/ui/icons";

const FALLBACK_MESSAGE = "درخواست شما ثبت شد و پس از تأیید مدیر مدرسه فعال می‌شود";

/** مدرسهٔ عمومی — GET /public/schools */
type PublicSchool = { id: number; name: string; school_type?: string; district_name?: string | null };

/** نرمال‌سازی پاسخ مدارس: آرایهٔ خام یا { schools: [...] }. */
function normalizeSchools(res: unknown): PublicSchool[] {
  if (Array.isArray(res)) return res as PublicSchool[];
  if (res && typeof res === "object") {
    const schools = (res as { schools?: unknown }).schools;
    if (Array.isArray(schools)) return schools as PublicSchool[];
  }
  return [];
}

type FormErrors = {
  full_name?: string;
  username?: string;
  password?: string;
  grade?: string;
};

export default function SignupPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [grade, setGrade] = useState("grade_7");
  const [phone, setPhone] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [schools, setSchools] = useState<PublicSchool[]>([]);
  const [schoolsError, setSchoolsError] = useState("");

  const [errors, setErrors] = useState<FormErrors>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // فهرست مدارس — عمومی و بدون نیاز به توکن
  useEffect(() => {
    let alive = true;
    api<unknown>("/public/schools")
      .then((res) => {
        if (alive) setSchools(normalizeSchools(res));
      })
      .catch(() => {
        if (alive) setSchoolsError("فهرست مدارس بارگذاری نشد؛ می‌توانید بدون انتخاب مدرسه ثبت‌نام کنید یا بعداً مدرسه را مشخص کنید.");
      });
    return () => {
      alive = false;
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    const errs: FormErrors = {};
    if (!fullName.trim()) errs.full_name = "نام کامل الزامی است";
    if (!username.trim()) errs.username = "نام کاربری الزامی است";
    if (password.length < 6) errs.password = "رمز عبور باید حداقل ۶ کاراکتر باشد";
    if (!grade) errs.grade = "انتخاب پایه تحصیلی الزامی است";
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setLoading(true);
    try {
      const json: Record<string, unknown> = {
        username: username.trim(),
        password,
        full_name: fullName.trim(),
        grade,
      };
      if (phone.trim()) json.phone = phone.trim();
      if (schoolId) json.school_id = Number(schoolId);

      const res = await api<{ message_fa?: string }>("/auth/register", { method: "POST", json });
      setSuccessMessage(
        typeof res?.message_fa === "string" && res.message_fa.trim() ? res.message_fa : FALLBACK_MESSAGE
      );
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setErrors({ username: "نام کاربری قبلاً استفاده شده" });
        } else if (err.status === 400) {
          setError(err.detail ?? "اطلاعات واردشده معتبر نیست؛ فرم را بررسی کنید.");
        } else {
          setError(err.message || "خطا در ثبت‌نام؛ لطفاً دوباره تلاش کنید.");
        }
      } else {
        setError("خطا در ارتباط با سرور؛ لطفاً دوباره تلاش کنید.");
      }
    } finally {
      setLoading(false);
    }
  }

  const highlights = [
    { icon: IconGraduation, text: "برنامه روزانه، دفترچه خطا و آزمون ترمیمی بر پایهٔ تسلط واقعی" },
    { icon: IconSparkles, text: "تحلیل ریشه‌ای ضعف و پیشنهاد بستهٔ ترمیمی اختصاصی" },
    { icon: IconUsers, text: "پس از تأیید مدیر مدرسه، حساب شما فعال می‌شود" },
  ];

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
              دانش‌آموز جدید، مسیر یادگیری
              <br />
              <span className="bg-gradient-to-l from-accent-300 to-primary-300 bg-clip-text text-transparent">
                از همین‌جا شروع می‌شود
              </span>
            </h1>
            <p className="mt-3 max-w-md text-sm leading-7 text-white/60">
              ثبت‌نام رایگان است؛ پس از تأیید مدیر مدرسه، حساب شما فعال و برنامهٔ یادگیری‌تان ساخته می‌شود.
            </p>
          </div>

          <ul className="relative space-y-3.5">
            {highlights.map((h) => {
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

          <p className="relative text-[11px] text-white/35">ثبت‌نام دانش‌آموز — داده‌های شما مطابق حریم خصوصی نگهداری می‌شود</p>
        </section>

        {/* ——— form panel ——— */}
        <section className="p-6 sm:p-9">
          <div className="mb-6 lg:hidden">
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-2xl bg-brand-gradient text-lg font-black text-white shadow-lift">د</span>
              <div>
                <p className="text-lg font-extrabold text-ink">دانشیار</p>
                <p className="text-[11px] text-ink-muted">پلتفرم آموزشی تحلیلی</p>
              </div>
            </div>
          </div>

          {successMessage ? (
            /* ——— حالت موفقیت ——— */
            <div className="animate-fade-in-up space-y-4 py-6 text-center">
              <span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-success-50 text-success-600">
                <IconCheckCircle size={32} />
              </span>
              <h2 className="text-xl font-extrabold text-ink">ثبت‌نام انجام شد</h2>
              <p className="mx-auto max-w-sm text-sm leading-7 text-ink-muted">{successMessage}</p>
              <div className="flex flex-col items-center gap-3 pt-2">
                <Button size="lg" onClick={() => router.push("/login")}>
                  ورود به حساب
                </Button>
                <Link href="/login" className="text-xs font-semibold text-primary-600 transition hover:text-primary-700 hover:underline">
                  بازگشت به صفحهٔ ورود
                </Link>
              </div>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-extrabold text-ink">ثبت‌نام دانش‌آموز</h2>
              <p className="mt-1 text-xs leading-6 text-ink-muted">
                فرم زیر را کامل کنید؛ پس از تأیید مدیر مدرسه می‌توانید وارد شوید.
              </p>

              <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
                <Field label="نام کامل" required>
                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
                      <IconUser size={16} />
                    </span>
                    <Input
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      className="pr-10"
                      placeholder="مثال: علی رضایی"
                      autoComplete="name"
                    />
                  </div>
                  {errors.full_name && <span className="mt-1 block text-[11px] text-danger-600">{errors.full_name}</span>}
                </Field>

                <Field label="نام کاربری" required>
                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
                      <IconGraduation size={16} />
                    </span>
                    <Input
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="pr-10 num"
                      placeholder="username"
                      autoComplete="username"
                      dir="ltr"
                    />
                  </div>
                  {errors.username && <span className="mt-1 block text-[11px] text-danger-600">{errors.username}</span>}
                </Field>

                <Field label="رمز عبور" required hint="حداقل ۶ کاراکتر">
                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
                      <IconLock size={16} />
                    </span>
                    <Input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="pr-10"
                      autoComplete="new-password"
                    />
                  </div>
                  {errors.password && <span className="mt-1 block text-[11px] text-danger-600">{errors.password}</span>}
                </Field>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="پایه تحصیلی" required>
                    <Select value={grade} onChange={(e) => setGrade(e.target.value)}>
                      {GRADE_OPTIONS.map((g) => (
                        <option key={g.value} value={g.value}>
                          {g.label}
                        </option>
                      ))}
                    </Select>
                    {errors.grade && <span className="mt-1 block text-[11px] text-danger-600">{errors.grade}</span>}
                  </Field>

                  <Field label="تلفن (اختیاری)">
                    <Input value={phone} onChange={(e) => setPhone(e.target.value)} className="num" placeholder="09…" dir="ltr" inputMode="tel" />
                  </Field>
                </div>

                <Field label="مدرسه" hint={schoolsError || "پس از تأیید مدیر مدرسه، ثبت‌نام نهایی می‌شود."}>
                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 right-3.5 grid place-items-center text-ink-faint">
                      <IconSchool size={16} />
                    </span>
                    <Select value={schoolId} onChange={(e) => setSchoolId(e.target.value)} className="pr-10">
                      <option value="">— بدون انتخاب مدرسه —</option>
                      {schools.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                          {s.district_name ? ` — ${s.district_name}` : ""}
                          {s.school_type ? ` (${SCHOOL_TYPE_FA[s.school_type] ?? s.school_type})` : ""}
                        </option>
                      ))}
                    </Select>
                  </div>
                </Field>

                {error && <Alert variant="danger">{error}</Alert>}

                <Button type="submit" loading={loading} size="lg" className="w-full">
                  {loading ? "در حال ثبت‌نام…" : "ثبت‌نام دانش‌آموز"}
                </Button>
              </form>

              <p className="mt-5 text-center text-xs text-ink-muted">
                قبلاً ثبت‌نام کرده‌اید؟{" "}
                <Link href="/login" className="font-bold text-primary-600 transition hover:text-primary-700 hover:underline">
                  ورود به حساب
                </Link>
              </p>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
