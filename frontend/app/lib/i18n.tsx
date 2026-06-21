"use client";

/**
 * Lightweight client-side i18n for Credarion.
 *
 * One language toggle (EN ↔ 简体中文), no routing, no external deps.
 * All translatable UI strings live in `dictionary.ts`. Real data values
 * (supplier names, pinyin, currency figures, API-returned text) are never
 * translated — only static interface chrome flows through `t()`.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from "react";
import { dictionary, type Lang } from "./dictionary";

const STORAGE_KEY = "credarion-lang";

// ── localStorage-backed external store ──
// useSyncExternalStore keeps the language hydration-safe: the server snapshot is
// always "en" (matching SSR), the client snapshot reads the saved preference,
// and the `storage` event syncs the choice across tabs.

const listeners = new Set<() => void>();

function readLang(): Lang {
  return window.localStorage.getItem(STORAGE_KEY) === "zh" ? "zh" : "en";
}

function writeLang(next: Lang) {
  window.localStorage.setItem(STORAGE_KEY, next);
  listeners.forEach((fn) => fn());
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  toggle: () => void;
}

const LangContext = createContext<LangContextValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const lang = useSyncExternalStore(
    subscribe,
    readLang,
    () => "en" as Lang
  );

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const setLang = useCallback((next: Lang) => writeLang(next), []);
  const toggle = useCallback(() => writeLang(readLang() === "en" ? "zh" : "en"), []);

  const value = useMemo(
    () => ({ lang, setLang, toggle }),
    [lang, setLang, toggle]
  );

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used within a LanguageProvider");
  return ctx;
}

export type TFunction = (
  key: string,
  vars?: Record<string, string | number>
) => string;

/**
 * Returns the translator for the active language. Falls back to English, then
 * to the raw key, so any string missed during translation stays visible rather
 * than rendering blank. Supports `{name}` placeholder interpolation.
 */
export function useT(): TFunction {
  const { lang } = useLang();
  return useCallback(
    (key, vars) => {
      let s = dictionary[lang][key] ?? dictionary.en[key] ?? key;
      if (vars) {
        for (const k of Object.keys(vars)) {
          s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(vars[k]));
        }
      }
      return s;
    },
    [lang]
  );
}
