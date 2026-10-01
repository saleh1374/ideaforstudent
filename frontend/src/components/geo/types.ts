/** انواع مشترک داده‌های تجمیعی استان/کشور (سرویس‌های geo). */

export type Overview = {
  scope: string;
  province_id: number | null;
  schools_count: number;
  students_count: number;
  avg_mastery: number | null;
  suppressed: boolean;
  min_group: number;
  worst_topics: { topic_id: number; subject: string | null; students_count: number; avg_mastery: number | null; weak_ratio: number | null }[];
  note_fa: string;
};

export type TopicRow = {
  topic_id: number;
  subject: string | null;
  students_count: number;
  avg_mastery: number | null;
  avg_retention: number | null;
  weak_ratio: number | null;
  suppressed: boolean;
};

/** روایت تحلیلی نقاط ضعف (insights service) — برای استان و سطح ملی. */
export type Insights = {
  scope: string;
  province_id: number | null;
  generated_at: string;
  headline_fa: string;
  weakest_subjects: { subject: string; avg_mastery: number; weak_ratio: number; students_count: number }[];
  weakest_topics: { topic_id: number; title: string; subject: string | null; avg_mastery: number; weak_ratio: number | null }[];
  province_ranking: { province_id: number; name: string; avg_mastery: number | null; students_count: number; suppressed: boolean }[];
  suppressed_provinces: { province_id: number; name: string; note_fa: string }[];
  strengths_fa: string[];
  recommendations: { priority: number; title_fa: string; detail_fa: string }[];
};
