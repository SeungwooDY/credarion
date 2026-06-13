"use client";

import { type ReactNode } from "react";
import { SWRConfig } from "swr";
import { swrDefaults } from "../lib/swr";

// Re-export useOrgs so existing imports keep working
export { useOrgs } from "../lib/swr";

export default function DataProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={swrDefaults}>
      {children}
    </SWRConfig>
  );
}
