import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { compileIntent } from '../../src/authoring-client/compile-intent.js';
import { HttpClient, HttpClientError } from '../../src/authoring-client/http-client.js';

describe('compileIntent', () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  const validResponse = {
    requestId: 'req-1',
    workflow: {
      id: 'test_flow',
      steps: [{ id: 'open', op: 'goto', args: { url: 'https://example.com' } }],
    },
    actions: {},
    selectors: {},
    policies: {},
    fingerprints: {},
  };

  it('returns validated response on success', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(validResponse),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });
    const result = await compileIntent(client, {
      requestId: 'req-1',
      goal: 'Book a flight',
      domain: 'airline.com',
    });

    expect(result.requestId).toBe('req-1');
    expect(result.workflow.id).toBe('test_flow');
    expect(result.workflow.steps).toHaveLength(1);
  });

  it('throws on invalid response schema', async () => {
    const invalidResponse = {
      requestId: 'req-2',
      workflow: { id: 'test', steps: [] }, // empty steps violates min(1)
      actions: {},
      selectors: {},
      policies: {},
      fingerprints: {},
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(invalidResponse),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    await expect(
      compileIntent(client, { requestId: 'req-2', goal: 'test' }),
    ).rejects.toThrow(HttpClientError);
  });

  it('throws on missing workflow field', async () => {
    const noWorkflow = {
      requestId: 'req-3',
      actions: {},
      selectors: {},
      policies: {},
      fingerprints: {},
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(noWorkflow),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    await expect(
      compileIntent(client, { requestId: 'req-3', goal: 'test' }),
    ).rejects.toThrow(HttpClientError);
  });
});
