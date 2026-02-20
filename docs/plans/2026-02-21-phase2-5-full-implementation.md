# Phase 2-5 Full Implementation Plan

> **Execution Strategy:** Round 1 (Phase 2 + Phase 3 parallel) → Round 2 (Phase 4 + Phase 5 parallel)

**Reference:**
- Blueprint: `doc/stagehand_chrome_automation_blueprint.md`
- Phase 1 code: `node-runtime/src/`, `python-authoring-service/app/`
- Phase 1 plan: `docs/plans/2026-02-21-phase1-deterministic-core.md`

---

## Phase 2: Patch-only Recovery

**Goal:** Complete the exception recovery pipeline — observe refresh, healing memory integration, authoring service patch generation, and automatic version-up.

### Task P2-1: Recovery Pipeline (Node)

**Files to create/modify:**
- Create: `node-runtime/src/runner/recovery-pipeline.ts`
- Create: `node-runtime/src/engines/observe-refresher.ts`
- Modify: `node-runtime/src/runner/step-executor.ts` — Wire fallback ladder to real recovery functions
- Modify: `node-runtime/src/exception/router.ts` — Return detailed RecoveryPlan (not just action names)
- Tests: `node-runtime/tests/runner/recovery-pipeline.test.ts`, `tests/engines/observe-refresher.test.ts`

**Recovery Pipeline spec:**

```ts
// recovery-pipeline.ts
export interface RecoveryPlan {
  actions: RecoveryAction[];
  context: FailureContext;
}

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

export class RecoveryPipeline {
  constructor(
    private observeRefresher: ObserveRefresher,
    private healingMemory: HealingMemory,
    private authoringClient: AuthoringClient,
    private budgetGuard: BudgetGuard,
    private checkpointHandler: CheckpointHandler,
  ) {}

  /**
   * Execute recovery actions in order until one succeeds.
   * Returns the recovered ActionRef or null if all fail.
   */
  async recover(plan: RecoveryPlan, recipe: Recipe): Promise<RecoveryResult> {
    for (const action of plan.actions) {
      switch (action) {
        case 'observe_refresh': // call observeRefresher
        case 'selector_fallback': // try selectors.json fallbacks
        case 'healing_memory': // check healing memory
        case 'authoring_patch': // call authoring service
        case 'checkpoint': // screenshot checkpoint
      }
    }
  }
}

export interface RecoveryResult {
  recovered: boolean;
  action?: ActionRef;
  patchApplied?: PatchPayload;
  method: string; // which recovery method succeeded
}
```

**ObserveRefresher spec:**

```ts
// observe-refresher.ts
export class ObserveRefresher {
  constructor(private engine: BrowserEngine) {}

  /**
   * Use observe() to re-discover an action for a target key.
   * Scope the observation to minimize token usage.
   * Update the actions cache on success.
   */
  async refresh(targetKey: string, instruction: string, scope?: string): Promise<ActionRef | null> {
    const actions = await this.engine.observe(instruction, scope);
    return actions.length > 0 ? actions[0] : null;
  }
}
```

### Task P2-2: Patch Application & Version-Up (Node)

**Files to create/modify:**
- Create: `node-runtime/src/runner/patch-workflow.ts`
- Modify: `node-runtime/src/recipe/patch-merger.ts` — Add major/minor classification, safety validation
- Modify: `node-runtime/src/recipe/versioning.ts` — Integrate with patch workflow
- Tests: `node-runtime/tests/runner/patch-workflow.test.ts`

**Patch Workflow spec:**

```ts
// patch-workflow.ts
export type PatchSeverity = 'minor' | 'major';

export class PatchWorkflow {
  constructor(
    private patchMerger: PatchMerger,
    private versioning: Versioning,
    private checkpointHandler: CheckpointHandler,
  ) {}

  /**
   * Classify patch severity:
   * - minor: single selector/action replacement → auto-apply
   * - major: multiple changes, policy update, workflow change → require GO/NOT GO
   */
  classifyPatch(payload: PatchPayload): PatchSeverity {}

  /**
   * Apply patch to recipe, version up, save new version.
   * Major patches require checkpoint approval.
   */
  async applyAndVersionUp(recipe: Recipe, payload: PatchPayload, basePath: string): Promise<Recipe> {
    const severity = this.classifyPatch(payload);
    if (severity === 'major') {
      const approval = await this.checkpointHandler.requestApproval(
        `Major patch: ${payload.reason}. Apply?`
      );
      if (approval === 'NOT_GO') throw new Error('Patch rejected by user');
    }
    const patched = this.patchMerger.applyPatch(recipe, payload);
    const newVersion = await this.versioning.saveNewVersion(basePath, patched);
    return { ...patched, version: newVersion };
  }
}
```

