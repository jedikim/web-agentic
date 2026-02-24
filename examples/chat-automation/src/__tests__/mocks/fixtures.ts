import type {
  SessionInfo,
  TurnResult,
  HandoffRequest,
  ProgressEvent,
  HandoffEvent,
  TurnCompleteEvent,
} from "../../types";

export const mockSessionInfo: SessionInfo = {
  session_id: "sess-abc12345-6789-def0",
  status: "active",
  headless: true,
  created_at: "2026-01-15T10:00:00Z",
};

export const mockTurnResult: TurnResult = {
  turn_id: "turn-001",
  turn_num: 1,
  session_id: "sess-abc12345-6789-def0",
  success: true,
  steps_total: 3,
  steps_ok: 3,
  cost_usd: 0.0042,
  tokens_used: 1200,
  error_msg: null,
  screenshots: ["screenshot-1.png"],
  current_url: "https://example.com/results",
  pending_handoffs: 0,
};

export const mockFailedTurnResult: TurnResult = {
  turn_id: "turn-002",
  turn_num: 2,
  session_id: "sess-abc12345-6789-def0",
  success: false,
  steps_total: 3,
  steps_ok: 1,
  cost_usd: 0.003,
  tokens_used: 800,
  error_msg: "Element not found",
  screenshots: [],
  current_url: "https://example.com",
  pending_handoffs: 0,
};

export const mockHandoffRequest: HandoffRequest = {
  request_id: "handoff-001",
  reason: "CaptchaDetected",
  url: "https://example.com/captcha",
  title: "CAPTCHA Page",
  message: "Please solve the CAPTCHA",
  has_screenshot: true,
  created_at: "2026-01-15T10:05:00Z",
};

export const mockHandoffRequestAction: HandoffRequest = {
  request_id: "handoff-002",
  reason: "LoginRequired",
  url: "https://example.com/login",
  title: "Login Page",
  message: "Manual login required",
  has_screenshot: false,
  created_at: "2026-01-15T10:06:00Z",
};

export const mockProgressEvent: ProgressEvent = {
  session_id: "sess-abc12345-6789-def0",
  event: "step_started",
  step_id: "step-001",
  step_index: 0,
  total_steps: 3,
  method: "L",
  attempt: 1,
  message: "Navigating to page",
};

export const mockHandoffEvent: HandoffEvent = {
  session_id: "sess-abc12345-6789-def0",
  request_id: "handoff-001",
  reason: "CaptchaDetected",
  message: "CAPTCHA detected on page",
  url: "https://example.com/captcha",
};

export const mockTurnCompleteEvent: TurnCompleteEvent = {
  session_id: "sess-abc12345-6789-def0",
  turn_id: "turn-001",
  success: true,
  cost_usd: 0.0042,
};
