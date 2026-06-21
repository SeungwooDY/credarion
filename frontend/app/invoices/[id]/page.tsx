"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Invoice detail — disabled until Phase 2.
 *
 * The invoice OCR feature is not ready, so this route makes no API calls and
 * simply redirects back to the Invoice Processing placeholder.
 */
export default function InvoiceDetailPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/invoices");
  }, [router]);

  return null;
}
