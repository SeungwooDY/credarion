"use client";

import { FileText } from "lucide-react";
import PageHeader from "../components/page-header";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useT } from "@/app/lib/i18n";

/**
 * Invoice Processing — Phase 2 placeholder.
 *
 * Intentionally static: no upload form, no API calls, no error states. The OCR
 * invoice feature is gated until supplier reconciliation is fully validated.
 */
export default function InvoicesPage() {
  const t = useT();

  return (
    <>
      <PageHeader
        title={t("invoices.placeholder.title")}
        description={t("invoices.placeholder.subtitle")}
      />

      <Card className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <FileText className="h-6 w-6" />
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-foreground">
            {t("invoices.placeholder.title")}
          </h2>
          <p className="max-w-md text-sm text-muted-foreground">
            {t("invoices.placeholder.subtitle")}
          </p>
        </div>
        <Badge variant="secondary">{t("invoices.placeholder.badge")}</Badge>
      </Card>
    </>
  );
}
