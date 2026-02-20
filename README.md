# web-agentic

**Deterministic-first web automation platform / 결정론적 우선 웹 자동화 플랫폼**

Node.js runtime for execution + Python service for AI-driven recipe generation.
Minimizes LLM usage through cached actions, strict locators, and a 6-level fallback ladder.

Node.js 런타임(실행) + Python 서비스(AI 레시피 생성).
캐시된 액션, 엄격한 로케이터, 6단계 폴백 래더를 통해 LLM 사용을 최소화합니다.

---

## Table of Contents / 목차

- [Architecture / 아키텍처](#architecture--아키텍처)
- [Quick Start / 빠른 시작](#quick-start--빠른-시작)
- [Recipe Format / 레시피 형식](#recipe-format--레시피-형식)
- [Writing Recipes / 레시피 작성법](#writing-recipes--레시피-작성법)
- [Running Workflows / 워크플로우 실행](#running-workflows--워크플로우-실행)
- [Recovery & Fallback / 복구 및 폴백](#recovery--fallback--복구-및-폴백)
- [Python Authoring Service / Python 오소링 서비스](#python-authoring-service--python-오소링-서비스)
- [E2E Testing / E2E 테스트](#e2e-testing--e2e-테스트)
- [Configuration / 설정](#configuration--설정)
- [API Reference / API 레퍼런스](#api-reference--api-레퍼런스)
- [Project Structure / 프로젝트 구조](#project-structure--프로젝트-구조)

---

## Architecture / 아키텍처

```
┌─────────────────────────────────┐     ┌──────────────────────────────┐
│  Node Runtime (Execution)        │     │  Python Service (Generation)  │
│                                  │     │                               │
│  Recipe Loader ─► Workflow Runner │────▶│  POST /compile-intent         │
│       │               │          │     │  POST /plan-patch             │
│       ▼               ▼          │     │  POST /optimize-profile       │
│  Template Engine  Step Executor  │     │  GET  /profiles/:id           │
│                    │             │     │                               │
│         ┌──────────┼──────────┐  │     │  DSPy Programs + GEPA         │
│         │          │          │  │     └──────────────────────────────┘
│    Stagehand   Playwright  Recovery
│    Engine      Fallback    Pipeline
│         │          │          │
│         └──────────┼──────────┘
│                    │
│              Healing Memory
│              Budget Guard
│              Metrics Collector
│              Run Logger
└─────────────────────────────────┘
```

**EN:** The Node runtime executes workflows deterministically using cached Stagehand actions. When a cached action fails, it walks a 6-level fallback ladder before asking a human. The Python service only activates for recipe generation and patch recovery — it never runs during normal execution.

**KR:** Node 런타임은 캐시된 Stagehand 액션을 사용하여 워크플로우를 결정론적으로 실행합니다. 캐시된 액션이 실패하면 사람에게 묻기 전에 6단계 폴백 래더를 순회합니다. Python 서비스는 레시피 생성과 패치 복구 시에만 활성화되며, 정상 실행 중에는 호출되지 않습니다.

---

## Quick Start / 빠른 시작

### Prerequisites / 사전 요구사항

- Node.js >= 18
- Python >= 3.11
- Chromium (installed automatically by Playwright)

### Installation / 설치

```bash
# Clone / 클론
git clone https://github.com/jedikim/web-agentic.git
cd web-agentic

# Node runtime / Node 런타임
cd node-runtime
npm install
npx playwright install chromium
npm run build

# Python service / Python 서비스
cd ../python-authoring-service
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run Tests / 테스트 실행

```bash
# Node unit tests (501 tests) / Node 단위 테스트
cd node-runtime
npm test

# Python unit tests (185 tests) / Python 단위 테스트
cd python-authoring-service
pytest
```

### First Workflow / 첫 워크플로우 실행

```bash
# 1. Start Python service / Python 서비스 시작
cd python-authoring-service
uvicorn app.main:app --host 127.0.0.1 --port 8321

# 2. In another terminal, run a recipe / 다른 터미널에서 레시피 실행
cd node-runtime
npx tsx src/index.ts --recipe ../recipes/example.com/basic/v001
```

---

## Recipe Format / 레시피 형식

A recipe is a versioned directory containing 5 JSON files:
레시피는 5개의 JSON 파일이 포함된 버전 관리 디렉터리입니다:

```
recipes/
└── example.com/
    └── basic/
        └── v001/
            ├── workflow.json      # Step sequence / 단계 순서
            ├── actions.json       # Cached Stagehand actions / 캐시된 액션
            ├── selectors.json     # Playwright fallback selectors / 폴백 셀렉터
            ├── fingerprints.json  # Page verification / 페이지 검증
            └── policies.json      # Candidate selection rules / 후보 선택 규칙
```

### workflow.json

Defines the step-by-step procedure. / 단계별 절차를 정의합니다.

```json
{
  "id": "example_basic",
  "version": "v001",
  "steps": [
    {
      "id": "open",
      "op": "goto",
      "args": { "url": "https://example.com" }
    },
    {
      "id": "verify_page",
      "op": "checkpoint",
      "args": { "message": "Verify page loaded" },
      "expect": [
        { "kind": "title_contains", "value": "Example" },
        { "kind": "url_contains", "value": "example.com" }
      ]
    },
    {
      "id": "click_link",
      "op": "act_cached",
      "targetKey": "more_info.link",
      "expect": [
        { "kind": "url_contains", "value": "iana.org" }
      ],
      "onFail": "fallback"
    }
  ]
}
```

**Step operations / 단계 연산자:**

| Op | Description (EN) | 설명 (KR) |
|----|-------------------|-----------|
| `goto` | Navigate to URL | URL로 이동 |
| `act_cached` | Execute cached action by targetKey | targetKey로 캐시된 액션 실행 |
| `checkpoint` | GO/NOT GO verification gate | GO/NOT GO 검증 게이트 |
| `extract` | Extract structured data from page | 페이지에서 구조화된 데이터 추출 |
| `wait` | Wait for specified milliseconds | 지정된 밀리초 대기 |

### actions.json

Maps targetKeys to cached Stagehand actions. These are the result of `observe()` calls that can be replayed deterministically.

targetKey를 캐시된 Stagehand 액션에 매핑합니다. `observe()` 호출 결과로, 결정론적으로 재생할 수 있습니다.

```json
{
  "more_info.link": {
    "instruction": "find the Learn more link",
    "preferred": {
      "selector": "a[href='https://iana.org/domains/example']",
      "description": "Learn more link",
      "method": "click",
      "arguments": []
    },
    "observedAt": "2026-02-21T00:00:00Z"
  }
}
```

### selectors.json

Playwright fallback selectors when cached actions fail. / 캐시된 액션이 실패할 때 사용하는 Playwright 폴백 셀렉터.

```json
{
  "more_info.link": {
    "primary": "a[href='https://iana.org/domains/example']",
    "fallbacks": [
      "a:has-text('Learn more')",
      "body > div > p:last-child > a"
    ],
    "strategy": "css"
  }
}
```

### fingerprints.json

Page verification — confirm you're on the right page before acting.
페이지 검증 — 액션 실행 전에 올바른 페이지인지 확인합니다.

```json
{
  "example_main": {
    "mustText": ["Example Domain"],
    "urlContains": "example.com"
  }
}
```

### policies.json

Candidate selection rules for when multiple elements match. / 여러 요소가 매칭될 때의 후보 선택 규칙.

```json
{
  "prefer_visible": {
    "hardFilter": { "visible": true },
    "score": { "aboveFold": 2, "hasTestId": 1 },
    "tieBreak": "domOrder"
  }
}
```

---

## Writing Recipes / 레시피 작성법

### Manual Creation / 수동 작성

1. Create the directory structure / 디렉터리 구조 생성:
```bash
mkdir -p recipes/mysite.com/login/v001
```

2. Write `workflow.json` with your steps / 단계를 workflow.json에 작성:
```json
{
  "id": "mysite_login",
  "version": "v001",
  "steps": [
    { "id": "open", "op": "goto", "args": { "url": "https://mysite.com/login" } },
    { "id": "enter_email", "op": "act_cached", "targetKey": "login.email_input" },
    { "id": "enter_password", "op": "act_cached", "targetKey": "login.password_input" },
    { "id": "submit", "op": "act_cached", "targetKey": "login.submit_button" },
    {
      "id": "verify",
      "op": "checkpoint",
      "args": { "message": "Verify login succeeded" },
      "expect": [{ "kind": "url_contains", "value": "/dashboard" }]
    }
  ]
}
```

3. Populate `actions.json` from a Stagehand observe() session / Stagehand observe() 세션에서 actions.json 채우기:
```json
{
  "login.email_input": {
    "instruction": "type email into the email field",
    "preferred": {
      "selector": "input[type='email']",
      "description": "Email input field",
      "method": "fill",
      "arguments": ["{{vars.email}}"]
    },
    "observedAt": "2026-02-21T00:00:00Z"
  }
}
```

4. Add fallback selectors in `selectors.json` / selectors.json에 폴백 셀렉터 추가
5. Add page fingerprints in `fingerprints.json` / fingerprints.json에 페이지 지문 추가
6. Add policies in `policies.json` (or leave as `{}`) / policies.json에 정책 추가 (또는 `{}`로 비워둠)

### Template Variables / 템플릿 변수

Use `{{vars.key}}` placeholders in actions and selectors. They are resolved at runtime from the RunContext.

액션과 셀렉터에서 `{{vars.key}}` 플레이스홀더를 사용합니다. 런타임에 RunContext에서 해석됩니다.

```json
{
  "method": "fill",
  "arguments": ["{{vars.email}}"]
}
```

```typescript
const context: RunContext = {
  recipe,
  vars: { email: "user@example.com", password: "secret" },
  budget: defaultBudget,
};
```

### AI-Assisted Creation / AI 보조 레시피 생성

Use the Python authoring service to generate recipes from natural language:
Python 오소링 서비스를 사용하여 자연어로 레시피를 생성할 수 있습니다:

```bash
curl -X POST http://127.0.0.1:8321/compile-intent \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "req-001",
    "goal": "Log into mysite.com",
    "domain": "mysite.com",
    "procedure": "1. Go to login page\n2. Enter email\n3. Enter password\n4. Click submit\n5. Verify dashboard loads"
  }'
```

---

## Running Workflows / 워크플로우 실행

### Programmatic Usage / 프로그래밍 방식 사용

```typescript
import { chromium } from 'playwright';
import { loadRecipe } from './recipe/loader.js';
import { PlaywrightFallbackEngine } from './engines/playwright-fallback.js';
import { StepExecutor } from './runner/step-executor.js';
import { WorkflowRunner } from './runner/workflow-runner.js';
import { AutoApproveCheckpointHandler } from './runner/checkpoint.js';
import { HealingMemory } from './memory/healing-memory.js';
import { BudgetGuard } from './runner/budget-guard.js';

// 1. Load recipe / 레시피 로드
const recipe = await loadRecipe('./recipes/example.com/basic', 'v001');

// 2. Launch browser / 브라우저 실행
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

// 3. Create engines / 엔진 생성
const engine = new PlaywrightFallbackEngine(page);

// 4. Create runner / 러너 생성
const executor = new StepExecutor(engine, engine, {
  healingMemory: new HealingMemory(),
  budgetGuard: new BudgetGuard({ maxLlmCalls: 3, maxAuthoringCalls: 2 }),
});

const runner = new WorkflowRunner(
  engine,
  engine,
  executor,
  new AutoApproveCheckpointHandler(),
);

// 5. Run / 실행
const result = await runner.run({
  recipe,
  vars: {},
  budget: { maxLlmCalls: 3, maxAuthoringCalls: 2, maxPromptChars: 10000, timeoutMs: 120000 },
});

console.log(`Result: ${result.ok ? 'SUCCESS' : 'FAILED'}`);
console.log(`Steps: ${result.stepResults.length}, Duration: ${result.durationMs}ms`);

await browser.close();
```

### With Stagehand (LLM-powered) / Stagehand 사용 (LLM 기반)

```typescript
import { Stagehand } from '@browserbasehq/stagehand';
import { StagehandEngine } from './engines/stagehand-engine.js';

// Requires OPENAI_API_KEY or ANTHROPIC_API_KEY
// OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 필요
const stagehand = new Stagehand({ env: 'LOCAL' });
await stagehand.init();

const stagehandEngine = new StagehandEngine(stagehand.page);
const playwrightEngine = new PlaywrightFallbackEngine(stagehand.page);

// StagehandEngine is primary, PlaywrightFallbackEngine is secondary
// StagehandEngine이 기본, PlaywrightFallbackEngine이 보조
const executor = new StepExecutor(stagehandEngine, playwrightEngine, { ... });
```

### RunContext Options / RunContext 옵션

```typescript
interface RunContext {
  recipe: Recipe;              // Loaded recipe / 로드된 레시피
  vars: Record<string, string>; // Template variables / 템플릿 변수
  budget: TokenBudget;          // Execution limits / 실행 제한
}

interface TokenBudget {
  maxLlmCalls: number;       // Max LLM API calls / 최대 LLM 호출 수
  maxAuthoringCalls: number; // Max Python service calls / 최대 Python 서비스 호출 수
  maxPromptChars: number;    // Max prompt characters / 최대 프롬프트 문자 수
  timeoutMs: number;         // Global timeout / 글로벌 타임아웃
}
```

---

## Recovery & Fallback / 복구 및 폴백

When a step fails, the system walks a 6-level fallback ladder:
단계가 실패하면 시스템은 6단계 폴백 래더를 순회합니다:

```
Level 1: Cached Action (act_cached)
  ↓ fail
Level 2: Playwright Strict Locator (selectors.json fallbacks)
  ↓ fail
Level 3: Stagehand observe() Refresh (re-discover action on page)
  ↓ fail
Level 4: Healing Memory (use previously successful alternatives)
  ↓ fail
Level 5: Python Authoring Patch (POST /plan-patch → JSON patch)
  ↓ fail
Level 6: Human Checkpoint (GO/NOT GO with screenshot)
```

**EN:** Levels 1-2 are free (no LLM). Level 3 uses one observe() call. Level 4 uses local memory. Level 5 calls the Python service. Level 6 asks for human approval. The budget guard enforces hard limits at each level.

**KR:** 레벨 1-2는 무료(LLM 없음). 레벨 3은 observe() 호출 1회. 레벨 4는 로컬 메모리 사용. 레벨 5는 Python 서비스 호출. 레벨 6은 사람의 승인 요청. 버짓 가드가 각 레벨에서 하드 리밋을 적용합니다.

### Healing Memory / 힐링 메모리

The healing memory records successful recoveries with evidence:
힐링 메모리는 증거와 함께 성공적인 복구를 기록합니다:

```typescript
const memory = new HealingMemory();

// Record a successful healing / 성공적인 힐링 기록
memory.record(targetKey, newSelector, action, {
  url: 'https://example.com',
  originalSelector: 'old-selector',
  errorType: 'TargetNotFound',
});

// Query for future use / 향후 사용을 위해 조회
const suggestion = memory.suggest(targetKey);
// Returns { selector, action, confidence } if confidence > threshold
// 신뢰도 > 임계값이면 { selector, action, confidence } 반환
```

### Patch Recovery / 패치 복구

When the fallback ladder reaches Level 5, the system sends failure context to the Python service:
폴백 래더가 레벨 5에 도달하면 시스템은 실패 컨텍스트를 Python 서비스로 전송합니다:

```
Node Runtime                          Python Service
    │                                      │
    ├─ Error: TargetNotFound ──────────►   │
    │  { errorType, failedSelector,        │
    │    url, title, domSnippet,           │
    │    screenshot }                      │
    │                                      ├─ Select strategy
    │                                      ├─ Generate patch ops
    │                                      ├─ Validate (§8 contract)
    │  ◄───────── PatchPayload ──────────  │
    │  { ops: [                            │
    │    { path: "actions.click_link",     │
    │      op: "replace",                  │
    │      value: { ... } }               │
    │  ]}                                  │
    │                                      │
    ├─ Classify: minor or major            │
    ├─ If minor: auto-apply                │
    ├─ If major: require GO/NOT GO         │
    ├─ Merge into recipe, bump version     │
    └─ Retry step with patched recipe      │
```

---

## Python Authoring Service / Python 오소링 서비스

### Starting the Service / 서비스 시작

```bash
cd python-authoring-service
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8321 --reload
```

### Endpoints / 엔드포인트

#### POST /compile-intent — Recipe generation / 레시피 생성

```bash
curl -X POST http://127.0.0.1:8321/compile-intent \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "req-001",
    "goal": "Check order status on example-shop.com",
    "domain": "example-shop.com",
    "procedure": "1. Go to orders page\n2. Click on latest order\n3. Extract status text"
  }'
```

Response / 응답:
```json
{
  "requestId": "req-001",
  "workflow": { "id": "...", "version": "v001", "steps": [...] },
  "actions": { ... },
  "selectors": { ... },
  "policies": { ... },
  "fingerprints": { ... }
}
```

#### POST /plan-patch — Patch generation / 패치 생성

```bash
curl -X POST http://127.0.0.1:8321/plan-patch \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "patch-001",
    "errorType": "TargetNotFound",
    "failedSelector": "#old-button",
    "url": "https://example.com/page",
    "title": "Example Page",
    "domSnippet": "<div class=\"actions\"><button id=\"new-btn\">Click</button></div>"
  }'
```

Response / 응답:
```json
{
  "requestId": "patch-001",
  "ops": [
    {
      "path": "selectors.old-button",
      "op": "replace",
      "value": { "primary": "#new-btn", "fallbacks": ["button:has-text('Click')"] }
    }
  ],
  "reason": "Button ID changed from #old-button to #new-btn"
}
```

#### POST /optimize-profile — GEPA optimization / GEPA 최적화

Queues an async optimization loop for the DSPy programs.
DSPy 프로그램에 대한 비동기 최적화 루프를 큐에 넣습니다.

```bash
curl -X POST http://127.0.0.1:8321/optimize-profile \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "opt-001",
    "profileId": "default",
    "taskSpecs": ["spec-001", "spec-002"]
  }'
```

#### GET /profiles/:id — Fetch profile / 프로필 조회

```bash
curl http://127.0.0.1:8321/profiles/default
```

### DSPy Configuration / DSPy 설정

The service uses DSPy for intelligent generation. Configure the LLM backend:
서비스는 지능형 생성을 위해 DSPy를 사용합니다. LLM 백엔드를 설정하세요:

```python
import dspy

# Option 1: OpenAI
dspy.configure(lm=dspy.LM("openai/gpt-4o-mini"))

# Option 2: Anthropic
dspy.configure(lm=dspy.LM("anthropic/claude-sonnet-4-20250514"))
```

Without a configured LLM, the service falls back to rule-based generation (still functional but less intelligent).
LLM이 설정되지 않으면 규칙 기반 생성으로 폴백합니다(여전히 동작하지만 지능도가 낮음).

---

## E2E Testing / E2E 테스트

### Browser E2E / 브라우저 E2E

Runs 5 real browser scenarios against live websites:
라이브 웹사이트에 대해 5개의 실제 브라우저 시나리오를 실행합니다:

```bash
cd node-runtime
npx tsx e2e/run-pipeline.ts
```

| Test | Target | Description (EN) | 설명 (KR) |
|------|--------|-------------------|-----------|
| Basic | example.com | Navigate + click link | 탐색 + 링크 클릭 |
| Broken Selector | example.com | Recovery from intentionally broken selector | 의도적으로 깨진 셀렉터에서 복구 |
| Form | httpbin.org | Multi-field form filling + submission | 다중 필드 폼 작성 + 제출 |
| Multi-step | example.com | Navigate + extract + wait + navigate | 탐색 + 추출 + 대기 + 탐색 |
| Total Failure | example.com | All selectors broken, checkpoint recovery | 모든 셀렉터 실패, 체크포인트 복구 |

Output includes screenshots, JSONL logs, metrics, and a summary.md in `e2e/runs/<timestamp>/`.
결과물은 `e2e/runs/<timestamp>/`에 스크린샷, JSONL 로그, 메트릭, summary.md를 포함합니다.

### Integration E2E / 통합 E2E

Tests Node ↔ Python HTTP communication (requires Python service running):
Node ↔ Python HTTP 통신 테스트 (Python 서비스 실행 필요):

```bash
# Terminal 1: Start Python service / 터미널 1: Python 서비스 시작
cd python-authoring-service
uvicorn app.main:app --port 8321

# Terminal 2: Run integration tests / 터미널 2: 통합 테스트 실행
cd node-runtime
AUTHORING_URL=http://127.0.0.1:8321 npx tsx e2e/run-integration.ts
```

---

## Configuration / 설정

### Environment Variables / 환경변수

| Variable | Default | Description (EN) | 설명 (KR) |
|----------|---------|-------------------|-----------|
| `AUTHORING_URL` | `http://127.0.0.1:8321` | Python service URL | Python 서비스 URL |
| `OPENAI_API_KEY` | — | Required for Stagehand engine | Stagehand 엔진에 필요 |
| `ANTHROPIC_API_KEY` | — | Alternative LLM key | 대체 LLM 키 |
| `HEADLESS` | `true` | Browser headless mode | 브라우저 헤드리스 모드 |
| `RECIPE_BASE_PATH` | `./recipes` | Root directory for recipes | 레시피 루트 디렉터리 |

### Budget Configuration / 버짓 설정

Control LLM usage with the TokenBudget:
TokenBudget으로 LLM 사용량을 제어합니다:

```typescript
const budget: TokenBudget = {
  maxLlmCalls: 3,          // Max observe() / extract() LLM calls / 최대 LLM 호출
  maxAuthoringCalls: 2,    // Max /plan-patch calls / 최대 /plan-patch 호출
  maxPromptChars: 10000,   // Max total prompt chars / 최대 프롬프트 문자
  timeoutMs: 120000,       // 2 minute global timeout / 2분 글로벌 타임아웃
};
```

When limits are exceeded, the BudgetGuard applies automatic downgrades:
제한 초과 시 BudgetGuard가 자동 다운그레이드를 적용합니다:

1. Trim DOM context / DOM 컨텍스트 축소
2. Drop conversation history / 대화 히스토리 삭제
3. Narrow extraction scope / 추출 범위 축소
4. Require human checkpoint / 사람 체크포인트 요구

### SLO Targets / SLO 목표

| Metric | Target | Description (EN) | 설명 (KR) |
|--------|--------|-------------------|-----------|
| LLM calls/run | ≤ 0.2 | Average LLM calls per execution | 실행당 평균 LLM 호출 |
| 2nd run success | ≥ 95% | Same recipe succeeds on 2nd run | 동일 레시피 2회차 성공률 |
| Post-patch recovery | ≥ 80% | Success rate after applying a patch | 패치 적용 후 성공률 |

---

## API Reference / API 레퍼런스

### Core Classes / 핵심 클래스

#### WorkflowRunner

Main orchestrator. Runs a complete workflow with preflight, step execution, and logging.
메인 오케스트레이터. 사전점검, 단계 실행, 로깅을 포함한 전체 워크플로우를 실행합니다.

```typescript
class WorkflowRunner {
  constructor(
    stagehand: BrowserEngine,
    playwright: BrowserEngine,
    executor: StepExecutor,
    checkpoint: CheckpointHandler,
  );
  run(context: RunContext): Promise<RunResult>;
}
```

#### StepExecutor

Executes individual steps with the 6-level fallback ladder.
6단계 폴백 래더를 사용하여 개별 단계를 실행합니다.

```typescript
class StepExecutor {
  constructor(
    stagehand: BrowserEngine,
    playwright: BrowserEngine,
    options: {
      healingMemory?: HealingMemory;
      budgetGuard?: BudgetGuard;
      observeRefresher?: ObserveRefresher;
      recoveryPipeline?: RecoveryPipeline;
      authoringClient?: AuthoringHttpClient;
      checkpoint?: CheckpointHandler;
    },
  );
  execute(step: WorkflowStep, context: RunContext): Promise<StepResult>;
}
```

#### BrowserEngine (Interface)

```typescript
interface BrowserEngine {
  goto(url: string): Promise<void>;
  act(action: ActionRef): Promise<boolean>;
  observe(instruction: string, scope?: string): Promise<ActionRef[]>;
  extract<T>(schema: unknown, scope?: string): Promise<T>;
  screenshot(selector?: string): Promise<Buffer>;
  currentUrl(): Promise<string>;
  currentTitle(): Promise<string>;
}
```

#### HealingMemory

```typescript
class HealingMemory {
  record(key: string, selector: string, action: ActionRef, evidence: HealingEvidence): void;
  suggest(key: string): HealingSuggestion | null;
  recordFailure(key: string, selector: string): void;
  prune(options: { minConfidence?: number; maxAgeMs?: number }): number;
}
```

#### MetricsCollector

```typescript
class MetricsCollector {
  startRun(runId: string): void;
  recordStep(stepId: string, result: StepResult): void;
  recordLlmCall(): void;
  recordPatch(patchType: 'minor' | 'major'): void;
  endRun(): RunMetrics;
}
```

---

## Project Structure / 프로젝트 구조

```
web-agentic/
├── node-runtime/
│   ├── src/
│   │   ├── types/              # TypeScript type definitions / 타입 정의 (9 files)
│   │   ├── schemas/            # Zod validators / Zod 검증기 (7 files)
│   │   ├── recipe/             # Recipe loading & templating / 레시피 로딩 & 템플릿 (4 files)
│   │   ├── engines/            # Browser engines / 브라우저 엔진 (8 files)
│   │   ├── runner/             # Workflow execution / 워크플로우 실행 (7 files)
│   │   ├── exception/          # Error classification / 에러 분류 (2 files)
│   │   ├── logging/            # Run logging / 실행 로깅 (3 files)
│   │   ├── memory/             # Healing memory & auth / 힐링 메모리 & 인증 (2 files)
│   │   ├── metrics/            # Metrics collection / 메트릭 수집 (4 files)
│   │   ├── blocks/             # Workflow blocks / 워크플로우 블록 (6 files)
│   │   ├── testing/            # Trace replay & regression / 트레이스 재생 & 회귀 (2 files)
│   │   ├── authoring-client/   # Python service client / Python 서비스 클라이언트 (4 files)
│   │   └── index.ts
│   ├── tests/                  # 501 unit tests / 단위 테스트
│   ├── e2e/                    # E2E test infrastructure / E2E 테스트 인프라
│   │   ├── run-pipeline.ts     # Browser E2E (5 scenarios) / 브라우저 E2E
│   │   ├── run-integration.ts  # HTTP integration (13 tests) / HTTP 통합 테스트
│   │   └── recipes/            # Test recipes / 테스트 레시피
│   ├── package.json
│   └── tsconfig.json
│
├── python-authoring-service/
│   ├── app/
│   │   ├── api/                # REST endpoints / REST 엔드포인트 (4 files)
│   │   ├── dspy_programs/      # DSPy AI programs / DSPy AI 프로그램 (4 files)
│   │   ├── gepa/               # Self-improving optimizer / 자기 개선 옵티마이저 (3 files)
│   │   ├── services/           # Patch generation / 패치 생성 (2 files)
│   │   ├── storage/            # Profile & task storage / 프로필 & 태스크 스토리지 (2 files)
│   │   ├── schemas/            # Pydantic models / Pydantic 모델 (2 files)
│   │   └── main.py
│   ├── tests/                  # 185 unit tests / 단위 테스트
│   └── pyproject.toml
│
├── doc/
│   └── stagehand_chrome_automation_blueprint.md  # Design blueprint / 설계 청사진
│
├── docs/
│   ├── IMPLEMENTATION-REPORT.md                   # Build report / 빌드 리포트
│   ├── DESIGN.md                                  # Detailed design / 상세 설계
│   └── plans/                                     # Implementation plans / 구현 계획
│
└── .gitignore
```

---

## License

MIT
