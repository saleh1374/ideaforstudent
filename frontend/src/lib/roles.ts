/**
 * نگاشت نقش → صفحهٔ خانه (پس از ورود و برای redirect‌های محافظت‌شده).
 * هر نقش مدیریتی دقیقاً یک پنل اصلی دارد.
 */
export const HOME: Record<string, string> = {
  student: "/student",
  teacher: "/teacher",
  school_admin: "/admin",
  district_admin: "/district",
  province_admin: "/province",
  ministry: "/geo",
  parent: "/parent",
  // معلم خصوصیِ بازار: خانهٔ خودش است (نه /boards که برای نقش ناشناس است)
  tutor: "/tutor",
  platform_admin: "/district",
};

/** صفحهٔ خانهٔ نقش؛ برای نقش‌های ناشناس «بردهای تحلیلی» (هرگز /admin). */
export function homeFor(role: string | null | undefined): string {
  if (role && HOME[role]) return HOME[role];
  return "/boards";
}
