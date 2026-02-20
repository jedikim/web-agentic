import { describe, it, expect, vi } from 'vitest';
import { ObserveRefresher } from '../../src/engines/observe-refresher.js';
import type { BrowserEngine } from '../../src/engines/browser-engine.js';

function mockEngine(overrides: Partial<BrowserEngine> = {}): BrowserEngine {
  return {
    goto: vi.fn().mockResolvedValue(undefined),
    act: vi.fn().mockResolvedValue(true),
    observe: vi.fn().mockResolvedValue([]),
    extract: vi.fn().mockResolvedValue({}),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
    currentUrl: vi.fn().mockResolvedValue('https://example.com'),
    currentTitle: vi.fn().mockResolvedValue('Example'),
    ...overrides,
  };
}

describe('ObserveRefresher', () => {
  it('returns first observed action on success', async () => {
    const action = {
      selector: '#new-btn',
      description: 'New button',
      method: 'click' as const,
    };
    const engine = mockEngine({
      observe: vi.fn().mockResolvedValue([action]),
    });

    const refresher = new ObserveRefresher(engine);
    const result = await refresher.refresh('login.submit', 'find login button');

    expect(result).toEqual(action);
    expect(engine.observe).toHaveBeenCalledWith('find login button', undefined);
  });

  it('returns null when observe returns empty array', async () => {
    const engine = mockEngine({
      observe: vi.fn().mockResolvedValue([]),
    });

    const refresher = new ObserveRefresher(engine);
    const result = await refresher.refresh('login.submit', 'find login button');

    expect(result).toBeNull();
  });

  it('passes scope parameter to engine.observe', async () => {
    const engine = mockEngine({
      observe: vi.fn().mockResolvedValue([]),
    });

    const refresher = new ObserveRefresher(engine);
    await refresher.refresh('nav.menu', 'find menu', '#header');

    expect(engine.observe).toHaveBeenCalledWith('find menu', '#header');
  });

  it('returns first action when multiple candidates found', async () => {
    const first = { selector: '#btn-1', description: 'Button 1', method: 'click' as const };
    const second = { selector: '#btn-2', description: 'Button 2', method: 'click' as const };
    const engine = mockEngine({
      observe: vi.fn().mockResolvedValue([first, second]),
    });

    const refresher = new ObserveRefresher(engine);
    const result = await refresher.refresh('submit', 'find submit');

    expect(result).toEqual(first);
  });

  it('propagates errors from engine.observe', async () => {
    const engine = mockEngine({
      observe: vi.fn().mockRejectedValue(new Error('observe failed')),
    });

    const refresher = new ObserveRefresher(engine);
    await expect(refresher.refresh('key', 'instruction')).rejects.toThrow('observe failed');
  });
});
