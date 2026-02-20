import { z } from 'zod';
import { HttpClient, HttpClientError } from './http-client.js';
import { PatchOpSchema } from '../schemas/patch.schema.js';

export interface PlanPatchRequest {
  requestId: string;
  stepId: string;
  errorType: string;
  url: string;
  title?: string;
  failedSelector?: string;
  failedAction?: Record<string, unknown>;
  domSnippet?: string;
  screenshotBase64?: string;
}

const PlanPatchResponseSchema = z.object({
  requestId: z.string(),
  patch: z.array(PatchOpSchema),
  reason: z.string(),
});

export type PlanPatchResponse = z.infer<typeof PlanPatchResponseSchema>;

/** Default timeout for plan-patch: 8-15s per Blueprint section 3.2 */
const PLAN_PATCH_DEFAULT_TIMEOUT_MS = 12000;

/**
 * POST /plan-patch wrapper with short timeout and schema validation.
 * Blueprint section 3.2, endpoint #2.
 * Timeout is kept short (8-15s); on timeout, Runtime degrades to screenshot checkpoint.
 */
export async function planPatch(
  client: HttpClient,
  request: PlanPatchRequest,
  timeoutMs: number = PLAN_PATCH_DEFAULT_TIMEOUT_MS,
): Promise<PlanPatchResponse> {
  const response = await client.post<unknown>(
    '/plan-patch',
    {
      requestId: request.requestId,
      step_id: request.stepId,
      error_type: request.errorType,
      url: request.url,
      title: request.title,
      failed_selector: request.failedSelector,
      failed_action: request.failedAction,
      dom_snippet: request.domSnippet,
      screenshot_base64: request.screenshotBase64,
    },
    request.requestId,
    timeoutMs,
  );

  const parsed = PlanPatchResponseSchema.safeParse(response.data);
  if (!parsed.success) {
    throw new HttpClientError(
      `Invalid plan-patch response: ${parsed.error.message}`,
      response.status,
      request.requestId,
    );
  }

  return parsed.data;
}
