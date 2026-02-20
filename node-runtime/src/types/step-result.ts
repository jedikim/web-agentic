export type ErrorType =
  | 'TargetNotFound'
  | 'NotActionable'
  | 'ExpectationFailed'
  | 'ExtractionEmpty'
  | 'CanvasDetected'
  | 'CaptchaOr2FA'
  | 'AuthoringServiceTimeout';

export interface StepResult {
  stepId: string;
  ok: boolean;
  data?: Record<string, unknown>;
  errorType?: ErrorType;
  message?: string;
  durationMs?: number;
}
