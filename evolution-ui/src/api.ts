/** API client wrapper for the Evolution backend. */

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body);
      if (parsed.detail) detail = parsed.detail;
    } catch { /* not JSON, use raw body */ }
    throw new Error(detail);
  }
  return res.json();
}

// ── Evolution ─────────────────────────────────────

export interface EvolutionRun {
  id: string;
  status: string;
  trigger_reason: string;
  branch_name: string | null;
  analysis_summary: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface EvolutionChange {
  id: string;
  file_path: string;
  change_type: string;
  diff_content: string | null;
  description: string;
  created_at: string;
}

export interface EvolutionDetail extends EvolutionRun {
  trigger_data: string;
  base_commit: string | null;
  changes: EvolutionChange[];
}

export interface StatusResponse {
  status: string;
  message: string;
  data: Record<string, unknown>;
}

export const evolution = {
  trigger: (reason = 'manual', scenarioFilter?: string) =>
    fetchJSON<StatusResponse>('/evolution/trigger', {
      method: 'POST',
      body: JSON.stringify({ reason, scenario_filter: scenarioFilter }),
    }),

  list: (limit = 50, status?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set('status', status);
    return fetchJSON<EvolutionRun[]>(`/evolution/?${params}`);
  },

  get: (id: string) => fetchJSON<EvolutionDetail>(`/evolution/${id}`),

  getDiff: (id: string) =>
    fetchJSON<{ run_id: string; branch_name: string; changes: EvolutionChange[] }>(
      `/evolution/${id}/diff`,
    ),

  approve: (id: string, comment?: string) =>
    fetchJSON<StatusResponse>(`/evolution/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ comment }),
    }),

  reject: (id: string, comment?: string) =>
    fetchJSON<StatusResponse>(`/evolution/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ comment }),
    }),
};

// ── Scenarios ─────────────────────────────────────

export interface ScenarioResult {
  id: string;
  scenario_name: string;
  version: string | null;
  overall_success: boolean;
  total_steps_ok: number;
  total_steps_all: number;
  total_cost_usd: number;
  total_tokens: number;
  wall_time_s: number;
  error_summary: string | null;
  created_at: string;
}

export interface ScenarioTrend {
  scenario_name: string;
  total_runs: number;
  successes: number;
  avg_cost: number;
  avg_time: number;
  success_rate: number;
}

export const scenarios = {
  run: (headless = true, maxCost = 0.5, filterName?: string) =>
    fetchJSON<StatusResponse>('/scenarios/run', {
      method: 'POST',
      body: JSON.stringify({
        headless,
        max_cost: maxCost,
        filter_name: filterName,
      }),
    }),

  results: (scenarioName?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (scenarioName) params.set('scenario_name', scenarioName);
    return fetchJSON<ScenarioResult[]>(`/scenarios/results?${params}`);
  },

  trends: () => fetchJSON<ScenarioTrend[]>('/scenarios/trends'),
};

// ── Versions ──────────────────────────────────────

export interface VersionRecord {
  id: string;
  version: string;
  previous_version: string | null;
  evolution_run_id: string | null;
  changelog: string;
  test_results: Record<string, unknown>;
  git_tag: string | null;
  git_commit: string | null;
  created_at: string;
}

export const versions = {
  list: (limit = 50) =>
    fetchJSON<VersionRecord[]>(`/versions/?limit=${limit}`),

  current: () => fetchJSON<{ version: string }>('/versions/current'),

  get: (version: string) => fetchJSON<VersionRecord>(`/versions/${version}`),

  rollback: (targetVersion: string) =>
    fetchJSON<StatusResponse>('/versions/rollback', {
      method: 'POST',
      body: JSON.stringify({ target_version: targetVersion }),
    }),
};

// ── Session types ─────────────────────────────────

export interface CreateSessionResponse {
  session_id: string;
  status: string;
  headless: boolean;
  created_at: string;
}

