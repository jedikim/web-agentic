import { describe, it, expect, vi } from 'vitest';
import { extractWithSchema } from '../../src/engines/extractor.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';

function mockEngine(): BrowserEngine {
  return {
    goto: vi.fn(),
    act: vi.fn(),
    observe: vi.fn(),
    extract: vi.fn().mockResolvedValue({ items: [{ name: 'Seat A', price: 50 }] }),
    screenshot: vi.fn(),
    currentUrl: vi.fn(),
    currentTitle: vi.fn(),
  };
}

describe('extractWithSchema', () => {
  it('extracts data using schema and scope', async () => {
    const engine = mockEngine();
    const schema = { type: 'object', properties: { items: { type: 'array' } } };

    const result = await extractWithSchema<{ items: { name: string; price: number }[] }>(
      engine,
      schema,
      '.results',
    );

    expect(result.data.items).toHaveLength(1);
    expect(result.data.items[0].name).toBe('Seat A');
    expect(result.scope).toBe('.results');
    expect(engine.extract).toHaveBeenCalledWith(schema, '.results');
  });

  it('extracts without scope', async () => {
    const engine = mockEngine();
    const schema = { type: 'object' };

    const result = await extractWithSchema(engine, schema);
    expect(result.scope).toBeUndefined();
    expect(engine.extract).toHaveBeenCalledWith(schema, undefined);
  });
});
