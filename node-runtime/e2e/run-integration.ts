/**
 * Integration test: Node runtime <-> Python authoring service
 *
 * Validates real HTTP communication between the Node authoring client
 * and the Python FastAPI authoring service (no mocks).
 *
 * Usage: npx tsx e2e/run-integration.ts
 */

import { HttpClient, HttpClientError } from '../src/authoring-client/http-client.js';
import { compileIntent } from '../src/authoring-client/compile-intent.js';
import { planPatch } from '../src/authoring-client/plan-patch.js';
import { getProfile } from '../src/authoring-client/profiles.js';

import { WorkflowSchema } from '../src/schemas/workflow.schema.js';
import { ActionsMapSchema } from '../src/schemas/action.schema.js';
import { SelectorsMapSchema } from '../src/schemas/selector.schema.js';
import { PoliciesMapSchema } from '../src/schemas/policy.schema.js';
import { FingerprintsMapSchema } from '../src/schemas/fingerprint.schema.js';
import { PatchPayloadSchema } from '../src/schemas/patch.schema.js';

const BASE_URL = process.env.AUTHORING_URL ?? 'http://127.0.0.1:8321';

let passed = 0;
let failed = 0;
const failures: string[] = [];

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTest(name: string, fn: () => Promise<void>): Promise<void> {
  const start = performance.now();
  try {
    await fn();
    const elapsed = (performance.now() - start).toFixed(0);
    console.log(`  PASS  ${name} (${elapsed}ms)`);
    passed++;
  } catch (err) {
    const elapsed = (performance.now() - start).toFixed(0);
    const msg = err instanceof Error ? err.message : String(err);
    console.log(`  FAIL  ${name} (${elapsed}ms)`);
    console.log(`        ${msg}`);
    failed++;
    failures.push(`${name}: ${msg}`);
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

async function main() {
  console.log(`\nIntegration tests: Node <-> Python authoring service`);
  console.log(`Target: ${BASE_URL}\n`);

  const client = new HttpClient({ baseUrl: BASE_URL });

  // ----- Health check -----
  await runTest('GET /health returns ok', async () => {
    const res = await client.get<{ status: string }>('/health', 'health-1');
    assert(res.ok, 'response should be ok');
    assert(res.data.status === 'ok', `expected status "ok", got "${res.data.status}"`);
  });

  // =========================================================================
  // 1. POST /compile-intent
  // =========================================================================
  await runTest('POST /compile-intent — valid request returns recipe', async () => {
    const result = await compileIntent(client, {
      requestId: 'test-ci-1',
      goal: 'Navigate to example.com and extract the heading',
      domain: 'example.com',
    });

    assert(result.requestId === 'test-ci-1', `requestId mismatch: ${result.requestId}`);

    // Validate each piece with Zod schemas independently
    const wf = WorkflowSchema.safeParse(result.workflow);
    assert(wf.success, `workflow validation failed: ${wf.error?.message}`);

    const acts = ActionsMapSchema.safeParse(result.actions);
    assert(acts.success, `actions validation failed: ${acts.error?.message}`);

    const sels = SelectorsMapSchema.safeParse(result.selectors);
    assert(sels.success, `selectors validation failed: ${sels.error?.message}`);

    const pols = PoliciesMapSchema.safeParse(result.policies);
    assert(pols.success, `policies validation failed: ${pols.error?.message}`);

    const fps = FingerprintsMapSchema.safeParse(result.fingerprints);
    assert(fps.success, `fingerprints validation failed: ${fps.error?.message}`);

    // Structural checks
    assert(result.workflow.steps.length >= 1, 'workflow should have at least 1 step');
  });

  await runTest('POST /compile-intent — with procedure generates multiple steps', async () => {
    const result = await compileIntent(client, {
      requestId: 'test-ci-2',
      goal: 'Login and extract dashboard data',
      domain: 'example.com',
      procedure: '1. Go to https://example.com/login\n2. Click the login button\n3. Extract the dashboard title',
    });

    assert(result.requestId === 'test-ci-2', `requestId mismatch: ${result.requestId}`);
    // With a procedure, we should get more than the default single step + checkpoint
    assert(result.workflow.steps.length >= 2, `expected >= 2 steps, got ${result.workflow.steps.length}`);
  });

  // =========================================================================
  // 2. POST /plan-patch
  // =========================================================================
  await runTest('POST /plan-patch — TargetNotFound error returns valid patch', async () => {
    const result = await planPatch(client, {
      requestId: 'test-pp-1',
      stepId: 'login',
      errorType: 'TargetNotFound',
      url: 'https://example.com',
      failedSelector: '#nonexistent',
      domSnippet: '<div><button id="submit">Login</button></div>',
    });

    assert(result.requestId === 'test-pp-1', `requestId mismatch: ${result.requestId}`);
    assert(typeof result.reason === 'string' && result.reason.length > 0, 'reason should be non-empty string');
    assert(Array.isArray(result.patch), 'patch should be an array');

    // Validate the entire response against PatchPayloadSchema
    const parsed = PatchPayloadSchema.safeParse({ patch: result.patch, reason: result.reason });
    assert(parsed.success, `PatchPayloadSchema validation failed: ${parsed.error?.message}`);
  });

  await runTest('POST /plan-patch — Timeout error type', async () => {
    const result = await planPatch(client, {
      requestId: 'test-pp-2',
      stepId: 'load_page',
      errorType: 'Timeout',
      url: 'https://slow-site.example.com',
    });

    assert(result.requestId === 'test-pp-2', `requestId mismatch: ${result.requestId}`);
    assert(Array.isArray(result.patch), 'patch should be an array');
    assert(typeof result.reason === 'string', 'reason should be a string');
  });

  // =========================================================================
  // 3. POST /optimize-profile
  // =========================================================================
  await runTest('POST /optimize-profile — returns queued status', async () => {
    const res = await client.post<{ requestId: string; status: string }>(
      '/optimize-profile',
      { requestId: 'test-op-1', profile_id: 'test-profile' },
      'test-op-1',
    );

    assert(res.ok, 'response should be ok');
    assert(res.data.requestId === 'test-op-1', `requestId mismatch: ${res.data.requestId}`);
    assert(res.data.status === 'queued', `expected status "queued", got "${res.data.status}"`);
  });

  // =========================================================================
  // 4. GET /profiles/:id
  // =========================================================================
  await runTest('GET /profiles/:id — non-existent profile returns 404', async () => {
    try {
      await getProfile(client, 'nonexistent-profile-xyz', 'test-gp-1');
      throw new Error('Expected HttpClientError for 404 but no error was thrown');
    } catch (err) {
      if (err instanceof HttpClientError) {
        assert(err.status === 404, `expected 404, got ${err.status}`);
      } else {
        throw err;
      }
    }
  });

  await runTest('GET /profiles — list profiles', async () => {
    const res = await client.get<{ profiles: string[] }>('/profiles', 'test-lp-1');
    assert(res.ok, 'response should be ok');
    assert(Array.isArray(res.data.profiles), 'profiles should be an array');
  });

  // =========================================================================
  // 5. Error handling tests
  // =========================================================================
  await runTest('POST /compile-intent — missing required field returns 422', async () => {
    try {
      // Send body missing the required 'goal' field
      await client.post('/compile-intent', { requestId: 'test-err-1' }, 'test-err-1');
      throw new Error('Expected HttpClientError for 422 but no error was thrown');
    } catch (err) {
      if (err instanceof HttpClientError) {
        assert(err.status === 422, `expected 422, got ${err.status}`);
      } else {
        throw err;
      }
    }
  });

  await runTest('GET /nonexistent — returns 404', async () => {
    try {
      await client.get('/nonexistent-endpoint', 'test-err-2');
      throw new Error('Expected HttpClientError for 404 but no error was thrown');
    } catch (err) {
      if (err instanceof HttpClientError) {
        assert(err.status === 404, `expected 404, got ${err.status}`);
      } else {
        throw err;
      }
    }
  });

  await runTest('POST /plan-patch — missing required fields returns 422', async () => {
    try {
      await client.post('/plan-patch', { requestId: 'test-err-3' }, 'test-err-3');
      throw new Error('Expected HttpClientError for 422 but no error was thrown');
    } catch (err) {
      if (err instanceof HttpClientError) {
        assert(err.status === 422, `expected 422, got ${err.status}`);
      } else {
        throw err;
      }
    }
  });

  await runTest('POST /compile-intent — timeout handling (short timeout)', async () => {
    const shortClient = new HttpClient({ baseUrl: BASE_URL, defaultTimeoutMs: 1 });
    try {
      await compileIntent(shortClient, {
        requestId: 'test-timeout-1',
        goal: 'Navigate to example.com',
        domain: 'example.com',
      });
      // It's possible the server responds in <1ms on localhost,
      // so we don't fail if no error. Just verify it didn't crash.
    } catch (err) {
      if (err instanceof HttpClientError) {
        assert(err.status === 0, `timeout error should have status 0, got ${err.status}`);
      } else {
        throw err;
      }
    }
  });

  // =========================================================================
  // 6. Schema validation roundtrip
  // =========================================================================
  await runTest('Schema roundtrip: compile-intent response validates with all Zod schemas', async () => {
    const result = await compileIntent(client, {
      requestId: 'test-roundtrip-1',
      goal: 'Click login, type credentials, submit form',
      domain: 'example.com',
      procedure: '1. Navigate to https://example.com\n2. Click login button\n3. Type username\n4. Submit form',
    });

    // Full Zod re-validation (already done by compileIntent internally, but verify independently)
    const wfResult = WorkflowSchema.parse(result.workflow);
    assert(wfResult.steps.length >= 1, 'parsed workflow needs at least 1 step');

    const actsResult = ActionsMapSchema.parse(result.actions);
    assert(typeof actsResult === 'object', 'parsed actions should be an object');

    const selsResult = SelectorsMapSchema.parse(result.selectors);
    assert(typeof selsResult === 'object', 'parsed selectors should be an object');

    // Verify the workflow steps have expected structure
    for (const step of wfResult.steps) {
      assert(typeof step.id === 'string' && step.id.length > 0, 'step.id should be non-empty string');
      assert(typeof step.op === 'string' && step.op.length > 0, 'step.op should be non-empty string');
    }
  });

  // =========================================================================
  // Summary
  // =========================================================================
  console.log(`\n${'='.repeat(60)}`);
  console.log(`Results: ${passed} passed, ${failed} failed, ${passed + failed} total`);

  if (failures.length > 0) {
    console.log(`\nFailures:`);
    for (const f of failures) {
      console.log(`  - ${f}`);
    }
  }

  console.log(`${'='.repeat(60)}\n`);

  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(2);
});
