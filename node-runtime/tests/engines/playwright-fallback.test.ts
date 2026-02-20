import { describe, it, expect, vi } from 'vitest';
import { PlaywrightFallbackEngine } from '../../src/engines/playwright-fallback.js';
import type { PlaywrightPage, PlaywrightLocator } from '../../src/engines/playwright-fallback.js';
import type { ActionRef, SelectorEntry } from '../../src/types/index.js';

function mockLocator(overrides: Partial<PlaywrightLocator> = {}): PlaywrightLocator {
  return {
    click: vi.fn().mockResolvedValue(undefined),
    fill: vi.fn().mockResolvedValue(undefined),
    type: vi.fn().mockResolvedValue(undefined),
    press: vi.fn().mockResolvedValue(undefined),
    isVisible: vi.fn().mockResolvedValue(true),
    textContent: vi.fn().mockResolvedValue('text'),
    ...overrides,
  };
}

function mockPage(overrides: Partial<PlaywrightPage> = {}): PlaywrightPage {
  const loc = mockLocator();
  return {
    goto: vi.fn().mockResolvedValue(undefined),
    locator: vi.fn().mockReturnValue(loc),
    getByTestId: vi.fn().mockReturnValue(loc),
    getByRole: vi.fn().mockReturnValue(loc),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
    url: vi.fn().mockReturnValue('https://example.com'),
    title: vi.fn().mockResolvedValue('Example'),
    content: vi.fn().mockResolvedValue('<html></html>'),
    ...overrides,
  };
}

describe('PlaywrightFallbackEngine', () => {
  it('navigates with domcontentloaded wait', async () => {
    const page = mockPage();
    const engine = new PlaywrightFallbackEngine(page);

    await engine.goto('https://example.com');
    expect(page.goto).toHaveBeenCalledWith('https://example.com', { waitUntil: 'domcontentloaded' });
  });

  it('acts using click method', async () => {
    const loc = mockLocator();
    const page = mockPage({ locator: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '#btn', description: 'Button', method: 'click' };
    const result = await engine.act(action);
    expect(result).toBe(true);
    expect(loc.click).toHaveBeenCalled();
  });

  it('acts using fill method', async () => {
    const loc = mockLocator();
    const page = mockPage({ locator: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '#input', description: 'Input', method: 'fill', arguments: ['hello'] };
    await engine.act(action);
    expect(loc.fill).toHaveBeenCalledWith('hello');
  });

  it('acts using type method', async () => {
    const loc = mockLocator();
    const page = mockPage({ locator: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '#input', description: 'Input', method: 'type', arguments: ['world'] };
    await engine.act(action);
    expect(loc.type).toHaveBeenCalledWith('world');
  });

  it('acts using press method', async () => {
    const loc = mockLocator();
    const page = mockPage({ locator: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '#btn', description: 'Button', method: 'press', arguments: ['Enter'] };
    await engine.act(action);
    expect(loc.press).toHaveBeenCalledWith('Enter');
  });

  it('uses getByTestId for data-testid selectors', async () => {
    const loc = mockLocator();
    const page = mockPage({ getByTestId: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '[data-testid="login-btn"]', description: 'Login', method: 'click' };
    await engine.act(action);
    expect(page.getByTestId).toHaveBeenCalledWith('login-btn');
  });

  it('uses getByRole for role selectors', async () => {
    const loc = mockLocator();
    const page = mockPage({ getByRole: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: 'role=button[name="Submit"]', description: 'Submit', method: 'click' };
    await engine.act(action);
    expect(page.getByRole).toHaveBeenCalledWith('button', { name: 'Submit' });
  });

  it('falls back to locator for CSS selectors', async () => {
    const loc = mockLocator();
    const page = mockPage({ locator: vi.fn().mockReturnValue(loc) });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '.btn-primary', description: 'Button', method: 'click' };
    await engine.act(action);
    expect(page.locator).toHaveBeenCalledWith('.btn-primary');
  });

  it('actWithFallback tries primary then fallbacks', async () => {
    const failLoc = mockLocator({ click: vi.fn().mockRejectedValue(new Error('not found')) });
    const successLoc = mockLocator();

    let callCount = 0;
    const page = mockPage({
      getByTestId: vi.fn().mockReturnValue(failLoc),
      locator: vi.fn().mockImplementation(() => {
        callCount++;
        if (callCount === 1) return failLoc;
        return successLoc;
      }),
    });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '[data-testid="btn"]', description: 'Button', method: 'click' };
    const selectorEntry: SelectorEntry = {
      primary: '[data-testid="btn"]',
      fallbacks: ['button.old', 'button.new'],
      strategy: 'testid',
    };

    const result = await engine.actWithFallback(action, selectorEntry);
    expect(result).toBe(true);
  });

  it('actWithFallback returns false when all fail', async () => {
    const failLoc = mockLocator({ click: vi.fn().mockRejectedValue(new Error('not found')) });
    const page = mockPage({
      getByTestId: vi.fn().mockReturnValue(failLoc),
      locator: vi.fn().mockReturnValue(failLoc),
    });
    const engine = new PlaywrightFallbackEngine(page);

    const action: ActionRef = { selector: '[data-testid="btn"]', description: 'Button', method: 'click' };
    const selectorEntry: SelectorEntry = {
      primary: '[data-testid="btn"]',
      fallbacks: ['button.fail'],
      strategy: 'testid',
    };

    const result = await engine.actWithFallback(action, selectorEntry);
    expect(result).toBe(false);
  });

  it('observe returns empty array (no LLM capability)', async () => {
    const page = mockPage();
    const engine = new PlaywrightFallbackEngine(page);
    const result = await engine.observe('find buttons');
    expect(result).toEqual([]);
  });

  it('returns current URL and title', async () => {
    const page = mockPage();
    const engine = new PlaywrightFallbackEngine(page);

    expect(await engine.currentUrl()).toBe('https://example.com');
    expect(await engine.currentTitle()).toBe('Example');
  });
});
