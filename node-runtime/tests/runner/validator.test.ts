import { describe, it, expect, vi } from 'vitest';
import { validateExpectations } from '../../src/runner/validator.js';
import type { Expectation } from '../../src/types/index.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';

function mockEngine(overrides: Partial<BrowserEngine> = {}): BrowserEngine {
  return {
    goto: vi.fn(),
    act: vi.fn(),
    observe: vi.fn(),
    extract: vi.fn().mockResolvedValue('page text content'),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
    currentUrl: vi.fn().mockResolvedValue('https://example.com/dashboard'),
    currentTitle: vi.fn().mockResolvedValue('Dashboard - Example'),
    ...overrides,
  };
}

describe('validateExpectations', () => {
  it('passes when URL contains expected value', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [{ kind: 'url_contains', value: '/dashboard' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(true);
    expect(result.failures).toHaveLength(0);
  });

  it('fails when URL does not contain expected value', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [{ kind: 'url_contains', value: '/settings' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(false);
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0].expectation.kind).toBe('url_contains');
  });

  it('passes when title contains expected value', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [{ kind: 'title_contains', value: 'Dashboard' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(true);
  });

  it('fails when title does not contain expected value', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [{ kind: 'title_contains', value: 'Settings' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(false);
  });

  it('passes when selector is visible (screenshot succeeds)', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [{ kind: 'selector_visible', value: '#main' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(true);
  });

  it('fails when selector is not visible (screenshot throws)', async () => {
    const engine = mockEngine({
      screenshot: vi.fn().mockRejectedValue(new Error('Element not found')),
    });
    const expectations: Expectation[] = [{ kind: 'selector_visible', value: '#missing' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(false);
  });

  it('passes when text contains expected value', async () => {
    const engine = mockEngine({
      extract: vi.fn().mockResolvedValue('Welcome to the dashboard page'),
    });
    const expectations: Expectation[] = [{ kind: 'text_contains', value: 'dashboard' }];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(true);
  });

  it('validates multiple expectations', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [
      { kind: 'url_contains', value: '/dashboard' },
      { kind: 'title_contains', value: 'Dashboard' },
    ];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(true);
  });

  it('returns all failures when multiple expectations fail', async () => {
    const engine = mockEngine();
    const expectations: Expectation[] = [
      { kind: 'url_contains', value: '/missing' },
      { kind: 'title_contains', value: 'Missing' },
    ];

    const result = await validateExpectations(expectations, engine);
    expect(result.ok).toBe(false);
    expect(result.failures).toHaveLength(2);
  });

  it('returns ok for empty expectations', async () => {
    const engine = mockEngine();
    const result = await validateExpectations([], engine);
    expect(result.ok).toBe(true);
  });
});
