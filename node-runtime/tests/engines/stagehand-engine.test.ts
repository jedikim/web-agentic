import { describe, it, expect, vi } from 'vitest';
import { StagehandEngine } from '../../src/engines/stagehand-engine.js';
import type { StagehandPage } from '../../src/engines/stagehand-engine.js';
import type { ActionRef } from '../../src/types/index.js';

function mockPage(): StagehandPage {
  return {
    goto: vi.fn().mockResolvedValue(undefined),
    act: vi.fn().mockResolvedValue({ success: true }),
    observe: vi.fn().mockResolvedValue([]),
    extract: vi.fn().mockResolvedValue({}),
    screenshot: vi.fn().mockResolvedValue(Buffer.from('png')),
    url: vi.fn().mockReturnValue('https://example.com'),
    title: vi.fn().mockResolvedValue('Example'),
  };
}

describe('StagehandEngine', () => {
  it('navigates to URL', async () => {
    const page = mockPage();
    const engine = new StagehandEngine(page);

    await engine.goto('https://example.com');
    expect(page.goto).toHaveBeenCalledWith('https://example.com');
  });

  it('executes cached action', async () => {
    const page = mockPage();
    const engine = new StagehandEngine(page);

    const action: ActionRef = {
      selector: '#btn',
      description: 'Click button',
      method: 'click',
    };

    const result = await engine.act(action);
    expect(result).toBe(true);
    expect(page.act).toHaveBeenCalledWith(action);
  });

  it('returns false when action fails', async () => {
    const page = mockPage();
    (page.act as ReturnType<typeof vi.fn>).mockResolvedValue({ success: false });
    const engine = new StagehandEngine(page);

    const action: ActionRef = { selector: '#btn', description: 'Click', method: 'click' };
    const result = await engine.act(action);
    expect(result).toBe(false);
  });

  it('observes with instruction and scope', async () => {
    const page = mockPage();
    const expectedActions: ActionRef[] = [
      { selector: '#login', description: 'Login btn', method: 'click' },
    ];
    (page.observe as ReturnType<typeof vi.fn>).mockResolvedValue(expectedActions);
    const engine = new StagehandEngine(page);

    const result = await engine.observe('find login button', '#header');
    expect(result).toEqual(expectedActions);
    expect(page.observe).toHaveBeenCalledWith({
      instruction: 'find login button',
      selector: '#header',
    });
  });

  it('observes without scope', async () => {
    const page = mockPage();
    const engine = new StagehandEngine(page);

    await engine.observe('find buttons');
    expect(page.observe).toHaveBeenCalledWith({
      instruction: 'find buttons',
    });
  });

  it('extracts data with schema', async () => {
    const page = mockPage();
    (page.extract as ReturnType<typeof vi.fn>).mockResolvedValue({ price: 42 });
    const engine = new StagehandEngine(page);

    const result = await engine.extract<{ price: number }>({ type: 'object' }, '.pricing');
    expect(result).toEqual({ price: 42 });
    expect(page.extract).toHaveBeenCalledWith({
      schema: { type: 'object' },
      selector: '.pricing',
    });
  });

  it('takes screenshot', async () => {
    const page = mockPage();
    const engine = new StagehandEngine(page);

    const result = await engine.screenshot('#content');
    expect(result).toBeInstanceOf(Buffer);
    expect(page.screenshot).toHaveBeenCalledWith({ selector: '#content' });
  });

  it('returns current URL', async () => {
    const page = mockPage();
    const engine = new StagehandEngine(page);

    const url = await engine.currentUrl();
    expect(url).toBe('https://example.com');
  });

  it('returns current title', async () => {
    const page = mockPage();
    const engine = new StagehandEngine(page);

    const title = await engine.currentTitle();
    expect(title).toBe('Example');
  });
});
