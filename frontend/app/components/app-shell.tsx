"use client";

import { usePathname } from "next/navigation";
import DataProvider from "./data-provider";
import ChatPanel from "./chat-panel";
import { SessionNavBar } from "@/components/ui/sidebar";
import { LanguageProvider } from "@/app/lib/i18n";

/**
 * Chooses the layout chrome per route. Marketing pages (e.g. /landing) render
 * bare so they can supply their own light "ledger" theme; every other route
 * gets the authenticated product shell (collapsible sidebar + assistant + purple theme).
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <LanguageProvider>
      <ShellChrome>{children}</ShellChrome>
    </LanguageProvider>
  );
}

function ShellChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isMarketing = pathname === "/landing" || pathname.startsWith("/landing/");

  if (isMarketing) {
    return <>{children}</>;
  }

  return (
    <DataProvider>
      <div className="relative h-full bg-background text-foreground">
        {/* Collapsible rail — sits at the left edge, expands on hover (overlays
            content, so the main column keeps a fixed collapsed-width margin). */}
        <SessionNavBar />

        <main className="h-full overflow-y-auto pl-8 pr-8 pt-8 pb-24 sm:pb-8 ml-[3.05rem]">
          {children}
        </main>
        <ChatPanel />
      </div>
    </DataProvider>
  );
}
