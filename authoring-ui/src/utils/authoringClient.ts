const DEFAULT_BASE_URL = 'http://127.0.0.1:8321';

function getBaseUrl(): string {
  if (typeof window !== 'undefined' && (window as Record<string, unknown>).__AUTHORING_URL__) {
    return (window as Record<string, unknown>).__AUTHORING_URL__ as string;
  }
  return DEFAULT_BASE_URL;
}

export interface CompileIntentRequest {
  requestId: string;
  goal: string;
  procedure?: string;
  domain?: string;
  context?: Record<string, unknown>;
  history?: Array<{ role: string; content: string }>;
}

export interface CompileIntentResponse {
  requestId: string;
  workflow: {
    id: string;
    version?: string | null;
    vars?: Record<string, unknown> | null;
    steps: Array<{
      id: string;
      op: string;
      targetKey?: string | null;
      args?: Record<string, unknown> | null;
      expect?: Array<{ kind: string; value: string }> | null;
      onFail?: string | null;
    }>;
  };
  actions: Record<string, unknown>;
  selectors: Record<string, unknown>;
  policies: Record<string, unknown>;
  fingerprints: Record<string, unknown>;
}

export async function compileIntent(req: CompileIntentRequest): Promise<CompileIntentResponse> {
  const res = await fetch(`${getBaseUrl()}/compile-intent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Authoring service error (${res.status}): ${text}`);
  }
  return res.json();
}

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${getBaseUrl()}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

export interface LlmSettings {
  model: string | null;
  provider: string | null;
  isConfigured: boolean;
  openaiKeySet: boolean;
  geminiKeySet: boolean;
  openaiKeyMasked: string | null;
  geminiKeyMasked: string | null;
}

export interface LlmSettingsRequest {
  model?: string;
  openai_api_key?: string;
  gemini_api_key?: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  description: string;
}

export interface AvailableModels {
  [provider: string]: {
    models: ModelInfo[];
    available: boolean;
  };
}

export async function getLlmSettings(): Promise<LlmSettings> {
  const res = await fetch(`${getBaseUrl()}/llm-settings`);
  if (!res.ok) throw new Error('Failed to get LLM settings');
  return res.json();
}

export async function setLlmSettings(req: LlmSettingsRequest): Promise<LlmSettings> {
  const res = await fetch(`${getBaseUrl()}/llm-settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to save LLM settings: ${text}`);
  }
  return res.json();
}

export async function getAvailableModels(): Promise<AvailableModels> {
  const res = await fetch(`${getBaseUrl()}/llm-settings/models`);
  if (!res.ok) throw new Error('Failed to get available models');
  return res.json();
}

// ── Run Recipe ───────────────────────────────────

export interface StartRunResponse {
  runId: string;
}

export async function startRunRecipe(
  recipe: Record<string, unknown>,
  options?: Record<string, unknown>,
): Promise<StartRunResponse> {
  const res = await fetch(`${getBaseUrl()}/run-recipe/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recipe, options }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to start run: ${text}`);
  }
  return res.json();
}

export function createRunEventSource(runId: string): EventSource {
  return new EventSource(`${getBaseUrl()}/run-recipe/stream/${runId}`);
}

export async function cancelRun(runId: string): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/run-recipe/cancel/${runId}`, {
    method: 'POST',
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to cancel run: ${text}`);
  }
}
