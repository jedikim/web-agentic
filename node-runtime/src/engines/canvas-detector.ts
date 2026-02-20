/**
 * Canvas Detector — detects non-standard surface types in a page.
 * Identifies canvas, iframe, shadow DOM, PDF embeds, and SVG-heavy content.
 * Used to route failures through the canvas recovery chain:
 * network parse -> CV -> LLM (last resort).
 */

export interface SurfaceInfo {
  type: 'standard' | 'canvas' | 'iframe' | 'shadow_dom' | 'pdf_embed';
  element?: string;
  bounds?: { x: number; y: number; width: number; height: number };
}

/**
 * Minimal page interface for canvas detection.
 * Compatible with Playwright's Page API.
 */
export interface DetectorPage {
  evaluate<T>(fn: string | ((...args: unknown[]) => T), ...args: unknown[]): Promise<T>;
}

interface DetectionResult {
  type: SurfaceInfo['type'];
  selector: string;
  bounds: { x: number; y: number; width: number; height: number } | null;
}

/**
 * CanvasDetector inspects the page for non-DOM surfaces
 * that require alternative interaction strategies (network parsing, CV, etc.).
 */
export class CanvasDetector {
  /**
   * Detect the surface type at an optional selector scope.
   * Checks for canvas, iframe, shadow DOM hosts, PDF embeds, and SVG-heavy content.
   * Returns 'standard' if none of the special surfaces are found.
   */
  async detect(page: DetectorPage, selector?: string): Promise<SurfaceInfo> {
    const result = await page.evaluate(
      `(function() {
        var scope = document;
        var selectorArg = ${JSON.stringify(selector ?? null)};
        if (selectorArg) {
          var el = document.querySelector(selectorArg);
          if (el) scope = el;
        }

        function getBounds(el) {
          if (!el || !el.getBoundingClientRect) return null;
          var r = el.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height };
        }

        // Check for canvas elements
        var canvas = scope.querySelector ? scope.querySelector('canvas') : null;
        if (!canvas && scope.tagName === 'CANVAS') canvas = scope;
        if (canvas) {
          return { type: 'canvas', selector: 'canvas', bounds: getBounds(canvas) };
        }

        // Check for iframes
        var iframe = scope.querySelector ? scope.querySelector('iframe') : null;
        if (!iframe && scope.tagName === 'IFRAME') iframe = scope;
        if (iframe) {
          return { type: 'iframe', selector: 'iframe', bounds: getBounds(iframe) };
        }

        // Check for shadow DOM hosts
        var allElements = scope.querySelectorAll ? scope.querySelectorAll('*') : [];
        for (var i = 0; i < allElements.length; i++) {
          if (allElements[i].shadowRoot) {
            var tag = allElements[i].tagName.toLowerCase();
            return { type: 'shadow_dom', selector: tag, bounds: getBounds(allElements[i]) };
          }
        }

        // Check for PDF embeds
        var pdfEmbed = scope.querySelector ? scope.querySelector('embed[type="application/pdf"], object[type="application/pdf"]') : null;
        if (pdfEmbed) {
          return { type: 'pdf_embed', selector: pdfEmbed.tagName.toLowerCase(), bounds: getBounds(pdfEmbed) };
        }

        // Check for SVG-heavy content (more than 3 SVG elements or a large SVG)
        var svgs = scope.querySelectorAll ? scope.querySelectorAll('svg') : [];
        if (svgs.length > 3) {
          return { type: 'canvas', selector: 'svg', bounds: getBounds(svgs[0]) };
        }
        for (var j = 0; j < svgs.length; j++) {
          var b = getBounds(svgs[j]);
          if (b && b.width > 500 && b.height > 300) {
            return { type: 'canvas', selector: 'svg', bounds: b };
          }
        }

        return { type: 'standard', selector: '', bounds: null };
      })()`
    ) as DetectionResult;

    const info: SurfaceInfo = { type: result.type };
    if (result.selector) {
      info.element = result.selector;
    }
    if (result.bounds) {
      info.bounds = result.bounds;
    }
    return info;
  }
}
