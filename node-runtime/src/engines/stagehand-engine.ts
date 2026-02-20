import type { ActionRef } from '../types/index.js';
import type { BrowserEngine } from './browser-engine.js';

export interface StagehandPage {
  goto(url: string): Promise<void>;
  act(action: { action: string } | ActionRef): Promise<{ success: boolean }>;
  observe(options?: { instruction?: string; selector?: string }): Promise<ActionRef[]>;
  extract(options: { instruction?: string; schema?: unknown; selector?: string }): Promise<unknown>;
  screenshot(options?: { selector?: string }): Promise<Buffer>;
  url(): string;
  title(): Promise<string>;
}

export class StagehandEngine implements BrowserEngine {
  constructor(private page: StagehandPage) {}

  async goto(url: string): Promise<void> {
    await this.page.goto(url);
  }

  async act(action: ActionRef): Promise<boolean> {
    const result = await this.page.act(action);
    return result.success;
  }

  async observe(instruction: string, scope?: string): Promise<ActionRef[]> {
    return this.page.observe({
      instruction,
      ...(scope ? { selector: scope } : {}),
    });
  }

  async extract<T>(schema: unknown, scope?: string): Promise<T> {
    const result = await this.page.extract({
      schema,
      ...(scope ? { selector: scope } : {}),
    });
    return result as T;
  }

  async screenshot(selector?: string): Promise<Buffer> {
    return this.page.screenshot(selector ? { selector } : undefined);
  }

  async currentUrl(): Promise<string> {
    return this.page.url();
  }

  async currentTitle(): Promise<string> {
    return this.page.title();
  }
}
