"use client";

/** برنامه هفتگی کلاس دانش‌آموز — GET /student/schedule

همان ردیف‌هایی که مدیر مدرسه برای کلاس ثبت کرده است (یک منبع حقیقت برای همه
پنل‌ها). فقط‌خواندنی: شیفت‌های مدرسه، جلسه‌های هفتگی و معلم هر جلسه. */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { fa, subjectFa } from "@/lib/labels";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { SkeletonTable } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { IconClock, IconRefresh, IconSchool } from "@/components/ui/icons";

type Shift = { id: number; name: string; start_time: string; end_time: string; order: number };

type Entry = {
  id: number;
  day: number;
  day_name: string;
  start_time: string;
  end_time: string;
  subject: string;
  teacher_user_id: number | null;
  teacher_name: string | null;
};

/** پاسخ سرویس — بدون کلاس خالی برمی‌گردد؛ ممکن است پاسخ نرم {ok:false, reason} هم بدهد. */
type ScheduleResponse = {
  ok?: boolean;
  reason?: string;
  class_id?: number | null;
  class_name?: string | null;
  school_id?: number;
  shifts?: Shift[];
  entries?: Entry[];
};

type ScheduleData = { class_id: number | null; class_name: string | null; shifts: Shift[]; entries: Entry[] };

const EMPTY: ScheduleData = { class_id: null, class_name: null, shifts: [], entries: [] };

const DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"];

/** نرمال‌سازی پاسخ: هرگز نباید روی null یا آرایهٔ غایب کرش کند. */
function normalize(res: ScheduleResponse | null | undefined): ScheduleData {
  if (!res || typeof res !== "object") return EMPTY;
  return {
    class_id: typeof res.class_id === "number" ? res.class_id : null,
    class_name: typeof res.class_name === "string" ? res.class_name : null,
    shifts: Array.isArray(res.shifts) ? res.shifts : [],
    entries: Array.isArray(res.entries) ? res.entries : [],
  };
}

/** ردیف یک جلسه در هفته — زمان، درس و یک سطر توضیح کم‌رنگ. */
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

export function StudentScheduleSection() {
  const [data, setData] = useState<ScheduleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [softNotice, setSoftNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api<ScheduleResponse | null>("/student/schedule");
      if (res && typeof res === "object" && res.ok === false) {
        // پاسخ نرم سرور: {ok:false, reason} — دلیل باید دیده شود
        setSoftNotice(res.reason || "برنامه‌ای برای نمایش موجود نیست");
        setData(EMPTY);
      } else {
        setSoftNotice(null);
        setData(normalize(res));
      }
    } catch (e) {
      setData(EMPTY);
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

  const d = data ?? EMPTY;
  const hasClass = d.class_id !== null;
  const hasProfile = hasClass || d.class_name !== null || d.shifts.length > 0;

  /** ردیف بالای اطلاعات: کلاس، شیفت‌ها و تعداد جلسه‌ها. */
  const infoRow = (
    <div className="flex flex-wrap items-center gap-2">
      {d.class_name && <Badge tone="primary">کلاس {d.class_name}</Badge>}
      {d.shifts.map((s) => (
        <Badge key={s.id} tone="info">
          {s.name} · <span dir="ltr" className="num">{`${s.start_time}–${s.end_time}`}</span>
        </Badge>
      ))}
      {hasClass && <Badge tone="neutral">تعداد جلسات: {fa(d.entries.length)}</Badge>}
    </div>
  );

  return (
    <Section
      title="برنامه هفتگی کلاس من"
      subtitle="برنامه هفتگی همان کلاسی که مدیر مدرسه ثبت کرده است"
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
      ) : (
        <div className="space-y-4">
          {hasProfile && infoRow}

          {d.entries.length > 0 && (
            <Alert variant="info">
              این برنامه از سوی مدیر مدرسه تعیین می‌شود؛ هر تغییری بلافاصله در همین صفحه اعمال می‌شود.
            </Alert>
          )}

          {!hasClass ? (
            hasProfile ? (
              <EmptyState
                icon={<IconSchool size={26} />}
                title="هنوز بدون کلاس هستید"
                description="برنامه پس از تعیین کلاس نمایش داده می‌شود؛ شیفت‌های مدرسه را در بالا می‌بینید."
              />
            ) : (
              <EmptyState
                icon={<IconClock size={26} />}
                title="هنوز به کلاسی تخصیص ندارید"
                description="پس از تعیین کلاس توسط مدیر مدرسه، برنامه هفتگی اینجا نمایش داده می‌شود."
              />
            )
          ) : d.entries.length === 0 ? (
            <EmptyState
              compact
              icon={<IconClock size={24} />}
              title="برنامه‌ای ثبت نشده"
              description="هنوز جلسه‌ای در برنامه هفتگی کلاس شما ثبت نشده است."
            />
          ) : (
            <WeekGrid items={d.entries} extra={(e) => e.teacher_name ?? "بدون معلم"} />
          )}
        </div>
      )}
    </Section>
  );
}
