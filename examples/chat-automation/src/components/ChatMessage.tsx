import type { Attachment, ChatMessage } from "../types";
import StepLogStream from "./StepLogStream";
import ScreenshotViewer from "./ScreenshotViewer";

interface Props {
  message: ChatMessage;
}

export default function ChatMessageView({ message }: Props) {
  const { type, content, meta } = message;

  if (type === "user") {
    const attachments = meta?.attachments as Attachment[] | undefined;
    return (
      <div className="animate-fade-in flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-md bg-cyan/12 px-4 py-2.5 text-sm text-text">
          {content}
          {attachments && attachments.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5" data-testid="message-attachments">
              {attachments.map((att, i) => (
                <img
                  key={`${att.filename}-${i}`}
                  src={att.dataUrl}
                  alt={att.filename}
                  className="h-16 w-16 rounded-lg object-cover border border-cyan/20"
                />
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (type === "system") {
    return (
      <div className="animate-fade-in flex justify-center py-1">
        <span className="rounded-full border border-edge bg-slab/60 px-3 py-1 font-mono text-[11px] text-muted">
          {content}
        </span>
      </div>
    );
  }

  if (type === "step_log") {
    return <StepLogStream content={content} meta={meta} />;
  }

  if (type === "result") {
    const success = meta?.success as boolean;
    return (
      <div className="animate-fade-in">
        <div
          className={`rounded-xl border px-4 py-3 font-mono text-xs ${
            success
              ? "border-cyan/20 bg-cyan-dim text-cyan"
              : "border-rose/20 bg-rose-dim text-rose"
          }`}
        >
          <span className="mr-2">{success ? "\u2713" : "\u2717"}</span>
          {content}
        </div>
      </div>
    );
  }

  if (type === "screenshot") {
    return <ScreenshotViewer src={content} />;
  }

  if (type === "handoff") {
    return (
      <div className="animate-fade-in">
        <div className="rounded-xl border border-amber/30 bg-amber-dim px-4 py-3">
          <div className="mb-1 flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-amber animate-glow" />
            <span className="font-mono text-[10px] uppercase tracking-widest text-amber">
              Handoff Required
            </span>
          </div>
          <p className="text-sm text-text">{content}</p>
          <p className="mt-1 font-mono text-[10px] text-muted">
            Reason: {String(meta?.reason || "unknown")}
          </p>
        </div>
      </div>
    );
  }

  return null;
}
