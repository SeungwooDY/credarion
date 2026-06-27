"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useLang } from "@/app/lib/i18n";

interface MonthPickerProps {
  /** Selected month as a "YYYY-MM" string (matches the backend `period`). */
  value: string;
  onChange: (period: string) => void;
  /** Accessible label for the trigger. */
  label?: string;
}

/** Parse "YYYY-MM" into { year, month } (month is 0-indexed). Falls back to a
 *  sane current-ish value if the string is malformed. */
function parsePeriod(value: string): { year: number; month: number } {
  const m = /^(\d{4})-(\d{2})$/.exec(value ?? "");
  if (m) {
    const month = Number(m[2]) - 1;
    if (month >= 0 && month <= 11) return { year: Number(m[1]), month };
  }
  return { year: 2026, month: 0 };
}

function toPeriod(year: number, month: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}`;
}

/**
 * Month selector — replaces the free-text "2026-03" period input with a click
 * target that opens a popover (year stepper + 12-month grid). Month and year
 * labels are localized via `Intl` from the active language. The value stays a
 * "YYYY-MM" string so it's a drop-in for the existing `period` state.
 */
export function MonthPicker({ value, onChange, label }: MonthPickerProps) {
  const { lang } = useLang();
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const selected = parsePeriod(value);

  const [isOpen, setIsOpen] = useState(false);
  // Year currently shown in the popover (independent of the selected value so
  // the user can browse years without committing).
  const [viewYear, setViewYear] = useState(selected.year);
  const containerRef = useRef<HTMLDivElement>(null);

  // Re-sync the browsing year whenever the popover opens or the value changes.
  useEffect(() => {
    if (isOpen) setViewYear(selected.year);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, value]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    if (isOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const monthShort = useMemo(
    () => new Intl.DateTimeFormat(locale, { month: "short" }),
    [locale],
  );
  const triggerLabel = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "long",
        year: "numeric",
      }).format(new Date(selected.year, selected.month, 1)),
    [locale, selected.year, selected.month],
  );

  const months = useMemo(
    () =>
      Array.from({ length: 12 }, (_, i) => ({
        index: i,
        label: monthShort.format(new Date(2000, i, 1)),
      })),
    [monthShort],
  );

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={label}
        onClick={() => setIsOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground transition-colors hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
      >
        <CalendarDays className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">{triggerLabel}</span>
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute left-0 top-full z-50 mt-2 w-64 origin-top-left rounded-xl border border-border bg-popover p-3 shadow-lg"
          >
            {/* Year stepper */}
            <div className="mb-2 flex items-center justify-between">
              <button
                type="button"
                aria-label="Previous year"
                onClick={() => setViewYear((y) => y - 1)}
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="text-sm font-semibold text-foreground">{viewYear}</span>
              <button
                type="button"
                aria-label="Next year"
                onClick={() => setViewYear((y) => y + 1)}
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {/* Month grid */}
            <div className="grid grid-cols-3 gap-1.5">
              {months.map((m) => {
                const isSelected =
                  viewYear === selected.year && m.index === selected.month;
                return (
                  <button
                    key={m.index}
                    type="button"
                    onClick={() => {
                      onChange(toPeriod(viewYear, m.index));
                      setIsOpen(false);
                    }}
                    className={`rounded-md px-2 py-2 text-sm transition-colors ${
                      isSelected
                        ? "bg-accent font-medium text-accent-foreground"
                        : "text-foreground hover:bg-muted"
                    }`}
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
