import type { BrowserEngine } from './browser-engine.js';

export interface ExtractionResult<T> {
  data: T;
  scope?: string;
}

export async function extractWithSchema<T>(
  engine: BrowserEngine,
  schema: unknown,
  scope?: string,
): Promise<ExtractionResult<T>> {
  const data = await engine.extract<T>(schema, scope);
  return { data, scope };
}
