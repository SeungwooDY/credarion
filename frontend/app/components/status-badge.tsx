import { useT } from "@/app/lib/i18n";

const LABEL_KEYS: Record<string, string> = {
  received: "statusBadge.received",
  extracted: "statusBadge.extracted",
  matched: "common.status.matched",
  approved: "statusBadge.approved",
  paid: "statusBadge.paid",
  running: "statusBadge.running",
  completed: "statusBadge.completed",
  failed: "statusBadge.failed",
  discrepancy: "common.status.discrepancy",
  success: "statusBadge.success",
  error: "common.status.error",
};

const COLORS: Record<string, string> = {
  received: "bg-zinc-100 text-zinc-600",
  extracted: "bg-[var(--accent-light)] text-[var(--accent)]",
  matched: "bg-emerald-50 text-emerald-700",
  approved: "bg-violet-50 text-violet-700",
  paid: "bg-green-50 text-green-700",
  running: "bg-amber-50 text-amber-700",
  completed: "bg-green-50 text-green-700",
  failed: "bg-red-50 text-red-700",
  discrepancy: "bg-orange-50 text-orange-700",
  success: "bg-green-50 text-green-700",
  error: "bg-red-50 text-red-700",
};

export default function StatusBadge({ status }: { status: string }) {
  const t = useT();
  const color = COLORS[status] ?? "bg-zinc-100 text-zinc-600";
  const labelKey = LABEL_KEYS[status];
  const label = labelKey ? t(labelKey) : status;
  return (
    <span
      className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}
    >
      {label}
    </span>
  );
}
