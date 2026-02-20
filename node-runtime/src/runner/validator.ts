import type { Expectation } from '../types/index.js';
import type { BrowserEngine } from '../engines/browser-engine.js';

export interface ValidationResult {
  ok: boolean;
  failures: { expectation: Expectation; actual?: string }[];
}

async function checkExpectation(
  expectation: Expectation,
  engine: BrowserEngine,
): Promise<{ ok: boolean; actual?: string }> {
  switch (expectation.kind) {
    case 'url_contains': {
      const url = await engine.currentUrl();
      return { ok: url.includes(expectation.value), actual: url };
    }

    case 'title_contains': {
      const title = await engine.currentTitle();
      return { ok: title.includes(expectation.value), actual: title };
    }

    case 'selector_visible': {
      try {
        const screenshot = await engine.screenshot(expectation.value);
        return { ok: screenshot.length > 0 };
      } catch {
        return { ok: false, actual: 'selector not visible' };
      }
    }

    case 'text_contains': {
      try {
        const content = await engine.extract<string>({ type: 'string' }, 'body');
        const text = typeof content === 'string' ? content : JSON.stringify(content);
        return { ok: text.includes(expectation.value), actual: text.slice(0, 200) };
      } catch {
        return { ok: false, actual: 'extraction failed' };
      }
    }

    default:
      return { ok: false, actual: `unknown expectation kind: ${expectation.kind}` };
  }
}

export async function validateExpectations(
  expectations: Expectation[],
  engine: BrowserEngine,
): Promise<ValidationResult> {
  const failures: ValidationResult['failures'] = [];

  for (const expectation of expectations) {
    const result = await checkExpectation(expectation, engine);
    if (!result.ok) {
      failures.push({ expectation, actual: result.actual });
    }
  }

  return { ok: failures.length === 0, failures };
}
