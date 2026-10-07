import Link from "next/link";
import { IconCompass, IconHome, IconSearch } from "@/components/ui/icons";

/** صفحهٔ ۴۰۴ — برای آدرس‌هایی که وجود ندارند (منو هیچ لینک مرده‌ای ندارد). */
export default function NotFound() {
  return (
    <main className="grid min-h-screen place-content-center gap-5 bg-canvas px-6 text-center">
      <div className="animate-fade-in-up space-y-4">
        <span className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-brand-gradient text-white shadow-lift">
          <IconCompass size={28} />
        </span>
        <p className="num text-5xl font-black text-primary-700">۴۰۴</p>
        <h1 className="text-lg font-extrabold text-ink sm:text-xl">این صفحه پیدا نشد</h1>
        <p className="mx-auto max-w-md text-xs leading-7 text-ink-muted">
          آدرس مورد نظر وجود ندارد یا جابه‌جا شده است. اگر از منوی کناری آمده‌اید، ممکن است نقش شما به آن بخش دسترسی نداشته
          باشد.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Link href="/" className="btn-primary text-xs">
            <IconHome size={15} /> صفحهٔ نخست
          </Link>
          <Link href="/boards" className="btn-ghost text-xs">
            <IconSearch size={15} /> بردهای تحلیلی
          </Link>
        </div>
      </div>
    </main>
  );
}