### Task P2-3: Enhanced Patch Generation (Python)

**Files to modify:**
- Modify: `python-authoring-service/app/dspy_programs/patch_planner.py` — Real patch generation logic
- Create: `python-authoring-service/app/services/patch_generator.py` — Core patch generation
- Modify: `python-authoring-service/app/api/plan_patch.py` — Enhanced error handling, timeout awareness
- Tests: `python-authoring-service/tests/test_patch_generator.py`

**Patch Generator spec:**

```python
# patch_generator.py
class PatchGenerator:
    """Generate patches based on failure context and error type."""

    def generate_patch(self, request: PlanPatchRequest) -> PlanPatchResponse:
        """
        Route to specific patch strategy based on error_type:
        - TargetNotFound → generate actions.replace with new selector
        - ExpectationFailed → generate workflow.update_expect
        - ExtractionEmpty → generate selectors.replace with broader scope
        - NotActionable → generate actions.replace with alternative method
        """
        strategy = self._get_strategy(request.error_type)
        patch_ops = strategy.generate(request)
        return PlanPatchResponse(
            requestId=request.request_id,
            patch=patch_ops,
            reason=strategy.explain(request),
        )
```

---

## Phase 3: DSL Authoring Auto-Improve

**Goal:** Replace DSPy stubs with real implementations, add GEPA self-improving optimization loop, and connect the full authoring pipeline.

### Task P3-1: DSPy Programs (Python)

**Files to create/modify:**
- Create: `python-authoring-service/app/dspy_programs/signatures.py` — DSPy signatures
- Modify: `python-authoring-service/app/dspy_programs/intent_to_workflow.py` — Real DSPy program
- Modify: `python-authoring-service/app/dspy_programs/intent_to_policy.py` — Real DSPy program
- Modify: `python-authoring-service/app/dspy_programs/patch_planner.py` — DSPy-powered planner
- Tests: `python-authoring-service/tests/test_dspy_real.py`

**DSPy Signatures:**

```python
# signatures.py
import dspy

class IntentToWorkflowSignature(dspy.Signature):
    """Convert user intent/goal into a structured workflow JSON."""
    goal: str = dspy.InputField(desc="User's automation goal")
    procedure: str = dspy.InputField(desc="Optional step-by-step procedure description")
    domain: str = dspy.InputField(desc="Target website domain")
    context: str = dspy.InputField(desc="Additional context as JSON string")
    workflow_json: str = dspy.OutputField(desc="Valid workflow JSON matching schema")
    actions_json: str = dspy.OutputField(desc="Valid actions JSON matching schema")
    selectors_json: str = dspy.OutputField(desc="Valid selectors JSON matching schema")

class IntentToPolicySignature(dspy.Signature):
    """Convert user constraints into a policy DSL JSON."""
    goal: str = dspy.InputField(desc="User's selection/filtering goal")
    constraints: str = dspy.InputField(desc="Hard constraints as JSON")
    preferences: str = dspy.InputField(desc="Soft preferences for scoring")
    policy_json: str = dspy.OutputField(desc="Valid policy JSON matching schema")

class PatchPlannerSignature(dspy.Signature):
    """Generate a minimal patch to fix a failure."""
    step_id: str = dspy.InputField(desc="Failed step ID")
    error_type: str = dspy.InputField(desc="Error classification")
    url: str = dspy.InputField(desc="Current page URL")
    failed_selector: str = dspy.InputField(desc="Selector that failed")
    dom_snippet: str = dspy.InputField(desc="Relevant DOM around failure")
    patch_json: str = dspy.OutputField(desc="Valid patch JSON with ops and reason")
```

