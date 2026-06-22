export default function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  /** Optional element rendered at the top-right of the header (e.g. a bell). */
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h2>
        {description && (
          <p className="text-sm text-zinc-400 mt-1.5 max-w-lg">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
