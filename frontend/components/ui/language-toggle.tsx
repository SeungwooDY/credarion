"use client";

import { cn } from "@/lib/utils";
import { useLang, useT } from "@/app/lib/i18n";

interface LanguageToggleProps {
  className?: string;
}

/**
 * Sliding pill that switches the app language between English ("EN") and
 * Simplified Chinese ("中"). Adapted from the 21st.dev theme-toggle — same
 * visual, but the knob slides EN (left) ⇄ 中文 (right) instead of light/dark.
 */
export function LanguageToggle({ className }: LanguageToggleProps) {
  const { lang, toggle } = useLang();
  const t = useT();
  const isZh = lang === "zh";

  return (
    <div
      className={cn(
        "flex w-16 h-8 p-1 rounded-full cursor-pointer transition-all duration-300 bg-white border border-zinc-200 shadow-sm",
        className
      )}
      onClick={toggle}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggle();
        }
      }}
      role="switch"
      aria-checked={isZh}
      aria-label={t("nav.lang_toggle_aria")}
      tabIndex={0}
    >
      <div className="flex justify-between items-center w-full">
        {/* Knob */}
        <div
          className={cn(
            "flex justify-center items-center w-6 h-6 rounded-full text-xs font-semibold text-white transition-transform duration-300",
            isZh ? "translate-x-8" : "translate-x-0"
          )}
          style={{ backgroundColor: "#4169E1" }}
        >
          {isZh ? "中" : "EN"}
        </div>
        {/* Inactive label */}
        <div
          className={cn(
            "flex justify-center items-center w-6 h-6 rounded-full text-xs font-medium text-zinc-400 transition-transform duration-300",
            isZh ? "-translate-x-8" : "translate-x-0"
          )}
        >
          {isZh ? "EN" : "中"}
        </div>
      </div>
    </div>
  );
}
