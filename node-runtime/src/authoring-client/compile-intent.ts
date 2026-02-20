import { z } from 'zod';
import { HttpClient, HttpClientError } from './http-client.js';
import { WorkflowSchema } from '../schemas/workflow.schema.js';
import { ActionsMapSchema } from '../schemas/action.schema.js';
import { SelectorsMapSchema } from '../schemas/selector.schema.js';
import { PoliciesMapSchema } from '../schemas/policy.schema.js';
import { FingerprintsMapSchema } from '../schemas/fingerprint.schema.js';

export interface CompileIntentRequest {
  requestId: string;
  goal: string;
  procedure?: string;
  domain?: string;
  context?: Record<string, unknown>;
}

const CompileIntentResponseSchema = z.object({
  requestId: z.string(),
  workflow: WorkflowSchema,
  actions: ActionsMapSchema,
  selectors: SelectorsMapSchema,
  policies: PoliciesMapSchema,
  fingerprints: FingerprintsMapSchema,
});

export type CompileIntentResponse = z.infer<typeof CompileIntentResponseSchema>;

/**
 * POST /compile-intent wrapper with schema validation on response.
 * Blueprint section 3.2, endpoint #1.
 */
export async function compileIntent(
  client: HttpClient,
  request: CompileIntentRequest,
): Promise<CompileIntentResponse> {
  const response = await client.post<unknown>(
    '/compile-intent',
    {
      requestId: request.requestId,
      goal: request.goal,
      procedure: request.procedure,
      domain: request.domain,
      context: request.context,
    },
    request.requestId,
  );

  const parsed = CompileIntentResponseSchema.safeParse(response.data);
  if (!parsed.success) {
    throw new HttpClientError(
      `Invalid compile-intent response: ${parsed.error.message}`,
      response.status,
      request.requestId,
    );
  }

  return parsed.data;
}
