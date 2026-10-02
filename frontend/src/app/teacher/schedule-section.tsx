"use client";

/** برنامه هفتگی معلم — GET /teacher/my-schedule

همان ردیف‌هایی که مدیر مدرسه ثبت کرده است (یک منبع حقیقت برای همه پنل‌ها)؛
اینجا فقط‌خواندنی است: شیفت‌های مدرسه، شیفت‌های کاری معلم، بار هفتگی و
برنامه ۷ روز هفته به تفکیک کلاس. */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { fa, subjectFa } from "@/lib/labels";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Section } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconClock, IconRefresh } from "@/components/ui/icons";

type Shift = { id: number; name: string; start_time: string; end_time: string; order: number };

type MyEntry = {
  id: number;
  day: number;
  day_name: string;
  start_time: string;
  end_time: string;
  subject: string;
  class_id: number;
  class_name: string;
};

type MySchool = {
  school_id: number;
  school_name: string;
  shifts: Shift[];
  my_shifts: string[];
  weekly_hours: number;
  entries: MyEntry[];
};

/** پاسخ سرویس — ممکن است پاسخ نرم {ok:false, reason} هم برگرداند. */
type ScheduleResponse = { ok?: boolean; reason?: string; schools?: MySchool[] };

const DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"];

/** نرمال‌سازی پاسخ: هرگز نباید روی null یا آرایهٔ غایب کرش کند. */
function normalizeSchools(res: ScheduleResponse | null | undefined): MySchool[] {
  if (!res || !Array.isArray(res.schools)) return [];
  return res.schools.map((s) => ({
    ...s,
    my_shifts: Array.isArray(s?.my_shifts) ? s.my_shifts : [],
    entries: Array.isArray(s?.entries) ? s.entries : [],
  }));
}

/** ردیف یک برنامه در هفته — زمان، درس و یک سطر توضیح کم‌رنگ. */
type WeekItem = { id: number; day: number; start_time: string; end_time: string; subject: string };

/** شبکهٔ ۷ روز هفته: در موبایل فهرست عمودی، از md به بعد ۷ ستون. */
function WeekGrid<T extends WeekItem>({ items, extra }: { items: T[]; extra?: (item: T) => string | null }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-7">
      {DAYS.map((dayName, dayIdx) => {
        const dayItems = items
          .filter((it) => it.day === dayIdx)
          .sort((a, b) => a.start_time.localeCompare(b.start_time));
        return (
          <div key={dayName} className="space-y-2">
            <div className="rounded-xl bg-surface-sunken px-2 py-1.5 text-center text-[11px] font-bold text-ink-muted">
              {dayName}
            </div>
            {dayItems.length === 0 ? (
              <span className="block text-center text-xs text-ink-faint">—</span>
            ) : (
              dayItems.map((it) => {
                const note = extra ? extra(it) : null;
                return (
                  <div key={it.id} className="rounded-xl border border-line bg-surface p-2.5 shadow-soft">
                    <span dir="ltr" className="num block text-[11px] font-bold text-primary-700">
                      {it.start_time}–{it.end_time}
                    </span>
                    <p className="mt-1 text-xs font-bold text-ink">{subjectFa(it.subject)}</p>
                    {note && <p className="mt-0.5 text-[11px] text-ink-faint">{note}</p>}
                  </div>
                );
              })
            )}
          </div>
        );
      })}
    </div>
  );
}

export function TeacherScheduleSection() {
  const [schools, setSchools] = useState<MySchool[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [softNotice, setSoftNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api<ScheduleResponse | null>("/teacher/my-schedule");
      if (res && res.ok === false) {
        // پاسخ نرم سرور: {ok:false, reason} — دلیل باید دیده شود
        setSoftNotice(res.reason || "برنامه‌ای برای نمایش موجود نیست");
        setSchools([]);
      } else {
        setSoftNotice(null);
        setSchools(normalizeSchools(res));
      }
    } catch (e) {
      setSchools([]);
      setSoftNotice(null);
      if (e instanceof ApiError) toast(e.message, "error");
      else toast(e instanceof Error ? e.message : "خطا در دریافت برنامه هفتگی", "error");
      setError(e instanceof Error ? e.message : "خطا در دریافت برنامه هفتگی");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Section
      title="برنامه من"
      subtitle="برنامه هفتگی ثبت‌شده توسط مدیر مدرسه — همان داده‌ای که در پنل مدیر دیده می‌شود"
      action={
        <Button size="sm" variant="soft" icon={<IconRefresh size={14} />} loading={loading} onClick={load}>
          به‌روزرسانی
        </Button>
      }
    >
      {error && <Alert variant="danger">{error}</Alert>}

      {loading ? (
        <SkeletonTable rows={5} cols={4} />
      ) : softNotice ? (
        <Alert variant="warning" title="برنامه‌ای نمایش داده نشد">
          {softNotice}
        </Alert>
      ) : !schools || schools.length === 0 ? (
        <EmptyState
          icon={<IconClock size={26} />}
          title="هنوز برنامه‌ای برای شما ثبت نشده است"
          description="پس از ثبت برنامه هفتگی توسط مدیر مدرسه، اینجا نمایش داده می‌شود."
        />
      ) : (
        schools.map((s) => {
          const entries = s.entries ?? [];
          return (
            <Card key={s.school_id}>
              <CardHeader title={s.school_name} subtitle={`${fa(entries.length)} جلسه در هفته`} />

              <div className="mb-4 flex flex-wrap items-center gap-2">
                {(s.my_shifts ?? []).length > 0 ? (
                  (s.my_shifts ?? []).map((name) => (
                    <Badge key={name} tone="primary">
                      {name}
                    </Badge>
                  ))
                ) : (
                  <Badge tone="warning">خارج از شیفت تعریف‌شده</Badge>
                )}
                <Badge tone="accent">ساعات هفتگی: {fa(s.weekly_hours, 1)}</Badge>
              </div>

              {entries.length === 0 ? (
                <EmptyState
                  compact
                  icon={<IconClock size={24} />}
                  title="برنامه‌ای در این مدرسه ثبت نشده است"
                  description="پس از ثبت جلسه‌های هفتگی کلاس‌های شما توسط مدیر مدرسه، اینجا نمایش داده می‌شود."
                />
              ) : (
                <WeekGrid items={entries} extra={(e) => e.class_name} />
              )}
            </Card>
          );
        })
      )}
    </Section>
  );
}
