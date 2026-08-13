"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Lock } from "lucide-react";
import { useLang } from "@/app/lib/i18n";
import { maxSelectablePeriod } from "@/app/lib/period";

export interface MonthPickerPeriod {
  period: string;
  has_data: boolean;
  locked: boolean;
}

/**
 * Month calendar — a year header with ‹ › steppers over a 3×4 month grid.
 *
 * Any past month is selectable; the future is capped at maxSelectablePeriod
 * (December of next year). Months known to the org (from /periods) show a
 * data dot / lock icon, but unknown months are selectable too — the caller
 * decides what selecting a brand-new month means (the sidebar creates it).
 */
export default function MonthPicker({
  value,
  onSelect,
  periods,
  disabled = false,
}: {
  value: string;
  onSelect: (period: string) => void;
  /** Org's known months (from usePeriods) — used purely for indicators. */
  periods?: MonthPickerPeriod[];
  disabled?: boolean;
}) {
  const { lang } = useLang();
  const maxPeriod = maxSelectablePeriod();
  const maxYear = Number(maxPeriod.slice(0, 4));
  const [year, setYear] = useState(() =>
    /^\d{4}-\d{2}$/.test(value) ? Number(value.slice(0, 4)) : new Date().getFullYear()
  );

  const byPeriod = new Map((periods ?? []).map((p) => [p.period, p]));
  const monthFmt = new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "short",
  });

  return (
    <div className="p-2">
      <div className="mb-1 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setYear((y) => y - 1)}
          disabled={disabled}
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent disabled:pointer-events-none disabled:opacity-30"
          aria-label={String(year - 1)}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="text-xs font-semibold text-foreground">{year}</span>
        <button
          type="button"
          onClick={() => setYear((y) => y + 1)}
          disabled={disabled || year >= maxYear}
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent disabled:pointer-events-none disabled:opacity-30"
          aria-label={String(year + 1)}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="grid grid-cols-3 gap-1">
        {Array.from({ length: 12 }, (_, i) => {
          const period = `${year}-${String(i + 1).padStart(2, "0")}`;
          const info = byPeriod.get(period);
          const beyondMax = period > maxPeriod;
          const selected = period === value;
          return (
            <button
              key={period}
              type="button"
              onClick={() => onSelect(period)}
              disabled={disabled || beyondMax}
              className={`relative flex h-8 items-center justify-center gap-1 rounded-md text-xs transition-colors disabled:pointer-events-none disabled:opacity-30 ${
                selected
                  ? "bg-accent font-semibold text-white"
                  : info?.has_data
                    ? "font-medium text-foreground hover:bg-muted"
                    : "text-zinc-500 hover:bg-muted"
              }`}
            >
              {monthFmt.format(new Date(year, i, 1))}
              {info?.locked && (
                <Lock className={`h-2.5 w-2.5 ${selected ? "text-white" : "text-emerald-600"}`} />
              )}
              {info?.has_data && !selected && (
                <span className="absolute bottom-1 h-1 w-1 rounded-full bg-accent" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
