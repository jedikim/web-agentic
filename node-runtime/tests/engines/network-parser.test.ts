import { describe, it, expect, vi } from 'vitest';
import { NetworkParser } from '../../src/engines/network-parser.js';
import type { NetworkPage, NetworkResponse } from '../../src/engines/network-parser.js';

function mockPage(): NetworkPage & { triggerResponse: (response: NetworkResponse) => void } {
  const handlers: Array<(response: NetworkResponse) => void> = [];
  return {
    on: vi.fn((event: string, handler: (response: NetworkResponse) => void) => {
      if (event === 'response') handlers.push(handler);
    }),
    off: vi.fn((event: string, handler: (response: NetworkResponse) => void) => {
      const idx = handlers.indexOf(handler);
      if (idx >= 0) handlers.splice(idx, 1);
    }),
    triggerResponse(response: NetworkResponse) {
      for (const h of handlers) h(response);
    },
  };
}

function mockResponse(overrides: {
  url: string;
  method?: string;
  status?: number;
  contentType?: string;
  body?: string;
}): NetworkResponse {
  return {
    url: () => overrides.url,
    request: () => ({ method: () => overrides.method ?? 'GET' }),
    status: () => overrides.status ?? 200,
    headers: () => ({ 'content-type': overrides.contentType ?? 'application/json' }),
    text: () => Promise.resolve(overrides.body ?? '{}'),
  };
}

describe('NetworkParser', () => {
  it('captures matching responses by string pattern', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api/data');
    page.triggerResponse(
      mockResponse({ url: 'https://example.com/api/data?page=1', body: '{"items":[1,2,3]}' }),
    );

    // Wait for async text() processing
    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured).toHaveLength(1);
    expect(captured[0].url).toBe('https://example.com/api/data?page=1');
    expect(captured[0].body).toEqual({ items: [1, 2, 3] });
  });

  it('captures matching responses by RegExp pattern', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, /\/api\/v\d+\/items/);
    page.triggerResponse(
      mockResponse({ url: 'https://example.com/api/v2/items', body: '{"count": 5}' }),
    );

    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured).toHaveLength(1);
    expect(captured[0].body).toEqual({ count: 5 });
  });

  it('ignores non-matching responses', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api/data');
    page.triggerResponse(
      mockResponse({ url: 'https://example.com/other/endpoint', body: '{"ignored":true}' }),
    );

    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured).toHaveLength(0);
  });

  it('parses JSON responses automatically', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api');
    page.triggerResponse(
      mockResponse({
        url: 'https://example.com/api',
        contentType: 'application/json',
        body: '{"name":"test","value":42}',
      }),
    );

    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured[0].body).toEqual({ name: 'test', value: 42 });
  });

  it('keeps non-JSON responses as text', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/page');
    page.triggerResponse(
      mockResponse({
        url: 'https://example.com/page',
        contentType: 'text/html',
        body: '<html>Hello</html>',
      }),
    );

    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured[0].body).toBe('<html>Hello</html>');
  });

  it('auto-detects JSON when content-type is not application/json', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api');
    page.triggerResponse(
      mockResponse({
        url: 'https://example.com/api',
        contentType: 'text/plain',
        body: '{"auto": "detected"}',
      }),
    );

    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured[0].body).toEqual({ auto: 'detected' });
  });

  it('stops capturing after stopCapture', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api');
    parser.stopCapture();

    expect(page.off).toHaveBeenCalled();
  });

  it('clears captured data on new startCapture', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api');
    page.triggerResponse(
      mockResponse({ url: 'https://example.com/api', body: '{"first":true}' }),
    );
    await new Promise((r) => setTimeout(r, 10));
    expect(parser.getCaptured()).toHaveLength(1);

    // Start new capture — clears old data
    parser.startCapture(page, '/api');
    expect(parser.getCaptured()).toHaveLength(0);
  });

  it('captures request method and status', async () => {
    const page = mockPage();
    const parser = new NetworkParser();

    parser.startCapture(page, '/api');
    page.triggerResponse(
      mockResponse({
        url: 'https://example.com/api',
        method: 'POST',
        status: 201,
        body: '{"created":true}',
      }),
    );

    await new Promise((r) => setTimeout(r, 10));

    const captured = parser.getCaptured();
    expect(captured[0].method).toBe('POST');
    expect(captured[0].status).toBe(201);
  });

  describe('extractData', () => {
    it('extracts data matching schema keys from responses', () => {
      const parser = new NetworkParser();
      const responses = [
        {
          url: 'https://example.com/api',
          method: 'GET',
          status: 200,
          contentType: 'application/json',
          body: { name: 'Product', price: 99, inStock: true },
        },
      ];

      const result = parser.extractData(responses, { name: 'string', price: 'number' });
      expect(result).toEqual({ name: 'Product', price: 99, inStock: true });
    });

    it('searches nested objects for matching schema', () => {
      const parser = new NetworkParser();
      const responses = [
        {
          url: 'https://example.com/api',
          method: 'GET',
          status: 200,
          contentType: 'application/json',
          body: {
            data: {
              results: { title: 'Found', count: 3 },
            },
          },
        },
      ];

      const result = parser.extractData(responses, { title: 'string', count: 'number' });
      expect(result).toEqual({ title: 'Found', count: 3 });
    });

    it('searches arrays for matching objects', () => {
      const parser = new NetworkParser();
      const responses = [
        {
          url: 'https://example.com/api',
          method: 'GET',
          status: 200,
          contentType: 'application/json',
          body: [
            { id: 1, foo: 'bar' },
            { id: 2, name: 'match', value: 42 },
          ],
        },
      ];

      const result = parser.extractData(responses, { name: 'string', value: 'number' });
      expect(result).toEqual({ id: 2, name: 'match', value: 42 });
    });

    it('returns null when no match found', () => {
      const parser = new NetworkParser();
      const responses = [
        {
          url: 'https://example.com/api',
          method: 'GET',
          status: 200,
          contentType: 'application/json',
          body: { unrelated: true },
        },
      ];

      const result = parser.extractData(responses, { name: 'string', price: 'number' });
      expect(result).toBeNull();
    });

    it('returns null for empty schema', () => {
      const parser = new NetworkParser();
      const result = parser.extractData([], {});
      expect(result).toBeNull();
    });
  });
});