### Task P3-2: GEPA Optimizer & Eval Harness (Python)

**Files to modify:**
- Modify: `python-authoring-service/app/gepa/optimizer.py` — Real GEPA implementation
- Modify: `python-authoring-service/app/gepa/eval_harness.py` — Auto evaluation
- Modify: `python-authoring-service/app/storage/profiles_repo.py` — Real file-based storage
- Modify: `python-authoring-service/app/storage/task_specs_repo.py` — Real file-based storage
- Modify: `python-authoring-service/app/api/optimize_profile.py` — Connect to GEPA
- Modify: `python-authoring-service/app/api/profiles.py` — Load real profiles
- Create: `python-authoring-service/app/gepa/scoring.py` — Scoring functions
- Tests: `python-authoring-service/tests/test_gepa.py`, `tests/test_eval_harness.py`

**GEPA Optimizer spec:**

```python
# optimizer.py
class GEPAOptimizer:
    """Self-improving prompt optimizer using GEPA methodology."""

    def __init__(self, profiles_repo: ProfilesRepo, task_specs_repo: TaskSpecsRepo):
        self.profiles_repo = profiles_repo
        self.task_specs_repo = task_specs_repo

    async def optimize(self, profile_id: str, max_rounds: int = 5) -> OptimizationResult:
        """
        Run GEPA optimization loop:
        1. Load current profile (signatures + instructions + few-shots)
        2. Load task specs bank
        3. Generate candidates using DSPy programs
        4. Evaluate candidates with eval harness
        5. If score < threshold, reflect and improve prompts
        6. Repeat until convergence or max rounds
        7. Save promoted profile if score >= threshold (0.82)
        """

# eval_harness.py
class EvalHarness:
    """Evaluate generated recipes against quality criteria."""

    def evaluate(self, recipe_json: dict, task_spec: dict) -> EvalResult:
        """
        Score = 0.45 * dry_run_success
             + 0.25 * schema_validity
             + 0.20 * replay_determinism
             - 0.10 * normalized_token_cost
        """

# scoring.py
def score_schema_validity(recipe: dict) -> float:
    """Validate all 5 JSON files against Zod-equivalent schemas. Returns 0.0-1.0."""

def score_dry_run_success(workflow: dict) -> float:
    """Check if workflow steps are logically valid. Returns 0.0-1.0."""

def score_replay_determinism(workflow: dict) -> float:
    """Check if workflow avoids non-deterministic patterns. Returns 0.0-1.0."""

def score_token_cost(recipe: dict) -> float:
    """Estimate normalized token cost. Returns 0.0-1.0 (lower is better)."""
```

---

## Phase 4: Special Surface Handling

**Goal:** Handle canvas/non-DOM surfaces with network parse → CV → LLM chain, and add operational metrics/dashboard.

### Task P4-1: Canvas & Non-DOM Engine Chain (Node)

**Files to create:**
- `node-runtime/src/engines/canvas-detector.ts` — Detect canvas/iframe/shadow DOM/non-standard surfaces
- `node-runtime/src/engines/network-parser.ts` — Parse XHR/fetch responses for structured data
- `node-runtime/src/engines/cv-engine.ts` — Screenshot-based coordinate extraction (template matching)
- Modify: `node-runtime/src/exception/router.ts` — Route CanvasDetected through new chain
- Modify: `node-runtime/src/runner/step-executor.ts` — Add canvas chain to fallback ladder
- Tests for each

**Canvas Detector spec:**

