import type { ErrorType, ActionRef } from '../types/index.js';

export type RecoveryAction =
  | 'retry'
  | 'observe_refresh'
  | 'selector_fallback'
  | 'healing_memory'
  | 'authoring_patch'
  | 'checkpoint'
  | 'abort';

export interface FailureContext {
  stepId: string;
  errorType: ErrorType;
  url: string;
  title: string;
  failedSelector?: string;
  failedAction?: ActionRef;
  domSnippet?: string;
  screenshotPath?: string;
}

export interface RecoveryPlan {
  actions: RecoveryAction[];
  context: FailureContext;
}

/**
 * Create a full RecoveryPlan with ordered actions and failure context.
 * Combines error routing with the failure details needed for each recovery method.
 */
export function createRecoveryPlan(
  errorType: ErrorType,
  context: Omit<FailureContext, 'errorType'>,
): RecoveryPlan {
  return {
    actions: routeError(errorType),
    context: {
      ...context,
      errorType,
    },
  };
}

/**
 * Route an ErrorType to an ordered list of RecoveryActions.
 * Follows Blueprint section 7 routing rules and the fallback ladder in section 7.1.
 */
export function routeError(errorType: ErrorType): RecoveryAction[] {
  switch (errorType) {
    case 'TargetNotFound':
      // observe refresh -> selector fallback -> healing memory -> authoring patch -> checkpoint
      return [
        'retry',
        'observe_refresh',
        'selector_fallback',
        'healing_memory',
        'authoring_patch',
        'checkpoint',
      ];

    case 'NotActionable':
      // Element found but not interactive - retry (may become actionable), then escalate
      return [
        'retry',
        'selector_fallback',
        'observe_refresh',
        'healing_memory',
        'authoring_patch',
        'checkpoint',
      ];

    case 'ExpectationFailed':
      // extract re-verify -> expect patch
      return [
        'retry',
        'observe_refresh',
        'authoring_patch',
        'checkpoint',
      ];

    case 'ExtractionEmpty':
      // selector scope re-adjust -> policy check
      return [
        'retry',
        'observe_refresh',
        'selector_fallback',
        'authoring_patch',
        'checkpoint',
      ];

    case 'CanvasDetected':
      // Non-DOM surface: network parse -> CV coordinates -> authoring service (LLM, last resort)
      return [
        'observe_refresh',
        'authoring_patch',
        'checkpoint',
      ];

    case 'CaptchaOr2FA':
      // Human checkpoint forced - no automated recovery
      return ['checkpoint', 'abort'];

    case 'AuthoringServiceTimeout':
      // Authoring service unreachable - screenshot checkpoint forced
      return ['checkpoint', 'abort'];

    default: {
      // Exhaustive check
      const _exhaustive: never = errorType;
      return ['checkpoint', 'abort'];
    }
  }
}
