import type { Metadata } from "next";
import "./marketing.css";
import { LandingPage } from "./_components/landing-page";

export const metadata: Metadata = {
  title: "Credarion — Supplier reconciliation, resolved by morning",
  description:
    "Credarion ingests messy ERP goods receipts and supplier statements in any format, matches every line through a 4-layer engine, and flags only true discrepancies — closing seven days of reconciliation in one.",
};

export default function Page() {
  return <LandingPage />;
}
