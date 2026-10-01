"use client";

import { useEffect, useMemo, useState } from "react";
import { api, getToken, BookNode } from "@/lib/api";
import { STATUS_FA, fa, subjectFa } from "@/lib/labels";
import { AppShell } from "@/components/ui/shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { StatCard } from "@/components/ui/stat";
import { Alert } from "@/components/ui/alert";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty";
import { ProgressBar } from "@/components/ui/progress";
import { SearchInput } from "@/components/ui/forms";
import { SkeletonCard } from "@/components/ui/skeleton";
import { IconBook, IconCheckCircle, IconChevronDown, IconHome, IconSearch, IconTarget } from "@/components/ui/icons";

export default function BooksPage() {
  const [books, setBooks] = useState<BookNode[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    api<{ books: BookNode[] }>("/student/books")
      .then((d) => {
        setBooks(d.books);
        if (d.books.length > 0) setOpen(d.books[0].id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim();
    if (!q) return books;
    return books.filter(
      (b) => b.title.includes(q) || b.subject.includes(q) || b.chapters.some((c) => c.title.includes(q))
    );
  }, [books, query]);

  const stats = useMemo(() => {
    const chapters = books.reduce((s, b) => s + b.chapters.length, 0);
    const topics = books.reduce((s, b) => s + b.chapters.reduce((t, c) => t + c.topics.length, 0), 0);
    const mastered = books.reduce(
      (s, b) => s + b.chapters.reduce((t, c) => t + c.topics.filter((x) => x.status === "mastered").length, 0),
      0
    );
    return { chapters, topics, mastered };
  }, [books]);

  return (
    <AppShell>
      <div className="space-y-6">
        <PageHeader
          title="کتاب‌های من"
          description="وضعیت تسلط هر مبحث در کنار درس آن؛ روی کتاب کلیک کن تا فصل‌ها باز شوند."
          crumbs={[{ label: "دانشیار" }, { label: "دانش‌آموز", href: "/student" }, { label: "کتاب‌های من" }]}
          actions={
            <ButtonLink href="/student" variant="ghost" size="sm" icon={<IconHome size={15} />}>
              خانه
            </ButtonLink>
          }
        />

        {error && <Alert variant="danger" title="خطا در دریافت کتاب‌ها">{error}</Alert>}

        {!loading && !error && (
          <>
            <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label="کتاب‌ها" value={fa(books.length)} tone="primary" icon={<IconBook size={20} />} />
              <StatCard label="فصل‌ها" value={fa(stats.chapters)} tone="accent" icon={<IconTarget size={20} />} />
              <StatCard label="مباحث" value={fa(stats.topics)} tone="sky" icon={<IconBook size={20} />} />
              <StatCard
                label="مباحث مسلط"
                value={fa(stats.mastered)}
                tone="success"
                icon={<IconCheckCircle size={20} />}
                hint={stats.topics > 0 ? `${fa((stats.mastered / stats.topics) * 100, 1)}٪ کل مباحث` : undefined}
              />
            </section>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <SearchInput value={query} onChange={setQuery} placeholder="جستجوی کتاب، درس یا فصل…" className="w-full max-w-sm" />
              <p className="num text-xs text-ink-faint">{fa(filtered.length)} نتیجه</p>
            </div>

            {filtered.length === 0 && (
              <EmptyState
                icon={<IconSearch size={26} />}
                title="کتابی با این جستجو پیدا نشد"
                description="عبارت دیگری را امتحان کن یا جستجو را پاک کن."
                action={
                  query ? (
                    <Button variant="soft" size="sm" type="button" onClick={() => setQuery("")}>
                      پاک کردن جستجو
                    </Button>
                  ) : undefined
                }
              />
            )}

            <div className="space-y-4">
              {filtered.map((b) => {
                const allTopics = b.chapters.flatMap((c) => c.topics);
                const mastered = allTopics.filter((t) => t.status === "mastered").length;
                const pct = allTopics.length > 0 ? (mastered / allTopics.length) * 100 : 0;
                const isOpen = open === b.id;
                return (
                  <Card key={b.id} padded={false} className="overflow-hidden">
                    <button
                      className="flex w-full items-center justify-between gap-4 px-5 py-4 text-right transition hover:bg-primary-50/40"
                      onClick={() => setOpen(isOpen ? null : b.id)}
                      aria-expanded={isOpen}
                    >
                      <div className="flex min-w-0 items-center gap-3.5">
                        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-gradient text-white shadow-soft">
                          <IconBook size={20} />
                        </span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-bold text-ink">{b.title}</p>
                            <Badge tone="neutral">{subjectFa(b.subject)}</Badge>
                          </div>
                          <p className="mt-1 text-[11px] text-ink-faint">
                            {fa(b.chapters.length)} فصل · {fa(allTopics.length)} مبحث · {fa(mastered)} مسلط
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <div className="hidden w-36 sm:block">
                          <ProgressBar value={pct} size="sm" tone={pct >= 66 ? "success" : "primary"} />
                        </div>
                        <IconChevronDown
                          size={18}
                          className={`text-ink-faint transition-transform ${isOpen ? "rotate-180 text-primary-600" : ""}`}
                        />
                      </div>
                    </button>

                    {isOpen && (
                      <div className="animate-fade-in border-t border-line bg-surface-sunken/60 px-5 py-4">
                        <div className="space-y-5">
                          {b.chapters.map((ch) => (
                            <div key={ch.id}>
                              <div className="mb-2 flex items-center justify-between">
                                <h3 className="text-xs font-bold text-ink">{ch.title}</h3>
                                <span className="num text-[11px] text-ink-faint">{fa(ch.topics.length)} مبحث</span>
                              </div>
                              <div className="space-y-1.5">
                                {ch.topics.map((t) => (
                                  <div
                                    key={t.id}
                                    className="flex items-center justify-between gap-3 rounded-xl bg-surface px-3.5 py-2.5 shadow-soft"
                                  >
                                    <div className="flex min-w-0 flex-1 items-center gap-3">
                                      <span className="truncate text-xs font-semibold text-ink">{t.title}</span>
                                      <div className="hidden w-28 shrink-0 sm:block">
                                        <ProgressBar value={t.effective_mastery ?? 0} size="sm" tone="primary" />
                                      </div>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-2">
                                      <span className="num text-[11px] font-bold text-ink-muted">
                                        {t.effective_mastery !== null ? `${fa(t.effective_mastery)}٪` : "—"}
                                      </span>
                                      <Badge tone={statusTone(t.status)}>{STATUS_FA[t.status] ?? t.status}</Badge>
                                    </div>
                                  </div>
                                ))}
                                {ch.topics.length === 0 && (
                                  <p className="rounded-xl border border-dashed border-line px-3.5 py-3 text-center text-[11px] text-ink-faint">
                                    مبحثی برای این فصل ثبت نشده است.
                                  </p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          </>
        )}

        {loading && (
          <div className="space-y-4">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}
      </div>
    </AppShell>
  );
}
