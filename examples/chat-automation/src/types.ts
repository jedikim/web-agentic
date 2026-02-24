/** File attachment for multimodal messages. */
export interface Attachment {
  filename: string;
  mimeType: string;
  /** base64 data URL for preview + sending. */
  dataUrl: string;
  size: number;
}

/** Message types in the chat panel. */
export type MessageType =
  | "user"
  | "system"
  | "step_log"
  | "result"
  | "screenshot"
  | "handoff";

export interface ChatMessage {
  id: string;
  type: MessageType;
  content: string;
  timestamp: number;
  /** Extra data depending on type. */
  meta?: Record<string, unknown>;
}

/** SSE progress event from the backend. */
export interface ProgressEvent {
  session_id: string;
  event: string;
  step_id: string;
  step_index: number;
  total_steps: number;
  method: string;
  attempt: number;
  message: string;
}

/** SSE handoff event. */
export interface HandoffEvent {
  session_id: string;
  request_id: string;
  reason: string;
  message: string;
  url: string;
}

/** SSE turn-completed event. */
export interface TurnCompleteEvent {
  session_id: string;
  turn_id: string;
  success: boolean;
  cost_usd?: number;
  cancelled?: boolean;
}

/** API: session creation response. */
export interface SessionInfo {
  session_id: string;
  status: string;
  headless: boolean;
  created_at: string;
}

/** API: turn execution response. */
export interface TurnResult {
  turn_id: string;
  turn_num: number;
  session_id: string;
  success: boolean;
  steps_total: number;
  steps_ok: number;
  cost_usd: number;
  tokens_used: number;
  error_msg?: string | null;
  screenshots: string[];
  current_url?: string | null;
  pending_handoffs: number;
}

/** Handoff request from the API. */
export interface HandoffRequest {
  request_id: string;
  reason: string;
  url: string;
  title: string;
  message: string;
  has_screenshot: boolean;
  created_at: string;
}
