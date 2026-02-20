# Phase 1: Deterministic Core MVP - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Phase 1 of the web-agentic platform: deterministic recipe execution with Stagehand/Playwright engines, fallback ladder recovery, Python authoring service, and GO/NOT GO checkpoint system.

**Architecture:** Node.js TypeScript runtime loads versioned recipes (workflow + DSL JSON files) and executes browser automation deterministically via cached Stagehand actions. Failures escalate through a 6-level fallback ladder. Python FastAPI authoring service generates/patches recipes via HTTP when recovery requires LLM intelligence. All LLM output is patch-only JSON, never code.

**Tech Stack:**
- Node Runtime: TypeScript 5.7, Node 20+, pnpm, Stagehand v3 (`@browserbasehq/stagehand`), Playwright, Zod 3.x, Vitest 3.x
- Python Service: Python 3.11+, uv, FastAPI 0.115+, Pydantic 2.x, DSPy 2.6+, pytest 8.x

---

## Reference

- **Blueprint**: `doc/stagehand_chrome_automation_blueprint.md`
- Types/schemas: Blueprint §5
- API contract: Blueprint §3.2
- Fallback ladder: Blueprint §7.1
- State machine: Blueprint §4
- Budget guard: Blueprint §6.4
- Error types: Blueprint §7

---

## Workstream Dependencies

```
A (Node Foundation) ──→ C (Node Runtime)
                    └──→ D (Node Support)
B (Python Service)  ─── independent
```

- **A and B start simultaneously** (no dependencies)
- **C and D start after A completes** (need types/schemas)

---

## Workstream A: Node Foundation

### Task 1: Node Project Scaffolding

**Files to create:**
- `node-runtime/package.json`
- `node-runtime/tsconfig.json`
- `node-runtime/vitest.config.ts`
- `node-runtime/src/index.ts`
- All directories per project structure

**Step 1: Create directory structure**

```bash
mkdir -p node-runtime/src/{types,schemas,recipe,engines,runner,exception,logging,memory,authoring-client,blocks/builtins}
mkdir -p node-runtime/tests/{schemas,recipe,engines,runner,exception,logging,memory,authoring-client}
```

**Step 2: Create package.json**

```json
{
  "name": "web-agentic-runtime",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "build": "tsc",
    "test": "vitest",
    "test:run": "vitest run",
    "dev": "tsx src/index.ts",
    "lint": "tsc --noEmit"
  },
  "dependencies": {
    "@browserbasehq/stagehand": "^3.0.0",
    "playwright": "^1.50.0",
    "zod": "^3.24.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "tsx": "^4.19.0",
    "typescript": "^5.7.0",
    "vitest": "^3.0.0"
  }
}
```

**Step 3: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "esModuleInterop": true,
    "strict": true,
    "outDir": "dist",
    "rootDir": "src",
    "declaration": true,
    "sourceMap": true,
    "resolveJsonModule": true,
    "skipLibCheck": true
  },
  "include": ["src"],
  "exclude": ["node_modules", "dist"]
}
```

**Step 4: Create vitest.config.ts**

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
});
```

**Step 5: Create src/index.ts entry point**

```ts
export * from './types/index.js';
export * from './schemas/index.js';
```

**Step 6: Install dependencies and verify**

```bash
cd node-runtime && pnpm install && pnpm run lint
```

**Step 7: Commit**

```bash
git add node-runtime/
git commit -m "feat: scaffold node-runtime project with TS + Playwright + Stagehand"
```

---

### Task 2: Core TypeScript Types & Schema Validators

**Files to create:**
- `node-runtime/src/types/*.ts` (10 files)
- `node-runtime/src/schemas/*.ts` (7 files)
- `node-runtime/tests/schemas/*.test.ts`

**Step 1: Create type definitions**

`node-runtime/src/types/workflow.ts`:
```ts
export interface Expectation {
  kind: 'url_contains' | 'selector_visible' | 'text_contains' | 'title_contains';
  value: string;
}

export interface WorkflowStep {
  id: string;
  op: 'goto' | 'act_cached' | 'act_template' | 'extract' | 'choose' | 'checkpoint' | 'wait';
  targetKey?: string;
  args?: Record<string, unknown>;
  expect?: Expectation[];
  onFail?: 'retry' | 'fallback' | 'checkpoint' | 'abort';
}

export interface Workflow {
  id: string;
  version?: string;
  vars?: Record<string, unknown>;
  steps: WorkflowStep[];
}
```

