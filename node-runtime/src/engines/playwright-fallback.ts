import type { ActionRef, SelectorEntry } from '../types/index.js';
import type { BrowserEngine } from './browser-engine.js';

export interface PlaywrightPage {
  goto(url: string, options?: { waitUntil?: string }): Promise<void>;
  locator(selector: string): PlaywrightLocator;
  getByTestId(testId: string): PlaywrightLocator;
  getByRole(role: string, options?: { name?: string }): PlaywrightLocator;
  screenshot(options?: { selector?: string }): Promise<Buffer>;
  url(): string;
  title(): Promise<string>;
  content(): Promise<string>;
}

export interface PlaywrightLocator {
  click(): Promise<void>;
  fill(value: string): Promise<void>;
  type(text: string, options?: { delay?: number }): Promise<void>;
  press(key: string): Promise<void>;
  isVisible(): Promise<boolean>;
  textContent(): Promise<string | null>;
}

function extractTestId(selector: string): string | null {
  const match = selector.match(/\[data-testid=["']([^"']+)["']\]/);
  return match ? match[1] : null;
}

function extractRole(selector: string): { role: string; name?: string } | null {
  const match = selector.match(/^role=(\w+)\[name=["']([^"']+)["']\]$/);
  if (match) return { role: match[1], name: match[2] };
  const simpleMatch = selector.match(/^role=(\w+)$/);
  if (simpleMatch) return { role: simpleMatch[1] };
  return null;
}

function getLocator(page: PlaywrightPage, selector: string): PlaywrightLocator {
  const testId = extractTestId(selector);
  if (testId) return page.getByTestId(testId);

  const role = extractRole(selector);
  if (role) return page.getByRole(role.role, role.name ? { name: role.name } : undefined);

  return page.locator(selector);
}

async function executeAction(locator: PlaywrightLocator, action: ActionRef): Promise<void> {
  switch (action.method) {
    case 'click':
      await locator.click();
      break;
    case 'fill':
      await locator.fill(action.arguments?.[0] ?? '');
      break;
    case 'type':
      await locator.type(action.arguments?.[0] ?? '');
      break;
    case 'press':
      await locator.press(action.arguments?.[0] ?? 'Enter');
      break;
    default:
      throw new Error(`Unsupported method: ${action.method}`);
  }
}

export class PlaywrightFallbackEngine implements BrowserEngine {
  constructor(private page: PlaywrightPage) {}

  async goto(url: string): Promise<void> {
    await this.page.goto(url, { waitUntil: 'domcontentloaded' });
  }

  async act(action: ActionRef): Promise<boolean> {
    const locator = getLocator(this.page, action.selector);
    await executeAction(locator, action);
    return true;
  }

  async actWithFallback(action: ActionRef, selectorEntry: SelectorEntry): Promise<boolean> {
    // Try primary selector first
    try {
      const locator = getLocator(this.page, selectorEntry.primary);
      await executeAction(locator, action);
      return true;
    } catch {
      // Try fallbacks in order
      for (const fallback of selectorEntry.fallbacks) {
        try {
          const locator = getLocator(this.page, fallback);
          await executeAction(locator, action);
          return true;
        } catch {
          continue;
        }
      }
    }
    return false;
  }

  async observe(_instruction: string, _scope?: string): Promise<ActionRef[]> {
    // Playwright doesn't have observe() capability; return empty
    return [];
  }

  async extract<T>(_schema: unknown, _scope?: string): Promise<T> {
    // Playwright fallback: return page content as raw data
    const content = await this.page.content();
    return content as unknown as T;
  }

  async screenshot(_selector?: string): Promise<Buffer> {
    return this.page.screenshot();
  }

  async currentUrl(): Promise<string> {
    return this.page.url();
  }

  async currentTitle(): Promise<string> {
    return this.page.title();
  }
}
