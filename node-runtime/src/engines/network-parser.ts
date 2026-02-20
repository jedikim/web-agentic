/**
 * Network Parser — intercepts and parses network responses for structured data.
 * First choice for canvas/non-DOM surfaces: avoids LLM entirely by reading API responses.
 */

export interface ParsedResponse {
  url: string;
  method: string;
  status: number;
  contentType: string;
  body: unknown;
}

/**
 * Minimal page interface for network interception.
 * Compatible with Playwright's Page API.
 */
export interface NetworkPage {
  on(event: 'response', handler: (response: NetworkResponse) => void): void;
  off(event: 'response', handler: (response: NetworkResponse) => void): void;
}

export interface NetworkResponse {
  url(): string;
  request(): { method(): string };
  status(): number;
  headers(): Record<string, string>;
  text(): Promise<string>;
}

/**
 * NetworkParser captures and parses HTTP responses matching a URL pattern.
 * Useful for extracting structured data from XHR/fetch calls behind canvas-rendered UIs.
 */
export class NetworkParser {
  private captured: ParsedResponse[] = [];
  private handler: ((response: NetworkResponse) => void) | null = null;
  private activePage: NetworkPage | null = null;

  /**
   * Start capturing network responses matching the given URL pattern.
   * @param page - The page to intercept responses on
   * @param urlPattern - String substring or RegExp to match response URLs
   */
  startCapture(page: NetworkPage, urlPattern: string | RegExp): void {
    this.stopCapture();
    this.captured = [];
    this.activePage = page;

    this.handler = (response: NetworkResponse) => {
      const url = response.url();
      const matches =
        typeof urlPattern === 'string'
          ? url.includes(urlPattern)
          : urlPattern.test(url);

      if (matches) {
        const contentType =
          response.headers()['content-type'] ?? response.headers()['Content-Type'] ?? '';
        const method = response.request().method();
        const status = response.status();

        response
          .text()
          .then((text) => {
            let body: unknown = text;
            if (contentType.includes('application/json') || this.looksLikeJson(text)) {
              try {
                body = JSON.parse(text);
              } catch {
                // Keep as text
              }
            }
            this.captured.push({ url, method, status, contentType, body });
          })
          .catch(() => {
            // Response body unavailable; skip
          });
      }
    };

    page.on('response', this.handler);
  }

  /**
   * Stop capturing network responses.
   */
  stopCapture(): void {
    if (this.activePage && this.handler) {
      this.activePage.off('response', this.handler);
    }
    this.handler = null;
    this.activePage = null;
  }

  /**
   * Return all captured responses.
   */
  getCaptured(): ParsedResponse[] {
    return [...this.captured];
  }

  /**
   * Extract structured data from captured responses matching an expected schema shape.
   * Looks for JSON responses containing the expected keys.
   *
   * @param responses - Parsed responses to search through
   * @param schema - Object describing the expected shape: keys to look for.
   *                 Each key maps to a type hint string ('string', 'number', 'array', 'object')
   *                 or a nested schema object.
   * @returns The first matching object, or null if none found.
   */
  extractData(
    responses: ParsedResponse[],
    schema: Record<string, string | Record<string, unknown>>,
  ): unknown {
    const expectedKeys = Object.keys(schema);
    if (expectedKeys.length === 0) return null;

    for (const resp of responses) {
      const match = this.findMatchingObject(resp.body, expectedKeys);
      if (match) return match;
    }

    return null;
  }

  private findMatchingObject(
    data: unknown,
    keys: string[],
  ): Record<string, unknown> | null {
    if (data === null || data === undefined) return null;

    if (typeof data === 'object' && !Array.isArray(data)) {
      const obj = data as Record<string, unknown>;
      const hasAllKeys = keys.every((k) => k in obj);
      if (hasAllKeys) return obj;

      // Search nested objects
      for (const val of Object.values(obj)) {
        const found = this.findMatchingObject(val, keys);
        if (found) return found;
      }
    }

    if (Array.isArray(data)) {
      for (const item of data) {
        const found = this.findMatchingObject(item, keys);
        if (found) return found;
      }
    }

    return null;
  }

  private looksLikeJson(text: string): boolean {
    const trimmed = text.trimStart();
    return trimmed.startsWith('{') || trimmed.startsWith('[');
  }
}