`node-runtime/src/types/action.ts`:
```ts
export interface ActionRef {
  selector: string;
  description: string;
  method: 'click' | 'fill' | 'type' | 'press' | string;
  arguments?: string[];
}

export interface ActionEntry {
  instruction: string;
  preferred: ActionRef;
  observedAt: string;
}

export type ActionsMap = Record<string, ActionEntry>;
```

`node-runtime/src/types/selector.ts`:
```ts
export interface SelectorEntry {
  primary: string;
  fallbacks: string[];
  strategy: 'testid' | 'role' | 'css' | 'xpath';
}

export type SelectorsMap = Record<string, SelectorEntry>;
```

`node-runtime/src/types/policy.ts`:
```ts
export interface PolicyCondition {
  field: string;
  op: '==' | '!=' | '<' | '<=' | '>' | '>=' | 'in' | 'not_in' | 'contains';
  value: unknown;
}

export interface PolicyScoreRule {
  when: PolicyCondition;
  add: number;
}

export interface Policy {
  hard: PolicyCondition[];
  score: PolicyScoreRule[];
  tie_break: string[];
  pick: 'argmax' | 'argmin' | 'first';
}

export type PoliciesMap = Record<string, Policy>;
```

`node-runtime/src/types/fingerprint.ts`:
```ts
export interface Fingerprint {
  mustText?: string[];
  mustSelectors?: string[];
  urlContains?: string;
}

export type FingerprintsMap = Record<string, Fingerprint>;
```

`node-runtime/src/types/step-result.ts`:
```ts
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
```

`node-runtime/src/types/patch.ts`:
```ts
export type PatchOpType =
  | 'actions.replace'
  | 'actions.add'
  | 'selectors.add'
  | 'selectors.replace'
  | 'workflow.update_expect'
  | 'policies.update';

export interface PatchOp {
  op: PatchOpType;
  key?: string;
  step?: string;
  value: unknown;
}

export interface PatchPayload {
  patch: PatchOp[];
  reason: string;
}
```

`node-runtime/src/types/budget.ts`:
```ts
export interface TokenBudget {
  maxLlmCallsPerRun: number;
  maxPromptChars: number;
  maxDomSnippetChars: number;
  maxScreenshotPerFailure: number;
  maxScreenshotPerCheckpoint: number;
  maxAuthoringServiceCallsPerRun: number;
  authoringServiceTimeoutMs: number;
}

export type DowngradeAction = 'trim_dom' | 'drop_history' | 'observe_scope_narrow' | 'require_human_checkpoint';

export interface BudgetConfig {
  budget: TokenBudget;
  downgradeOrder: DowngradeAction[];
}

export interface BudgetUsage {
  llmCalls: number;
  authoringCalls: number;
  promptChars: number;
  screenshots: number;
}
```

`node-runtime/src/types/recipe.ts`:
```ts
import type { Workflow } from './workflow.js';
import type { ActionsMap } from './action.js';
import type { SelectorsMap } from './selector.js';
import type { PoliciesMap } from './policy.js';
import type { FingerprintsMap } from './fingerprint.js';
import type { TokenBudget, BudgetUsage } from './budget.js';

export interface Recipe {
  domain: string;
  flow: string;
  version: string;
  workflow: Workflow;
  actions: ActionsMap;
  selectors: SelectorsMap;
  policies: PoliciesMap;
  fingerprints: FingerprintsMap;
}

export interface RunContext {
  recipe: Recipe;
  vars: Record<string, unknown>;
  budget: TokenBudget;
  usage: BudgetUsage;
  runId: string;
  startedAt: string;
}
```

`node-runtime/src/types/index.ts`:
```ts
export * from './workflow.js';
export * from './action.js';
export * from './selector.js';
export * from './policy.js';
export * from './fingerprint.js';
export * from './step-result.js';
export * from './patch.js';
export * from './budget.js';
export * from './recipe.js';
```

**Step 2: Create Zod schema validators**

