import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { planPatch } from '../../src/authoring-client/plan-patch.js';
import { HttpClient, HttpClientError } from '../../src/authoring-client/http-client.js';

describe('planPatch', () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  const validPatchResponse = {
    requestId: 'req-1',
    patch: [
      {
        op: 'actions.replace',
        key: 'login.submit',
        value: {
          selector: '#new-btn',
          description: 'New login button',
          method: 'click',
        },
      },
    ],
    reason: 'Login button moved to new location',
  };

  it('returns validated patch response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(validPatchResponse),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });
    const result = await planPatch(client, {
      requestId: 'req-1',
      stepId: 'login',
      errorType: 'TargetNotFound',
      url: 'https://example.com/login',
    });

    expect(result.requestId).toBe('req-1');
    expect(result.patch).toHaveLength(1);
    expect(result.patch[0].op).toBe('actions.replace');
    expect(result.reason).toContain('Login button');
  });

  it('throws on invalid patch op', async () => {
    const invalidResponse = {
      requestId: 'req-2',
      patch: [{ op: 'invalid_op', value: {} }],
      reason: 'test',
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(invalidResponse),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    await expect(
      planPatch(client, {
        requestId: 'req-2',
        stepId: 'step1',
        errorType: 'TargetNotFound',
        url: 'https://example.com',
      }),
    ).rejects.toThrow(HttpClientError);
  });

  it('throws on missing reason field', async () => {
    const noReason = {
      requestId: 'req-3',
      patch: [],
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(noReason),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    await expect(
      planPatch(client, {
        requestId: 'req-3',
        stepId: 'step1',
        errorType: 'TargetNotFound',
        url: 'https://example.com',
      }),
    ).rejects.toThrow(HttpClientError);
  });

  it('passes custom timeout', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(validPatchResponse),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });
    await planPatch(
      client,
      {
        requestId: 'req-4',
        stepId: 'step1',
        errorType: 'TargetNotFound',
        url: 'https://example.com',
      },
      8000,
    );

    // Verify the request was made (timeout is handled internally)
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it('handles empty patch array', async () => {
    const emptyPatch = {
      requestId: 'req-5',
      patch: [],
      reason: 'No fix available',
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(emptyPatch),
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });
    const result = await planPatch(client, {
      requestId: 'req-5',
      stepId: 'step1',
      errorType: 'TargetNotFound',
      url: 'https://example.com',
    });

    expect(result.patch).toHaveLength(0);
    expect(result.reason).toBe('No fix available');
  });
});
