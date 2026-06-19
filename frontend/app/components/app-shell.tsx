"use client";

import { usePathname } from "next/navigation";
import DataProvider from "./data-provider";
import Sidebar from "./sidebar";
import ChatPanel from "./chat-panel";

/**
 * Chooses the layout chrome per route. Marketing pages (e.g. /landing) render
 * bare so they can supply their own light "ledger" theme; every other route
 * gets the authenticated product shell (sidebar + assistant + purple theme).
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isBare =
    pathname === "/landing" ||
    pathname.startsWith("/landing/") ||
    pathname === "/login";

  if (isBare) {
    return <>{children}</>;
  }

  return (
    <DataProvider>
      <div className="flex h-full bg-background text-foreground">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
        <ChatPanel />
      </div>
    </DataProvider>
  );
}