`node-runtime/src/schemas/workflow.schema.ts`:
```ts
import { z } from 'zod';

export const ExpectationSchema = z.object({
  kind: z.enum(['url_contains', 'selector_visible', 'text_contains', 'title_contains']),
  value: z.string(),
});

export const WorkflowStepSchema = z.object({
  id: z.string(),
  op: z.enum(['goto', 'act_cached', 'act_template', 'extract', 'choose', 'checkpoint', 'wait']),
  targetKey: z.string().optional(),
  args: z.record(z.unknown()).optional(),
  expect: z.array(ExpectationSchema).optional(),
  onFail: z.enum(['retry', 'fallback', 'checkpoint', 'abort']).optional(),
});

export const WorkflowSchema = z.object({
  id: z.string(),
  version: z.string().optional(),
  vars: z.record(z.unknown()).optional(),
  steps: z.array(WorkflowStepSchema).min(1),
});
```

Create similar Zod schemas for: `action.schema.ts`, `selector.schema.ts`, `policy.schema.ts`, `fingerprint.schema.ts`, `patch.schema.ts`. Each should mirror the corresponding type definition. Include a barrel `schemas/index.ts`.

**Step 3: Write schema validation tests**

`node-runtime/tests/schemas/workflow.schema.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { WorkflowSchema } from '../../src/schemas/workflow.schema.js';

describe('WorkflowSchema', () => {
  it('validates a correct workflow', () => {
    const valid = {
      id: 'booking_flow',
      steps: [
        { id: 'open', op: 'goto', args: { url: 'https://example.com' } },
        { id: 'login', op: 'act_cached', targetKey: 'login.submit', expect: [{ kind: 'url_contains', value: '/dashboard' }] },
      ],
    };
    expect(WorkflowSchema.parse(valid)).toEqual(valid);
  });

  it('rejects workflow with no steps', () => {
    expect(() => WorkflowSchema.parse({ id: 'empty', steps: [] })).toThrow();
  });

  it('rejects invalid op', () => {
    expect(() => WorkflowSchema.parse({ id: 'x', steps: [{ id: 's', op: 'invalid' }] })).toThrow();
  });
});
```

Write similar tests for all schemas. Each test file should cover: valid input, missing required fields, invalid enum values.

**Step 4: Run tests, verify pass**

```bash
cd node-runtime && pnpm test:run
```

**Step 5: Commit**

```bash
git add node-runtime/src/types/ node-runtime/src/schemas/ node-runtime/tests/schemas/
git commit -m "feat: add core TypeScript types and Zod schema validators"
```

---

## Workstream B: Python Authoring Service

### Task 3: Python Project Scaffolding & API Endpoints

**Files to create:**
- `python-authoring-service/pyproject.toml`
- `python-authoring-service/app/main.py`
- `python-authoring-service/app/api/*.py`
- `python-authoring-service/app/schemas/*.py`
- `python-authoring-service/tests/*.py`

**Step 1: Create directory structure**

```bash
mkdir -p python-authoring-service/app/{api,dspy_programs,gepa,storage,schemas}
mkdir -p python-authoring-service/tests
touch python-authoring-service/app/__init__.py
touch python-authoring-service/app/api/__init__.py
touch python-authoring-service/app/dspy_programs/__init__.py
touch python-authoring-service/app/gepa/__init__.py
touch python-authoring-service/app/storage/__init__.py
touch python-authoring-service/app/schemas/__init__.py
```

**Step 2: Create pyproject.toml**

```toml
[project]
name = "web-agentic-authoring"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "pydantic>=2.0.0",
    "dspy>=2.6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.28.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**Step 3: Create Pydantic schemas**

`python-authoring-service/app/schemas/recipe_schema.py`:
```python
from pydantic import BaseModel, Field

class Expectation(BaseModel):
    kind: str  # url_contains | selector_visible | text_contains | title_contains
    value: str

class WorkflowStep(BaseModel):
    id: str
    op: str  # goto | act_cached | act_template | extract | choose | checkpoint | wait
    target_key: str | None = Field(None, alias="targetKey")
    args: dict | None = None
    expect: list[Expectation] | None = None
    on_fail: str | None = Field(None, alias="onFail")

    model_config = {"populate_by_name": True}

class Workflow(BaseModel):
    id: str
    version: str | None = None
    vars: dict | None = None
    steps: list[WorkflowStep]

class ActionRef(BaseModel):
    selector: str
    description: str
    method: str
    arguments: list[str] | None = None

class ActionEntry(BaseModel):
    instruction: str
    preferred: ActionRef
    observed_at: str = Field(alias="observedAt")

    model_config = {"populate_by_name": True}

