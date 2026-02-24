import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Attachment,
  ChatMessage,
  HandoffRequest,
  ProgressEvent,
  HandoffEvent,
  TurnCompleteEvent,
} from "./types";
import {
  createSession,
  executeTurn,
  cancelTurn,
  getScreenshot,
  getHandoffs,
  resolveHandoff,
  closeSession,
  subscribeSSE,
} from "./api";
import SessionHeader from "./components/SessionHeader";
import ChatPanel from "./components/ChatPanel";

let msgId = 0;
function nextId(): string {
  return `msg-${++msgId}`;
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [headless, setHeadless] = useState(true);
  const [handoffs, setHandoffs] = useState<HandoffRequest[]>([]);
  const [totalCost, setTotalCost] = useState(0);
  const [turnCount, setTurnCount] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  const sessionRef = useRef<string | null>(null);

  // Keep sessionRef in sync for SSE callbacks
  useEffect(() => {
    sessionRef.current = sessionId;
  }, [sessionId]);

  const addMessage = useCallback(
    (type: ChatMessage["type"], content: string, meta?: Record<string, unknown>) => {
      setMessages((prev) => [
        ...prev,
        { id: nextId(), type, content, timestamp: Date.now(), meta },
      ]);
    },
    [],
  );

  // SSE subscription
  useEffect(() => {
    const es = subscribeSSE({
      onProgress: (data: ProgressEvent) => {
        if (data.session_id !== sessionRef.current) return;
        const label = methodLabel(data.method);
        if (data.event === "step_started") {
          addMessage(
            "step_log",
            `Step ${data.step_index + 1}/${data.total_steps}: ${data.message}`,
            { status: "running", method: label },
          );
        } else if (data.event === "step_completed") {
          addMessage(
            "step_log",
            `Step ${data.step_index + 1}/${data.total_steps}: ${data.message}`,
            { status: "ok", method: label },
          );
        } else if (data.event === "step_failed") {
          addMessage(
            "step_log",
            `Step ${data.step_index + 1}/${data.total_steps}: ${data.message}`,
            { status: "fail", method: label },
          );
        }
      },
      onHandoff: (data: HandoffEvent) => {
        if (data.session_id !== sessionRef.current) return;
        addMessage("handoff", data.message, {
          request_id: data.request_id,
          reason: data.reason,
        });
        // Refresh handoffs list
        if (sessionRef.current) {
          getHandoffs(sessionRef.current).then(setHandoffs).catch(() => {});
        }
      },
      onTurnComplete: (data: TurnCompleteEvent) => {
        if (data.session_id !== sessionRef.current) return;
        if (data.cancelled) {
          addMessage("system", "Turn cancelled.");
        }
        // Screenshot on completion
        if (sessionRef.current) {
          getScreenshot(sessionRef.current)
            .then((url) => addMessage("screenshot", url))
            .catch(() => {});
        }
      },
    });
    esRef.current = es;
    return () => es.close();
  }, [addMessage]);

  // ── Handlers ──────────────────────────────────────

  const handleStartSession = async (url: string, _attachments?: Attachment[]) => {
    try {
      addMessage("system", "Starting session...");
      const info = await createSession(headless, url || undefined);
      setSessionId(info.session_id);
      addMessage(
        "system",
        `Session created: ${info.session_id.slice(0, 8)}... (${headless ? "headless" : "headful"})`,
      );
    } catch (err) {
      addMessage("system", `Failed to create session: ${err}`);
    }
  };

  const handleSend = async (intent: string, attachments?: Attachment[]) => {
    if (!sessionId || isRunning) return;

    addMessage("user", intent, attachments ? { attachments } : undefined);
    setIsRunning(true);

    try {
      const result = await executeTurn(sessionId, intent, attachments);
      setTurnCount((c) => c + 1);
      setTotalCost((c) => c + result.cost_usd);

      const ok = result.steps_ok;
      const total = result.steps_total;
      const costStr = result.cost_usd.toFixed(4);

      if (result.success) {
        addMessage(
          "result",
          `Done: ${ok}/${total} steps, $${costStr}`,
          { success: true },
        );
      } else {
        addMessage(
          "result",
          `Failed: ${ok}/${total} steps. ${result.error_msg || ""} ($${costStr})`,
          { success: false },
        );
      }

      // Check for new handoffs
      const h = await getHandoffs(sessionId);
      setHandoffs(h);
    } catch (err) {
      if (String(err).includes("CancelledError") || String(err).includes("cancelled")) {
        addMessage("system", "Turn was cancelled.");
      } else {
        addMessage("result", `Error: ${err}`, { success: false });
      }
    } finally {
      setIsRunning(false);
    }
  };

  const handleCancel = async () => {
    if (!sessionId) return;
    try {
      await cancelTurn(sessionId);
    } catch {
      // Ignore
    }
  };

  const handleResolveHandoff = async (requestId: string, action: string) => {
    if (!sessionId) return;
    try {
      await resolveHandoff(sessionId, requestId, action);
      addMessage("system", `Handoff resolved: ${action}`);
      setHandoffs((prev) => prev.filter((h) => h.request_id !== requestId));
    } catch (err) {
      addMessage("system", `Handoff resolve failed: ${err}`);
    }
  };

  const handleCloseSession = async () => {
    if (!sessionId) return;
    try {
      await closeSession(sessionId);
      addMessage("system", "Session closed.");
    } catch {
      // Ignore
    }
    setSessionId(null);
    setHandoffs([]);
    setTotalCost(0);
    setTurnCount(0);
  };

  const handleNewSession = () => {
    if (sessionId) {
      closeSession(sessionId).catch(() => {});
    }
    setSessionId(null);
    setMessages([]);
    setHandoffs([]);
    setTotalCost(0);
    setTurnCount(0);
  };

  return (
    <div className="scanline flex h-screen flex-col bg-void">
      <SessionHeader
        sessionId={sessionId}
        headless={headless}
        onToggleHeadless={() => setHeadless((h) => !h)}
        isRunning={isRunning}
        onCancel={handleCancel}
        onClose={handleCloseSession}
        onNewSession={handleNewSession}
        totalCost={totalCost}
        turnCount={turnCount}
      />
      <ChatPanel
        messages={messages}
        sessionId={sessionId}
        isRunning={isRunning}
        handoffs={handoffs}
        onStartSession={handleStartSession}
        onSend={handleSend}
        onResolveHandoff={handleResolveHandoff}
      />
    </div>
  );
}

function methodLabel(method: string): string {
  const map: Record<string, string> = {
    L: "LLM",
    CACHE: "Cache",
    SELECTOR: "Selector",
    GOTO: "Navigate",
    KEY: "Key",
    WAIT: "Wait",
    SCROLL: "Scroll",
    BV: "Vision",
  };
  return map[method] || method || "...";
}
