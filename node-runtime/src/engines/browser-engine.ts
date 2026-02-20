import type { ActionRef } from '../types/index.js';

export interface BrowserEngine {
  goto(url: string): Promise<void>;
  act(action: ActionRef): Promise<boolean>;
  observe(instruction: string, scope?: string): Promise<ActionRef[]>;
  extract<T>(schema: unknown, scope?: string): Promise<T>;
  screenshot(selector?: string): Promise<Buffer>;
  currentUrl(): Promise<string>;
  currentTitle(): Promise<string>;
}
