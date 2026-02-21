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
