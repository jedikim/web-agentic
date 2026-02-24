import { useState } from "react";
import type { HandoffRequest } from "../types";

interface Props {
  handoff: HandoffRequest;
  onResolve: (requestId: string, action: string) => void;
}

export default function HandoffInline({ handoff, onResolve }: Props) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = () => {
    if (!input.trim()) return;
    setSubmitting(true);
    onResolve(handoff.request_id, input.trim());
  };

  return (
    <div className="animate-fade-in rounded-xl border border-amber/30 bg-amber-dim p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full bg-amber animate-glow" />
        <span className="font-mono text-[10px] uppercase tracking-widest text-amber">
          {handoff.reason === "CaptchaDetected" ? "CAPTCHA" : "Action Required"}
        </span>
      </div>

      <p className="mb-1 text-sm text-text">{handoff.message}</p>
      <p className="mb-3 font-mono text-[10px] text-muted">
        {handoff.url} &middot; {handoff.title}
      </p>

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="Enter solution..."
          disabled={submitting}
          className="flex-1 rounded-lg border border-edge bg-slab px-3 py-2 font-mono text-xs text-text placeholder:text-muted focus:border-amber/50 focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={handleSubmit}
          disabled={!input.trim() || submitting}
          className="rounded-lg border border-amber/40 bg-amber/10 px-4 py-2 font-mono text-xs text-amber transition-colors hover:bg-amber/20 disabled:opacity-40"
        >
          {submitting ? "..." : "Submit"}
        </button>
      </div>
    </div>
  );
}