```ts
// canvas-detector.ts
export interface SurfaceInfo {
  type: 'standard' | 'canvas' | 'iframe' | 'shadow_dom' | 'pdf_embed';
  element?: string;
  bounds?: { x: number; y: number; width: number; height: number };
}

export class CanvasDetector {
  async detect(page: Page, selector?: string): Promise<SurfaceInfo> {
    // Check for canvas elements, iframes, shadow roots, PDF embeds
    // Return surface type and bounds
  }
}

// network-parser.ts
export class NetworkParser {
  /**
   * Intercept and parse network responses for structured data.
   * First choice for canvas/non-DOM — avoids LLM entirely.
   */
  async captureResponses(page: Page, urlPattern: string | RegExp): Promise<ParsedResponse[]> {}
  async extractData(responses: ParsedResponse[], schema: unknown): Promise<unknown> {}
}

// cv-engine.ts
export class CVEngine {
  /**
   * Use screenshot comparison to find UI elements by visual template.
   * Fallback when DOM queries fail (canvas, complex SVG, etc.)
   */
  async findByTemplate(screenshot: Buffer, template: Buffer): Promise<{x: number, y: number, confidence: number} | null> {}
  async findByText(screenshot: Buffer, text: string): Promise<{x: number, y: number, confidence: number} | null> {}
  async clickAtCoordinate(page: Page, x: number, y: number): Promise<void> {}
}
```

### Task P4-2: Metrics & Dashboard (Node)

**Files to create:**
- `node-runtime/src/metrics/collector.ts` — Collect operational metrics per run
- `node-runtime/src/metrics/aggregator.ts` — Aggregate metrics across runs
- `node-runtime/src/metrics/reporter.ts` — Generate reports (JSON + MD)
- Tests for each

**Metrics spec (Blueprint §12):**

```ts
// collector.ts
export interface RunMetrics {
  runId: string;
  flow: string;
  version: string;
  startedAt: string;
  completedAt: string;
  success: boolean;
  durationMs: number;
  llmCalls: number;
  tokenUsage: { prompt: number; completion: number };
  patchCount: number;
  patchSuccessRate: number;
  healingMemoryHits: number;
  healingMemoryMisses: number;
  checkpointWaitMs: number;
  stepResults: { total: number; passed: number; failed: number; recovered: number };
  fallbackLadderUsage: Record<string, number>; // recovery method -> count
}

export class MetricsCollector {
  startRun(runId: string, flow: string, version: string): void {}
  recordStep(result: StepResult, recoveryMethod?: string): void {}
  recordLlmCall(tokens: { prompt: number; completion: number }): void {}
  recordPatch(success: boolean): void {}
  recordHealingMemory(hit: boolean): void {}
  recordCheckpointWait(waitMs: number): void {}
  finalize(success: boolean): RunMetrics {}
}

// aggregator.ts
export class MetricsAggregator {
  /**
   * Aggregate metrics across runs to compute SLO metrics:
   * - Success rate
   * - Avg LLM calls per run (SLO: <= 0.2 for normal flows)
   * - 2nd run success rate (SLO: >= 95%)
   * - Post-patch recovery rate (SLO: >= 80%)
   */
  aggregate(metrics: RunMetrics[]): AggregateMetrics {}
}

// reporter.ts
export class MetricsReporter {
  generateJSON(aggregate: AggregateMetrics): string {}
  generateMarkdown(aggregate: AggregateMetrics): string {}
}
```

---

## Phase 5: OSS Pattern Hardening

**Goal:** Production-harden auth management, add workflow block registry, strengthen healing memory, and add trace-based regression testing.

### Task P5-1: Auth Profile & Block Registry (Node)

**Files to modify/create:**
- Modify: `node-runtime/src/memory/auth-profile-manager.ts` — Session expiry detection, auto-recovery, multi-profile support
- Create: `node-runtime/src/blocks/block-registry.ts` — Register and look up reusable workflow blocks
- Create: `node-runtime/src/blocks/builtins/navigation.block.ts`
- Create: `node-runtime/src/blocks/builtins/action.block.ts`
- Create: `node-runtime/src/blocks/builtins/extract.block.ts`
- Create: `node-runtime/src/blocks/builtins/validation.block.ts`
- Create: `node-runtime/src/blocks/block-types.ts` — Block type definitions
- Tests for each

**Auth Profile Enhancement spec:**

