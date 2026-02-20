import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { HttpClient, HttpClientError } from '../../src/authoring-client/http-client.js';

describe('HttpClient', () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function mockFetch(status: number, body: unknown, ok = true) {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok,
      status,
      statusText: ok ? 'OK' : 'Error',
      json: () => Promise.resolve(body),
    });
  }

  it('sends GET request with correct headers', async () => {
    mockFetch(200, { data: 'test' });
    const client = new HttpClient({ baseUrl: 'http://localhost:8000', apiKey: 'test-key' });

    await client.get('/health', 'req-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/health',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'X-Request-Id': 'req-1',
          'Authorization': 'Bearer test-key',
        }),
      }),
    );
  });

  it('sends POST request with body', async () => {
    mockFetch(200, { result: 'ok' });
    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });
    const body = { goal: 'test', requestId: 'r1' };

    await client.post('/compile-intent', body, 'req-2');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/compile-intent',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(body),
      }),
    );
  });

  it('returns parsed response data', async () => {
    mockFetch(200, { workflow: { id: 'test' } });
    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    const result = await client.get<{ workflow: { id: string } }>('/test', 'req-3');

    expect(result.ok).toBe(true);
    expect(result.status).toBe(200);
    expect(result.data.workflow.id).toBe('test');
    expect(result.requestId).toBe('req-3');
  });

  it('throws HttpClientError on non-ok response', async () => {
    mockFetch(500, { error: 'internal' }, false);
    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    await expect(client.get('/fail', 'req-4')).rejects.toThrow(HttpClientError);
    await expect(client.get('/fail', 'req-5')).rejects.toMatchObject({
      status: 500,
    });
  });

  it('throws on timeout', async () => {
    globalThis.fetch = vi.fn().mockImplementation(() => {
      return new Promise((_, reject) => {
        setTimeout(() => {
          const error = new DOMException('The operation was aborted', 'AbortError');
          reject(error);
        }, 10);
      });
    });

    const client = new HttpClient({ baseUrl: 'http://localhost:8000', defaultTimeoutMs: 5 });

    await expect(client.get('/slow', 'req-6')).rejects.toThrow(HttpClientError);
  });

  it('does not include Authorization header when no apiKey', async () => {
    mockFetch(200, {});
    const client = new HttpClient({ baseUrl: 'http://localhost:8000' });

    await client.get('/test', 'req-7');

    const callArgs = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[1].headers).not.toHaveProperty('Authorization');
  });

  it('strips trailing slash from baseUrl', async () => {
    mockFetch(200, {});
    const client = new HttpClient({ baseUrl: 'http://localhost:8000/' });

    await client.get('/test', 'req-8');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/test',
      expect.anything(),
    );
  });
});
