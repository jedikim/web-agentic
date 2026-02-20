import type { ErrorType } from '../types/step-result.js';

interface ClassifyContext {
  selector?: string;
  url?: string;
  message?: string;
}

export function classifyError(error: unknown, context: ClassifyContext = {}): ErrorType {
  const message = extractMessage(error);
  const combined = `${message} ${context.message ?? ''}`.toLowerCase();

  if (isCaptchaOr2FA(combined)) {
    return 'CaptchaOr2FA';
  }

  if (isCanvasDetected(combined)) {
    return 'CanvasDetected';
  }

  if (isAuthoringTimeout(error, combined)) {
    return 'AuthoringServiceTimeout';
  }

  if (isTargetNotFound(combined, context.selector)) {
    return 'TargetNotFound';
  }

  if (isNotActionable(combined)) {
    return 'NotActionable';
  }

  if (isExtractionEmpty(combined)) {
    return 'ExtractionEmpty';
  }

  if (isExpectationFailed(combined)) {
    return 'ExpectationFailed';
  }

  // Default: treat unknown errors as TargetNotFound if selector context present,
  // otherwise ExpectationFailed
  return context.selector ? 'TargetNotFound' : 'ExpectationFailed';
}

function extractMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return String(error);
}

function isCaptchaOr2FA(text: string): boolean {
  const patterns = [
    'captcha',
    'recaptcha',
    'hcaptcha',
    'two-factor',
    '2fa',
    'two factor',
    'verification code',
    'mfa',
    'multi-factor',
    'authenticator',
  ];
  return patterns.some((p) => text.includes(p));
}

function isCanvasDetected(text: string): boolean {
  const patterns = [
    'canvas',
    'webgl',
    '<canvas',
    'canvas element',
    'non-dom',
  ];
  return patterns.some((p) => text.includes(p));
}

function isAuthoringTimeout(error: unknown, text: string): boolean {
  if (text.includes('authoring') && (text.includes('timeout') || text.includes('timed out'))) {
    return true;
  }
  if (error instanceof Error && error.name === 'AbortError' && text.includes('authoring')) {
    return true;
  }
  return false;
}

function isTargetNotFound(text: string, selector?: string): boolean {
  const patterns = [
    'timeout',
    'waiting for selector',
    'waiting for locator',
    'no element found',
    'element not found',
    'target not found',
    'could not find',
    'unable to find',
    'locator resolved to',
    'strict mode violation',
  ];
  if (selector && patterns.some((p) => text.includes(p))) {
    return true;
  }
  if (patterns.some((p) => text.includes(p)) && !text.includes('not actionable') && !text.includes('not clickable')) {
    return true;
  }
  return false;
}

function isNotActionable(text: string): boolean {
  const patterns = [
    'not actionable',
    'not clickable',
    'element is not visible',
    'element is not enabled',
    'element is not stable',
    'intercepted',
    'pointer-events: none',
    'disabled',
    'hidden',
  ];
  return patterns.some((p) => text.includes(p));
}

function isExtractionEmpty(text: string): boolean {
  const patterns = [
    'extraction empty',
    'extract returned null',
    'no data extracted',
    'empty extraction',
    'extract failed',
  ];
  return patterns.some((p) => text.includes(p));
}

function isExpectationFailed(text: string): boolean {
  const patterns = [
    'expectation failed',
    'assertion failed',
    'expect',
    'mismatch',
    'unexpected',
    'url does not contain',
    'text not found',
    'selector not visible',
  ];
  return patterns.some((p) => text.includes(p));
}