class PolicyCondition(BaseModel):
    field: str
    op: str
    value: object

class PolicyScoreRule(BaseModel):
    when: PolicyCondition
    add: float

class Policy(BaseModel):
    hard: list[PolicyCondition]
    score: list[PolicyScoreRule]
    tie_break: list[str]
    pick: str  # argmax | argmin | first

class SelectorEntry(BaseModel):
    primary: str
    fallbacks: list[str]
    strategy: str

class Fingerprint(BaseModel):
    must_text: list[str] | None = Field(None, alias="mustText")
    must_selectors: list[str] | None = Field(None, alias="mustSelectors")
    url_contains: str | None = Field(None, alias="urlContains")

    model_config = {"populate_by_name": True}

class CompileIntentRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    goal: str
    procedure: str | None = None
    domain: str | None = None
    context: dict | None = None

    model_config = {"populate_by_name": True}

class CompileIntentResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    workflow: Workflow
    actions: dict[str, ActionEntry]
    selectors: dict[str, SelectorEntry]
    policies: dict[str, Policy]
    fingerprints: dict[str, Fingerprint]

    model_config = {"populate_by_name": True}
```

`python-authoring-service/app/schemas/patch_schema.py`:
```python
from pydantic import BaseModel, Field

class PatchOp(BaseModel):
    op: str  # actions.replace | actions.add | selectors.add | selectors.replace | workflow.update_expect | policies.update
    key: str | None = None
    step: str | None = None
    value: object

class PlanPatchRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    step_id: str
    error_type: str
    url: str
    title: str | None = None
    failed_selector: str | None = None
    failed_action: dict | None = None
    dom_snippet: str | None = None
    screenshot_base64: str | None = None

    model_config = {"populate_by_name": True}

class PlanPatchResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    patch: list[PatchOp]
    reason: str

    model_config = {"populate_by_name": True}
```

**Step 4: Create FastAPI main app and endpoints**

`python-authoring-service/app/main.py`:
```python
from fastapi import FastAPI
from app.api import compile_intent, plan_patch, optimize_profile, profiles

app = FastAPI(title="Web-Agentic Authoring Service", version="0.1.0")

