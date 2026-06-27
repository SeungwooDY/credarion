"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Invoice detail — disabled until Phase 2.
 *
 * The invoice OCR feature is not ready, so this route makes no API calls and
 * simply redirects to the dashboard. (Was "/invoices"; point back there to
 * restore the Phase 2 placeholder.)
 */
export default function InvoiceDetailPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/");
  }, [router]);

  return null;
}
