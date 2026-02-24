import { useEffect, useRef, useState } from "react";
import type { Attachment, ChatMessage, HandoffRequest } from "../types";
import ChatMessageView from "./ChatMessage";
import HandoffInline from "./HandoffInline";

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const MAX_FILES = 5;

interface Props {
  messages: ChatMessage[];
  sessionId: string | null;
  isRunning: boolean;
  handoffs: HandoffRequest[];
  onStartSession: (url: string, attachments?: Attachment[]) => void;
  onSend: (intent: string, attachments?: Attachment[]) => void;
  onResolveHandoff: (requestId: string, action: string) => void;
}

export default function ChatPanel({
  messages,
  sessionId,
  isRunning,
  handoffs,
  onStartSession,
  onSend,
  onResolveHandoff,
}: Props) {
  const [input, setInput] = useState("");
  const [urlInput, setUrlInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, handoffs]);

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    const remaining = MAX_FILES - attachments.length;
    const toProcess = Array.from(files).slice(0, remaining);

    for (const file of toProcess) {
      if (file.size > MAX_FILE_SIZE) {
        continue; // Skip files over 10MB
      }
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result as string;
        setAttachments((prev) => {
          if (prev.length >= MAX_FILES) return prev;
          return [
            ...prev,
            {
              filename: file.name,
              mimeType: file.type,
              dataUrl,
              size: file.size,
            },
          ];
        });
      };
      reader.readAsDataURL(file);
    }
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = () => {
    const text = input.trim();
    if (!text) return;

    const atts = attachments.length > 0 ? [...attachments] : undefined;
    if (!sessionId) {
      onStartSession(urlInput.trim(), atts);
    } else {
      onSend(text, atts);
    }
    setInput("");
    setAttachments([]);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Message area */}
      <div className="bg-grid flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-2 px-4 py-6">
          {messages.length === 0 && !sessionId && (
            <EmptyState />
          )}

          {messages.map((msg) => (
            <ChatMessageView key={msg.id} message={msg} />
          ))}

          {/* Pending handoffs */}
          {handoffs.map((h) => (
            <HandoffInline
              key={h.request_id}
              handoff={h}
              onResolve={onResolveHandoff}
            />
          ))}

          {/* Running indicator */}
          {isRunning && (
            <div className="flex items-center gap-2 py-2">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-cyan animate-glow" />
              <span className="cursor-blink font-mono text-xs text-dim">
                Executing
              </span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-edge bg-slab/80 px-4 py-3 backdrop-blur-sm">
        <div className="mx-auto max-w-2xl">
          {/* URL input (pre-session) */}
          {!sessionId && (
            <div className="mb-2">
              <input
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="Starting URL (optional, e.g. https://example.com)"
                className="w-full rounded-lg border border-edge bg-plate px-3 py-2 font-mono text-xs text-text placeholder:text-muted focus:border-cyan/40 focus:outline-none"
              />
            </div>
          )}

          {/* Attachment preview */}
          {attachments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2" data-testid="attachment-preview">
              {attachments.map((att, i) => (
                <div
                  key={`${att.filename}-${i}`}
                  className="group relative flex items-center gap-1.5 rounded-lg border border-edge bg-plate px-2 py-1"
                >
                  {att.mimeType.startsWith("image/") ? (
                    <img
                      src={att.dataUrl}
                      alt={att.filename}
                      className="h-8 w-8 rounded object-cover"
                    />
                  ) : (
                    <span className="flex h-8 w-8 items-center justify-center rounded bg-slab text-xs text-muted">
                      F
                    </span>
                  )}
                  <span className="max-w-[100px] truncate font-mono text-[10px] text-dim">
                    {att.filename}
                  </span>
                  <button
                    onClick={() => removeAttachment(i)}
                    className="ml-1 text-xs text-muted hover:text-rose"
                    aria-label={`Remove ${att.filename}`}
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                handleFiles(e.target.files);
                e.target.value = "";
              }}
              data-testid="file-input"
            />

            {/* Clip button */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isRunning || attachments.length >= MAX_FILES}
              className="flex items-center justify-center rounded-xl border border-edge bg-plate px-3 py-3 text-muted transition-all hover:border-cyan/40 hover:text-cyan disabled:opacity-30"
              title="Attach files"
              aria-label="Attach files"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 8.5l-5.5 5.5a3.5 3.5 0 01-5-5l6.5-6.5a2.5 2.5 0 013.5 3.5L7 12.5a1.5 1.5 0 01-2-2L10.5 5" />
              </svg>
            </button>

            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder={
                sessionId
                  ? isRunning
                    ? "Running..."
                    : 'Type your automation intent...'
                  : "Type your first intent to start a session..."
              }
              disabled={isRunning}
              className="flex-1 rounded-xl border border-edge bg-plate px-4 py-3 text-sm text-text placeholder:text-muted focus:border-cyan/40 focus:outline-none disabled:opacity-50"
              autoFocus
            />
            <button
              onClick={handleSubmit}
              disabled={!input.trim() || isRunning}
              className="rounded-xl border border-cyan/30 bg-cyan/8 px-5 py-3 font-mono text-sm font-medium text-cyan transition-all hover:bg-cyan/15 disabled:opacity-30 disabled:hover:bg-cyan/8"
            >
              {sessionId ? "Send" : "Start"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border border-edge bg-plate">
        <span className="font-mono text-2xl text-cyan/60">&gt;_</span>
      </div>
      <h2 className="mb-2 font-display text-lg font-semibold text-text">
        Chat Automation
      </h2>
      <p className="max-w-sm text-sm leading-relaxed text-dim">
        Describe what you want to automate in natural language.
        The engine will plan, execute, and report back in real time.
      </p>
      <div className="mt-6 space-y-1">
        {[
          '"Go to Google and search for web automation"',
          '"Find the cheapest laptop on Coupang"',
          '"Log in to my dashboard and export the CSV"',
        ].map((example) => (
          <p
            key={example}
            className="font-mono text-[11px] text-muted/60"
          >
            {example}
          </p>
        ))}
      </div>
    </div>
  );
}
