export default function PageHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="mb-8">
      <h2 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h2>
      {description && (
        <p className="text-sm text-zinc-400 mt-1.5 max-w-lg">{description}</p>
      )}
    </div>
  );
}
