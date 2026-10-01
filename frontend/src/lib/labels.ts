export const STATUS_FA: Record<string, string> = {
  mastered: "مسلط",
  consolidating: "در حال تثبیت",
  weak: "ضعیف",
  critical: "بحرانی",
  unknown: "نامشخص",
};

export const STATUS_COLOR: Record<string, string> = {
  mastered: "bg-emerald-100 text-emerald-700",
  consolidating: "bg-sky-100 text-sky-700",
  weak: "bg-amber-100 text-amber-700",
  critical: "bg-red-100 text-red-700",
  unknown: "bg-slate-100 text-slate-500",
};

export const SUBJECT_FA: Record<string, string> = {
  math: "ریاضی",
  physics: "فیزیک",
  chemistry: "شیمی",
  arabic: "عربی",
  persian: "فارسی",
  english: "انگلیسی",
  biology: "زیست",
  geology: "زمین‌شناسی",
  history: "تاریخ",
  geography: "جغرافیا",
  religion: "دین و زندگی",
  physics1: "فیزیک (تجربی)",
};

/** پایهٔ تحصیلی: grade_10 → «پایهٔ دهم» */
export const GRADE_FA: Record<string, string> = {
  grade_7: "پایهٔ هفتم",
  grade_8: "پایهٔ هشتم",
  grade_9: "پایهٔ نهم",
  grade_10: "پایهٔ دهم",
  grade_11: "پایهٔ یازدهم",
  grade_12: "پایهٔ دوازدهم",
};

/** برگرداندن برچسب فارسی عنوان درس (در صورت نبود، همان مقدار اولیه). */
export const subjectFa = (value?: string | null): string =>
  (value && (SUBJECT_FA[value] || value)) || "—";

/** برگرداندن برچسب فارسی پایهٔ تحصیلی. */
export const gradeFa = (value?: string | null): string =>
  (value && (GRADE_FA[value] || value)) || "—";

export const CAUSE_FA: Record<string, string> = {
  conceptual: "ضعف مفهومی",
  prerequisite: "ضعف پیش‌نیاز",
  calculation: "خطای محاسباتی",
  careless: "بی‌دقتی",
  time_management: "کمبود زمان",
  guess: "حدس",
};

export const EXAM_TYPE_FA: Record<string, string> = {
  period_exam: "آزمون دوره",
  cumulative: "آزمون تجمعی",
  quiz: "کوییز",
  diagnostic: "تشخیصی",
  remedial_retest: "بازآزمون ترمیمی",
  practice: "تمرین",
};

export const TASK_TYPE_FA: Record<string, string> = {
  lesson: "درس",
  practice: "تمرین",
  remedial_pack: "بسته ترمیمی",
  spaced_review: "مرور فاصله",
  retest: "بازآزمون",
  quiz: "آزمونک",
};

export const NEED_FA: Record<string, string> = {
  intervention: "مداخله آموزشی",
  retention_drop: "افت ماندگاری",
  behind: "عقب‌ماندگی برنامه",
  future_risk: "ریسک آینده",
  ready: "آماده پیشروی",
};

export const NEED_COLOR: Record<string, string> = {
  intervention: "bg-red-100 text-red-700",
  retention_drop: "bg-orange-100 text-orange-700",
  behind: "bg-amber-100 text-amber-700",
  future_risk: "bg-sky-100 text-sky-700",
  ready: "bg-emerald-100 text-emerald-700",
};

export const CAUSE_SHORT: Record<string, string> = {
  conceptual: "مفهومی",
  prerequisite: "پیش‌نیاز",
  calculation: "محاسباتی",
  careless: "بی‌دقتی",
  time_management: "زمان",
  guess: "حدس",
};

export const STATUS_ORDER = ["mastered", "consolidating", "weak", "critical", "unknown"] as const;

export function fa(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fa-IR", { maximumFractionDigits: digits });
}
