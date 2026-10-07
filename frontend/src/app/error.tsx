"use client";

import { useEffect } from "react";
import { IconAlert, IconRefresh } from "@/components/ui/icons";

/**
 * مرز خطای سراسری: خطای رندر یا واکشیِ یک صفحه را به‌جای صفحهٔ سفید،
 * با پیام فارسی و دکمهٔ «تلاش دوباره» نشان می‌دهد.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // برای دیدن خطا در کنسول مرورگر/سرور — بدون نشت اطلاعات به کاربر
    console.error(error);
  }, [error]);

  return (
    <main className="grid min-h-screen place-content-center gap-5 bg-canvas px-6 text-center">
      <div className="animate-fade-in-up mx-auto max-w-md space-y-4">
        <span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-danger-50 text-danger-600">
          <IconAlert size={28} />
        </span>
        <h1 className="text-lg font-extrabold text-ink sm:text-xl">خطایی پیش آمد</h1>
        <p className="text-xs leading-7 text-ink-muted">
          در نمایش این بخش مشکلی پیش آمد. معمولاً با تلاش دوباره برطرف می‌شود؛ اگر ادامه داشت از منوی کناری به بخش دیگری
          بروید.
        </p>
        {error.digest && <p className="num text-[10px] text-ink-faint">کد پیگیری: {error.digest}</p>}
        <div className="flex flex-wrap justify-center gap-2">
          <button type="button" onClick={reset} className="btn-primary text-xs">
            <IconRefresh size={15} /> تلاش دوباره
          </button>
          <a href="/" className="btn-ghost text-xs">
            صفحهٔ نخست
          </a>
        </div>
      </div>
    </main>
  );
}
