import type {
  Attachment,
  HandoffRequest,
  SessionInfo,
  TurnResult,
  ProgressEvent,
  HandoffEvent,
  TurnCompleteEvent,
} from "./types";

const BASE = "";

// ── REST helpers ──────────────────────────────────────

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function createSession(
  headless: boolean,
  url?: string,
): Promise<SessionInfo> {
  const res = await fetch(`${BASE}/api/sessions/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ headless, url: url || null }),
  });
  return json<SessionInfo>(res);
}

export async function executeTurn(
  sessionId: string,
  intent: string,
  attachments?: Attachment[],
): Promise<TurnResult> {
  const body: Record<string, unknown> = { intent };
  if (attachments && attachments.length > 0) {
    body.attachments = attachments.map((a) => ({
      filename: a.filename,
      mime_type: a.mimeType,
      // Strip "data:<mime>;base64," prefix to send pure base64
      base64_data: a.dataUrl.replace(/^data:[^;]+;base64,/, ""),
    }));
  }
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return json<TurnResult>(res);
}

export async function cancelTurn(
  sessionId: string,
): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/cancel`, {
    method: "POST",
  });
  return json(res);
}

export async function getScreenshot(sessionId: string): Promise<string> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/screenshot`);
  if (!res.ok) throw new Error("Screenshot failed");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export async function getHandoffs(
  sessionId: string,
): Promise<HandoffRequest[]> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/handoffs`);
  return json<HandoffRequest[]>(res);
}

export async function resolveHandoff(
  sessionId: string,
  requestId: string,
  actionTaken: string,
): Promise<void> {
  const res = await fetch(
    `${BASE}/api/sessions/${sessionId}/handoffs/${requestId}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_taken: actionTaken }),
    },
  );
  if (!res.ok) throw new Error("Resolve handoff failed");
}

export async function closeSession(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Close session failed");
}

// ── SSE subscription ──────────────────────────────────

export function subscribeSSE(callbacks: {
  onProgress: (data: ProgressEvent) => void;
  onHandoff: (data: HandoffEvent) => void;
  onTurnComplete: (data: TurnCompleteEvent) => void;
}): EventSource {
  const es = new EventSource(`${BASE}/api/progress/stream`);

  es.addEventListener("session_progress", (e) => {
    callbacks.onProgress(JSON.parse(e.data));
  });

  es.addEventListener("handoff_requested", (e) => {
    callbacks.onHandoff(JSON.parse(e.data));
  });

  es.addEventListener("session_turn_completed", (e) => {
    callbacks.onTurnComplete(JSON.parse(e.data));
  });

  es.onerror = () => {
    // EventSource auto-reconnects; nothing extra needed.
  };

  return es;
}
