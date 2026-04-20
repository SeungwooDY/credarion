const COLORS: Record<string, string> = {
  received: "bg-zinc-100 text-zinc-600",
  extracted: "bg-blue-50 text-blue-700",
  matched: "bg-emerald-50 text-emerald-700",
  approved: "bg-violet-50 text-violet-700",
  paid: "bg-green-50 text-green-700",
  running: "bg-yellow-50 text-yellow-700",
  completed: "bg-green-50 text-green-700",
  failed: "bg-red-50 text-red-700",
  discrepancy: "bg-orange-50 text-orange-700",
  success: "bg-green-50 text-green-700",
  error: "bg-red-50 text-red-700",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = COLORS[status] ?? "bg-zinc-100 text-zinc-600";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color}`}
    >
      {status}
    </span>
  );
}
