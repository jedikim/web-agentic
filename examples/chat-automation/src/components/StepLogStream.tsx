interface Props {
  content: string;
  meta?: Record<string, unknown>;
}

export default function StepLogStream({ content, meta }: Props) {
  const status = (meta?.status as string) || "running";
  const method = (meta?.method as string) || "";

  const statusConfig = {
    running: {
      icon: "\u25B6",
      color: "text-blue",
      bg: "bg-blue-dim",
      border: "border-blue/15",
    },
    ok: {
      icon: "\u2713",
      color: "text-cyan",
      bg: "bg-cyan-dim",
      border: "border-cyan/15",
    },
    fail: {
      icon: "\u2717",
      color: "text-rose",
      bg: "bg-rose-dim",
      border: "border-rose/15",
    },
  }[status] || {
    icon: "\u2022",
    color: "text-dim",
    bg: "bg-plate",
    border: "border-edge",
  };

  return (
    <div className="animate-fade-in">
      <div
        className={`flex items-start gap-2.5 rounded-lg border ${statusConfig.border} ${statusConfig.bg} px-3 py-2`}
      >
        <span className={`mt-0.5 font-mono text-xs ${statusConfig.color}`}>
          {statusConfig.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs text-soft">{content}</p>
        </div>
        {method && (
          <span className="shrink-0 rounded border border-edge bg-slab px-1.5 py-0.5 font-mono text-[9px] text-muted">
            {method}
          </span>
        )}
      </div>
    </div>
  );
}
