interface Props {
  sessionId: string | null;
  headless: boolean;
  onToggleHeadless: () => void;
  isRunning: boolean;
  onCancel: () => void;
  onClose: () => void;
  onNewSession: () => void;
  totalCost: number;
  turnCount: number;
}

export default function SessionHeader({
  sessionId,
  headless,
  onToggleHeadless,
  isRunning,
  onCancel,
  onClose,
  onNewSession,
  totalCost,
  turnCount,
}: Props) {
  return (
    <header className="flex items-center justify-between border-b border-edge bg-slab/80 px-5 py-3 backdrop-blur-sm">
      {/* Left: branding */}
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-cyan/10">
          <span className="font-mono text-sm font-semibold text-cyan">WA</span>
        </div>
        <div>
          <h1 className="font-display text-sm font-semibold tracking-tight text-text">
            Web-Agentic Chat
          </h1>
          {sessionId && (
            <p className="font-mono text-[10px] text-muted">
              {sessionId.slice(0, 12)}...
            </p>
          )}
        </div>
      </div>

      {/* Center: stats */}
      {sessionId && (
        <div className="flex items-center gap-6">
          <Stat label="Turns" value={String(turnCount)} />
          <Stat label="Cost" value={`$${totalCost.toFixed(4)}`} />
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                isRunning ? "bg-cyan animate-glow" : "bg-muted"
              }`}
            />
            <span className="font-mono text-[10px] text-dim">
              {isRunning ? "Running" : "Idle"}
            </span>
          </div>
        </div>
      )}

      {/* Right: controls */}
      <div className="flex items-center gap-2">
        {!sessionId && (
          <button
            onClick={onToggleHeadless}
            className="rounded-md border border-edge px-3 py-1.5 font-mono text-xs text-dim transition-colors hover:border-cyan/40 hover:text-text"
          >
            {headless ? "Headless" : "Headful"}
          </button>
        )}
        {sessionId && isRunning && (
          <button
            onClick={onCancel}
            className="rounded-md border border-rose/40 bg-rose-dim px-3 py-1.5 font-mono text-xs text-rose transition-colors hover:bg-rose/20"
          >
            Cancel
          </button>
        )}
        {sessionId && !isRunning && (
          <>
            <button
              onClick={onNewSession}
              className="rounded-md border border-edge px-3 py-1.5 font-mono text-xs text-dim transition-colors hover:border-cyan/40 hover:text-text"
            >
              New
            </button>
            <button
              onClick={onClose}
              className="rounded-md border border-edge px-3 py-1.5 font-mono text-xs text-dim transition-colors hover:border-rose/40 hover:text-rose"
            >
              Close
            </button>
          </>
        )}
      </div>
    </header>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <p className="font-mono text-xs font-medium text-text">{value}</p>
      <p className="text-[9px] uppercase tracking-widest text-muted">{label}</p>
    </div>
  );
}
