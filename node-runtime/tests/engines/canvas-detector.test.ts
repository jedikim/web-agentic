import { describe, it, expect, vi } from 'vitest';
import { CanvasDetector } from '../../src/engines/canvas-detector.js';
import type { DetectorPage, SurfaceInfo } from '../../src/engines/canvas-detector.js';

function mockPage(evaluateReturn: unknown): DetectorPage {
  return {
    evaluate: vi.fn().mockResolvedValue(evaluateReturn),
  };
}

describe('CanvasDetector', () => {
  it('detects standard surface when no special elements exist', async () => {
    const page = mockPage({ type: 'standard', selector: '', bounds: null });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.type).toBe('standard');
    expect(result.element).toBeUndefined();
    expect(result.bounds).toBeUndefined();
  });

  it('detects canvas element', async () => {
    const page = mockPage({
      type: 'canvas',
      selector: 'canvas',
      bounds: { x: 0, y: 0, width: 800, height: 600 },
    });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.type).toBe('canvas');
    expect(result.element).toBe('canvas');
    expect(result.bounds).toEqual({ x: 0, y: 0, width: 800, height: 600 });
  });

  it('detects iframe element', async () => {
    const page = mockPage({
      type: 'iframe',
      selector: 'iframe',
      bounds: { x: 10, y: 20, width: 400, height: 300 },
    });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.type).toBe('iframe');
    expect(result.element).toBe('iframe');
    expect(result.bounds).toEqual({ x: 10, y: 20, width: 400, height: 300 });
  });

  it('detects shadow DOM host', async () => {
    const page = mockPage({
      type: 'shadow_dom',
      selector: 'my-component',
      bounds: { x: 0, y: 0, width: 200, height: 100 },
    });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.type).toBe('shadow_dom');
    expect(result.element).toBe('my-component');
  });

  it('detects PDF embed', async () => {
    const page = mockPage({
      type: 'pdf_embed',
      selector: 'embed',
      bounds: { x: 0, y: 0, width: 600, height: 800 },
    });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.type).toBe('pdf_embed');
    expect(result.element).toBe('embed');
  });

  it('detects SVG-heavy content as canvas type', async () => {
    const page = mockPage({
      type: 'canvas',
      selector: 'svg',
      bounds: { x: 0, y: 0, width: 800, height: 400 },
    });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.type).toBe('canvas');
    expect(result.element).toBe('svg');
  });

  it('passes selector to evaluate for scoped detection', async () => {
    const page = mockPage({ type: 'standard', selector: '', bounds: null });
    const detector = new CanvasDetector();

    await detector.detect(page, '#my-container');
    expect(page.evaluate).toHaveBeenCalled();
    // Verify the evaluate call includes the selector in the function string
    const callArg = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(callArg).toContain('#my-container');
  });

  it('returns SurfaceInfo without optional fields for standard', async () => {
    const page = mockPage({ type: 'standard', selector: '', bounds: null });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    const keys = Object.keys(result);
    expect(keys).toContain('type');
    expect(keys).not.toContain('element');
    expect(keys).not.toContain('bounds');
  });

  it('includes bounds when present', async () => {
    const bounds = { x: 50, y: 100, width: 300, height: 200 };
    const page = mockPage({
      type: 'canvas',
      selector: 'canvas',
      bounds,
    });
    const detector = new CanvasDetector();

    const result = await detector.detect(page);
    expect(result.bounds).toEqual(bounds);
  });
});