```ts
// Enhanced auth-profile-manager.ts
export interface AuthProfile {
  id: string;
  domain: string;
  cookies: Cookie[];
  localStorage: Record<string, string>;
  sessionStorage: Record<string, string>;
  createdAt: string;
  expiresAt?: string;
  lastUsedAt: string;
}

export class AuthProfileManager {
  // Existing: load, save, delete, list
  // NEW methods:
  async detectExpiry(page: Page, profile: AuthProfile): Promise<boolean> {}
  async refreshSession(page: Page, profile: AuthProfile, loginFlow: Workflow): Promise<AuthProfile> {}
  async rotateProfile(domain: string): Promise<AuthProfile | null> {}
  getActiveProfile(domain: string): AuthProfile | null {}
}

// block-registry.ts
export interface WorkflowBlock {
  id: string;
  type: 'navigation' | 'action' | 'extract' | 'validation';
  name: string;
  description: string;
  steps: WorkflowStep[];
  parameters: BlockParameter[];
}

export interface BlockParameter {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'selector';
  required: boolean;
  default?: unknown;
}

export class BlockRegistry {
  register(block: WorkflowBlock): void {}
  get(id: string): WorkflowBlock | undefined {}
  getByType(type: string): WorkflowBlock[] {}
  list(): WorkflowBlock[] {}
  expandBlock(blockId: string, params: Record<string, unknown>): WorkflowStep[] {}
}
```

**Builtin blocks:**

```ts
// navigation.block.ts — goto + waitForLoad + fingerprint check
// action.block.ts — act with retry + fallback
// extract.block.ts — extract with schema + scope narrowing
// validation.block.ts — multi-expectation check + screenshot on fail
```

### Task P5-2: Healing Memory Hardening & Trace Regression (Node)

**Files to modify/create:**
- Modify: `node-runtime/src/memory/healing-memory.ts` — Evidence-based healing, confidence scoring, decay
- Modify: `node-runtime/src/logging/trace-bundler.ts` — Full trace.zip packaging
- Create: `node-runtime/src/testing/trace-replayer.ts` — Replay traces for regression
- Create: `node-runtime/src/testing/regression-runner.ts` — Automated regression from trace archives
- Tests for each

**Healing Memory Hardening spec:**

```ts
// Enhanced healing-memory.ts
export interface HealingRecord {
  targetKey: string;
  action: ActionRef;
  url: string;
  domain: string;
  successCount: number;
  failCount: number;
  confidence: number; // successCount / (successCount + failCount)
  lastSuccessAt: string;
  lastFailAt?: string;
  evidence: HealingEvidence;
}

export interface HealingEvidence {
  originalSelector: string;
  healedSelector: string;
  domContext: string; // surrounding DOM snippet at heal time
  pageTitle: string;
  method: string; // how the healing was discovered
}

export class HealingMemory {
  // Enhanced methods:
  async findMatch(targetKey: string, currentUrl: string, minConfidence?: number): Promise<ActionRef | null> {}
  async record(targetKey: string, action: ActionRef, url: string, evidence: HealingEvidence): Promise<void> {}
  async recordFailure(targetKey: string, url: string): Promise<void> {}
  async prune(minConfidence?: number, maxAge?: number): Promise<number> {} // remove low-confidence entries
  async getStats(): Promise<HealingStats> {}
}

// trace-replayer.ts
export class TraceReplayer {
  /**
   * Load a trace bundle and replay steps to verify regression.
   * Compares current execution against saved trace.
   */
  async loadTrace(tracePath: string): Promise<TraceBundle> {}
  async replay(trace: TraceBundle, engine: BrowserEngine): Promise<ReplayResult> {}
}

// regression-runner.ts
export class RegressionRunner {
  /**
   * Run all trace archives in a directory as regression tests.
   * Report pass/fail/diff for each.
   */
  async runAll(tracesDir: string): Promise<RegressionReport> {}
  async runSingle(tracePath: string): Promise<RegressionResult> {}
  generateReport(results: RegressionResult[]): string {}
}
```

---

## Execution Rounds

### Round 1 (Parallel)
- **Phase 2 Team** (2 agents): Node recovery pipeline + Python patch generation
- **Phase 3 Team** (2 agents): DSPy programs + GEPA optimizer

### Round 2 (Parallel)
- **Phase 4 Team** (2 agents): Canvas engine chain + metrics dashboard
- **Phase 5 Team** (2 agents): Auth/blocks + healing/trace regression