app.include_router(compile_intent.router, prefix="/compile-intent", tags=["compile"])
app.include_router(plan_patch.router, prefix="/plan-patch", tags=["patch"])
app.include_router(optimize_profile.router, prefix="/optimize-profile", tags=["optimize"])
app.include_router(profiles.router, prefix="/profiles", tags=["profiles"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

`python-authoring-service/app/api/compile_intent.py`:
```python
from fastapi import APIRouter, HTTPException
from app.schemas.recipe_schema import CompileIntentRequest, CompileIntentResponse
from app.dspy_programs.intent_to_workflow import compile_intent_to_recipe

router = APIRouter()

@router.post("", response_model=CompileIntentResponse)
async def compile_intent(request: CompileIntentRequest):
    try:
        result = await compile_intent_to_recipe(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

`python-authoring-service/app/api/plan_patch.py`:
```python
from fastapi import APIRouter, HTTPException
from app.schemas.patch_schema import PlanPatchRequest, PlanPatchResponse
from app.dspy_programs.patch_planner import plan_patch_for_failure

router = APIRouter()

@router.post("", response_model=PlanPatchResponse)
async def plan_patch(request: PlanPatchRequest):
    try:
        result = await plan_patch_for_failure(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

`python-authoring-service/app/api/optimize_profile.py` (async queue stub):
```python
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter()

class OptimizeRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    profile_id: str
    task_specs: list[dict] | None = None

    model_config = {"populate_by_name": True}

class OptimizeResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    status: str  # queued

    model_config = {"populate_by_name": True}

@router.post("", response_model=OptimizeResponse)
async def optimize_profile(request: OptimizeRequest, background_tasks: BackgroundTasks):
    # TODO: Queue optimization job
    background_tasks.add_task(lambda: None)  # stub
    return OptimizeResponse(requestId=request.request_id, status="queued")
```

`python-authoring-service/app/api/profiles.py`:
```python
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    # TODO: Load from storage
    raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")
```

**Step 5: Write API tests**

```python
# python-authoring-service/tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_compile_intent_schema_validation(client):
    response = await client.post("/compile-intent", json={})
    assert response.status_code == 422  # validation error
```

**Step 6: Install dependencies and run tests**

```bash
cd python-authoring-service && uv sync --extra dev && uv run pytest
```

**Step 7: Commit**

```bash
git add python-authoring-service/
git commit -m "feat: scaffold python authoring service with FastAPI endpoints"
```

---

### Task 4: DSPy Program Stubs

**Files to create:**
- `python-authoring-service/app/dspy_programs/intent_to_workflow.py`
- `python-authoring-service/app/dspy_programs/intent_to_policy.py`
- `python-authoring-service/app/dspy_programs/patch_planner.py`
- `python-authoring-service/app/storage/profiles_repo.py`
- `python-authoring-service/app/storage/task_specs_repo.py`
- `python-authoring-service/tests/test_dspy_programs.py`

**Step 1: Create IntentToWorkflow stub**

```python
# app/dspy_programs/intent_to_workflow.py
from app.schemas.recipe_schema import CompileIntentRequest, CompileIntentResponse, Workflow, WorkflowStep

async def compile_intent_to_recipe(request: CompileIntentRequest) -> CompileIntentResponse:
    """
    Phase 1 stub: Returns a minimal workflow from the intent.
    Phase 3 will replace with DSPy program + GEPA optimization.
    """
    # Stub: create a minimal goto + checkpoint workflow
    steps = [
        WorkflowStep(id="open", op="goto", args={"url": f"https://{request.domain or 'example.com'}"}),
        WorkflowStep(id="checkpoint_start", op="checkpoint", args={"message": f"Goal: {request.goal}. Proceed?"}),
    ]
    workflow = Workflow(id=f"{request.domain or 'default'}_flow", steps=steps)

    return CompileIntentResponse(
        requestId=request.request_id,
        workflow=workflow,
        actions={},
        selectors={},
        policies={},
        fingerprints={},
    )
```

**Step 2: Create PatchPlanner stub**

```python
# app/dspy_programs/patch_planner.py
from app.schemas.patch_schema import PlanPatchRequest, PlanPatchResponse, PatchOp

async def plan_patch_for_failure(request: PlanPatchRequest) -> PlanPatchResponse:
    """
    Phase 1 stub: Returns empty patch with human review suggestion.
    Phase 2 will implement real patch generation.
    """
    return PlanPatchResponse(
        requestId=request.request_id,
        patch=[],
        reason=f"Stub: manual review needed for {request.error_type} at step {request.step_id}",
    )
```

**Step 3: Create storage stubs**

```python
# app/storage/profiles_repo.py
class ProfilesRepo:
    """Stub storage for authoring profiles."""
    async def get(self, profile_id: str) -> dict | None:
        return None
    async def save(self, profile_id: str, data: dict) -> None:
        pass

# app/storage/task_specs_repo.py
class TaskSpecsRepo:
    """Stub storage for task specification samples."""
    async def get_specs(self) -> list[dict]:
        return []
    async def add_spec(self, spec: dict) -> None:
        pass
```

**Step 4: Write tests, run, commit**

---

## Workstream C: Node Runtime (depends on Workstream A)

### Task 5: Recipe System

**Files to create:**
- `node-runtime/src/recipe/loader.ts` — Load recipe from filesystem
- `node-runtime/src/recipe/template.ts` — Variable interpolation in args/values
- `node-runtime/src/recipe/versioning.ts` — Version management (v001 → v002)
- `node-runtime/src/recipe/patch-merger.ts` — Apply PatchPayload to Recipe
- `node-runtime/tests/recipe/*.test.ts`

**Key patterns:**

```ts
// loader.ts
import { Recipe } from '../types/index.js';
import { WorkflowSchema } from '../schemas/index.js';

export async function loadRecipe(basePath: string, version: string): Promise<Recipe> {
  // Read workflow.json, actions.json, selectors.json, policies.json, fingerprints.json
  // Validate each with Zod schemas
  // Return assembled Recipe
}

// template.ts
export function interpolate(template: string, vars: Record<string, unknown>): string {
  // Replace {{vars.key}} patterns with actual values
  return template.replace(/\{\{vars\.(\w+)\}\}/g, (_, key) => String(vars[key] ?? ''));
}

export function interpolateStep(step: WorkflowStep, vars: Record<string, unknown>): WorkflowStep {
  // Deep interpolate all string values in step.args
}

// versioning.ts
export function nextVersion(current: string): string {
  // v001 -> v002, v099 -> v100
  const num = parseInt(current.slice(1), 10);
  return `v${String(num + 1).padStart(3, '0')}`;
}

export async function saveRecipeVersion(basePath: string, recipe: Recipe): Promise<string> {
  // Save all 5 JSON files to basePath/<domain>/<flow>/<newVersion>/
}

// patch-merger.ts
export function applyPatch(recipe: Recipe, payload: PatchPayload): Recipe {
  // Apply each PatchOp to the recipe, return new recipe (immutable)
  // Supported ops: actions.replace, actions.add, selectors.add, selectors.replace,
  //   workflow.update_expect, policies.update
}
```

**Tests should cover:** loading valid/invalid recipes, variable interpolation, version incrementing, patch application for each op type.

---

### Task 6: Browser Engines

**Files to create:**
- `node-runtime/src/engines/stagehand-engine.ts` — Stagehand observe/act/extract wrapper
- `node-runtime/src/engines/playwright-fallback.ts` — Strict Playwright locator execution
- `node-runtime/src/engines/extractor.ts` — Schema-based data extraction
- `node-runtime/src/engines/policy-engine.ts` — Hard filter + score + tie-break selection
- `node-runtime/tests/engines/*.test.ts`

**Key interfaces:**

```ts
// Common engine interface
export interface BrowserEngine {
  goto(url: string): Promise<void>;
  act(action: ActionRef): Promise<boolean>;
  observe(instruction: string, scope?: string): Promise<ActionRef[]>;
  extract<T>(schema: unknown, scope?: string): Promise<T>;
  screenshot(selector?: string): Promise<Buffer>;
  currentUrl(): Promise<string>;
  currentTitle(): Promise<string>;
}

// stagehand-engine.ts wraps Stagehand's page.act(), page.observe(), page.extract()
// playwright-fallback.ts uses page.locator() with strict mode

// policy-engine.ts
export function evaluatePolicy(candidates: Record<string, unknown>[], policy: Policy): Record<string, unknown> | null {
  // 1. Apply hard filters
  // 2. Score remaining candidates
  // 3. Apply tie-break
  // 4. Pick based on policy.pick (argmax/argmin/first)
}
```

**Tests:** policy-engine can be fully unit tested. Stagehand/Playwright engines should be tested with mocks (mock the page object).

---

### Task 7: Workflow Execution

**Files to create:**
- `node-runtime/src/runner/step-executor.ts` — Execute single step with fallback ladder
- `node-runtime/src/runner/workflow-runner.ts` — Orchestrate full workflow
- `node-runtime/src/runner/validator.ts` — Validate step expectations
- `node-runtime/src/runner/checkpoint.ts` — GO/NOT GO gate system
- `node-runtime/tests/runner/*.test.ts`

**Key patterns:**

```ts
// step-executor.ts — Implements the 6-level fallback ladder (Blueprint §7.1)
export class StepExecutor {
  constructor(
    private stagehand: BrowserEngine,
    private playwright: BrowserEngine,
    private healingMemory: HealingMemory,
    private authoringClient: AuthoringClient,
    private budgetGuard: BudgetGuard,
  ) {}

  async execute(step: WorkflowStep, context: RunContext): Promise<StepResult> {
    // Level 1: act(cached action) from actions.json
    // Level 2: Playwright strict locator fallback from selectors.json
    // Level 3: observe(scope) — re-discover action
    // Level 4: Healing memory match
    // Level 5: Authoring service /plan-patch
    // Level 6: Screenshot checkpoint (GO/NOT GO)
  }
}

// workflow-runner.ts
export class WorkflowRunner {
  async run(context: RunContext): Promise<RunResult> {
    // 1. Preflight: validate fingerprints
    // 2. Request GO/NOT GO
    // 3. Loop through steps, using StepExecutor
    // 4. Handle retries and onFail policies
    // 5. Generate run summary
  }
}

// validator.ts
export function validateExpectations(expectations: Expectation[], page: BrowserEngine): Promise<boolean> {
  // Check each expectation (url_contains, selector_visible, text_contains, title_contains)
}

// checkpoint.ts
export interface CheckpointHandler {
  requestApproval(message: string, screenshot?: Buffer): Promise<'GO' | 'NOT_GO'>;
}
```

---

## Workstream D: Node Support (depends on Workstream A)

### Task 8: Exception Handling & Budget Guard

**Files to create:**
- `node-runtime/src/exception/classifier.ts` — Classify errors into ErrorType
- `node-runtime/src/exception/router.ts` — Route errors to recovery strategies
- `node-runtime/src/runner/budget-guard.ts` — Token/call budget tracking + downgrade
- `node-runtime/tests/exception/*.test.ts`

**Key patterns:**

```ts
// classifier.ts
export function classifyError(error: unknown, context: { selector?: string; url?: string }): ErrorType {
  // Map Playwright/Stagehand errors to our ErrorType enum
  // TimeoutError + selector -> TargetNotFound
  // Element not clickable -> NotActionable
  // Assertion failure -> ExpectationFailed
  // etc.
}

// router.ts
export type RecoveryAction = 'retry' | 'observe_refresh' | 'selector_fallback' | 'healing_memory' | 'authoring_patch' | 'checkpoint' | 'abort';

export function routeError(errorType: ErrorType): RecoveryAction[] {
  // Return ordered list of recovery actions to try
  // See Blueprint §7 for routing rules
}

// budget-guard.ts
export class BudgetGuard {
  constructor(private config: BudgetConfig) {}

  canCallLlm(): boolean { /* check usage vs budget */ }
  canCallAuthoring(): boolean { /* check usage vs budget */ }
  recordLlmCall(promptChars: number): void { /* update usage */ }
  recordAuthoringCall(): void { /* update usage */ }
  getDowngradeAction(): DowngradeAction | null { /* next downgrade if over budget */ }
}
```

---

### Task 9: Logging, Memory & Authoring Client

**Files to create:**
- `node-runtime/src/logging/run-logger.ts` — JSONL execution log
- `node-runtime/src/logging/summary-writer.ts` — Human-readable MD summary (Blueprint §9)
- `node-runtime/src/logging/trace-bundler.ts` — Package trace artifacts
- `node-runtime/src/memory/healing-memory.ts` — Store successful locator/action pairs
- `node-runtime/src/memory/auth-profile-manager.ts` — Session/cookie management
- `node-runtime/src/authoring-client/http-client.ts` — HTTP client for Python service
- `node-runtime/src/authoring-client/compile-intent.ts`
- `node-runtime/src/authoring-client/plan-patch.ts`
- `node-runtime/src/authoring-client/profiles.ts`
- `node-runtime/tests/logging/*.test.ts`
- `node-runtime/tests/memory/*.test.ts`
- `node-runtime/tests/authoring-client/*.test.ts`

**Key patterns:**

```ts
// run-logger.ts
export class RunLogger {
  constructor(private runDir: string) {}
  logStep(result: StepResult): void { /* append to logs.jsonl */ }
  saveScreenshot(stepId: string, buffer: Buffer): void { /* save step_<id>.png */ }
  saveDomSnippet(stepId: string, html: string): void { /* save dom_<id>.html */ }
}

// summary-writer.ts — Follow template from Blueprint §9
export function writeSummary(runDir: string, context: RunContext, results: StepResult[], patchApplied: boolean): void {
  // Generate markdown summary with: goal, result, duration, LLM calls, key events, version info
}

// healing-memory.ts
export class HealingMemory {
  async findMatch(targetKey: string, currentUrl: string): Promise<ActionRef | null> {
    // Look up previously successful action for this targetKey
  }
  async record(targetKey: string, action: ActionRef, url: string): Promise<void> {
    // Store successful action for future reference
  }
}

// http-client.ts
export class AuthoringClient {
  constructor(private baseUrl: string, private apiKey?: string) {}

  async compileIntent(request: CompileIntentRequest): Promise<CompileIntentResponse> {
    // POST /compile-intent with timeout, schema validation on response
  }
  async planPatch(request: PlanPatchRequest): Promise<PlanPatchResponse> {
    // POST /plan-patch with short timeout (8-15s), schema validation
  }
  async getProfile(profileId: string): Promise<unknown> {
    // GET /profiles/:id
  }
}
```

---

## Summary

| Workstream | Agent | Tasks | Depends On |
|------------|-------|-------|------------|
| A: Node Foundation | node-foundation | 1-2 | — |
| B: Python Service | python-service | 3-4 | — |
| C: Node Runtime | node-runtime | 5-7 | A |
| D: Node Support | node-support | 8-9 | A |

After all workstreams complete: integration smoke test connecting Node runtime to Python service.