export interface TurnResult {
  turn_id: string;
  turn_num: number;
  session_id: string;
  success: boolean;
  steps_total: number;
  steps_ok: number;
  cost_usd: number;
  tokens_used: number;
  error_msg: string | null;
  result_summary: string | null;
  screenshots: string[];
  current_url: string | null;
  pending_handoffs: number;
}

export interface Session {
  id: string;
  status: string;
  headless: boolean;
  initial_url: string | null;
  current_url: string | null;
  total_cost_usd: number;
  turn_count: number;
  created_at: string;
  last_activity: string;
}

export interface SessionTurn {
  id: string;
  turn_num: number;
  intent: string;
  success: boolean;
  cost_usd: number;
  tokens_used: number;
  steps_total: number;
  steps_ok: number;
  error_msg: string | null;
  result_summary: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface SessionDetail extends Session {
  total_tokens: number;
  context: Record<string, unknown>;
  closed_at: string | null;
  turns: SessionTurn[];
}

export interface HandoffItem {
  request_id: string;
  reason: string;
  url: string;
  title: string;
  message: string;
  has_screenshot: boolean;
  created_at: string;
}

export interface OneShotResult {
  success: boolean;
  steps_total: number;
  steps_ok: number;
  cost_usd: number;
  tokens_used: number;
  error_msg: string | null;
  result_summary: string | null;
  screenshots: string[];
  final_url: string | null;
}

// ── Session API ──────────────────────────────────

export const sessions = {
  create: (url?: string, headless = true, context: Record<string, unknown> = {}) =>
    fetchJSON<CreateSessionResponse>('/sessions/', {
      method: 'POST',
      body: JSON.stringify({ url, headless, context }),
    }),

  list: (status?: string, limit = 50) => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    params.set('limit', String(limit));
    return fetchJSON<Session[]>(`/sessions/?${params}`);
  },

  get: (id: string) => fetchJSON<SessionDetail>(`/sessions/${id}`),

  turn: (id: string, intent: string) =>
    fetchJSON<TurnResult>(`/sessions/${id}/turn`, {
      method: 'POST',
      body: JSON.stringify({ intent }),
    }),

  screenshot: async (id: string): Promise<Blob> => {
    const res = await fetch(`${BASE}/sessions/${id}/screenshot`);
    if (!res.ok) throw new Error(`Screenshot failed: ${res.status}`);
    return res.blob();
  },

  handoffs: (id: string) => fetchJSON<HandoffItem[]>(`/sessions/${id}/handoffs`),

  resolveHandoff: (
    id: string,
    requestId: string,
    actionTaken: string,
    metadata: Record<string, unknown> = {},
  ) =>
    fetchJSON<StatusResponse>(`/sessions/${id}/handoffs/${requestId}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ action_taken: actionTaken, metadata }),
    }),

  close: (id: string) =>
    fetchJSON<StatusResponse>(`/sessions/${id}`, { method: 'DELETE' }),
};

// ── Automation (one-shot) ────────────────────────

export const automation = {
  run: (intent: string, url?: string, headless = true) =>
    fetchJSON<OneShotResult>('/run', {
      method: 'POST',
      body: JSON.stringify({ intent, url, headless }),
    }),
};

// ── SSE ───────────────────────────────────────────

export type SSEHandler = (event: string, data: unknown) => void;

const SSE_EVENTS = [
  'evolution_status',
  'scenario_progress',
  'version_created',
  'session_created',
  'session_turn_started',
  'session_turn_completed',
  'session_closed',
  'session_expired',
  'handoff_requested',
  'handoff_resolved',
];

export function subscribeSSE(onEvent: SSEHandler): EventSource {
  const es = new EventSource(`${BASE}/progress/stream`);

  for (const evtType of SSE_EVENTS) {
    es.addEventListener(evtType, (e) => {
      try {
        onEvent(evtType, JSON.parse(e.data));
      } catch {
        onEvent(evtType, e.data);
      }
    });
  }

  es.onerror = () => {
    // Auto-reconnect is handled by EventSource
  };

  return es;
}
