# Web-Agentic — Detailed Design Document / 상세 설계 문서

**Version:** 1.0
**Date:** 2026-02-21
**Status:** Implemented (Phase 1-5 complete)

---

## Table of Contents / 목차

1. [Design Philosophy / 설계 철학](#1-design-philosophy--설계-철학)
2. [System Architecture / 시스템 아키텍처](#2-system-architecture--시스템-아키텍처)
3. [Data Model / 데이터 모델](#3-data-model--데이터-모델)
4. [Execution Engine / 실행 엔진](#4-execution-engine--실행-엔진)
5. [Fallback Ladder / 폴백 래더](#5-fallback-ladder--폴백-래더)
6. [Recovery Pipeline / 복구 파이프라인](#6-recovery-pipeline--복구-파이프라인)
7. [Patch Contract / 패치 계약](#7-patch-contract--패치-계약)
8. [Python Authoring Service / Python 오소링 서비스](#8-python-authoring-service--python-오소링-서비스)
9. [DSPy & GEPA / DSPy와 GEPA](#9-dspy--gepa--dspy와-gepa)
10. [Special Surface Handling / 특수 서피스 처리](#10-special-surface-handling--특수-서피스-처리)
11. [Memory Systems / 메모리 시스템](#11-memory-systems--메모리-시스템)
12. [Metrics & SLOs / 메트릭과 SLO](#12-metrics--slos--메트릭과-slo)
13. [Logging & Tracing / 로깅과 트레이싱](#13-logging--tracing--로깅과-트레이싱)
14. [Block Registry / 블록 레지스트리](#14-block-registry--블록-레지스트리)
15. [Security Considerations / 보안 고려사항](#15-security-considerations--보안-고려사항)
16. [Module Dependency Map / 모듈 의존성 맵](#16-module-dependency-map--모듈-의존성-맵)

---

## 1. Design Philosophy / 설계 철학

### Core Principles / 핵심 원칙

**Deterministic-first execution / 결정론적 우선 실행**

The platform assumes most web interactions are repetitive. A workflow that succeeded once should succeed again without any LLM involvement. LLMs are expensive, slow, and non-deterministic — they are the last resort, not the first tool.

플랫폼은 대부분의 웹 상호작용이 반복적이라고 가정합니다. 한 번 성공한 워크플로우는 LLM 개입 없이 다시 성공해야 합니다. LLM은 비싸고, 느리고, 비결정론적입니다 — 첫 번째 도구가 아니라 마지막 수단입니다.

**Patch-only LLM output / 패치 전용 LLM 출력**

When an LLM is invoked, it never generates code. It only produces JSON patch operations against the existing recipe. This makes LLM output auditable, reversible, and constrained to a well-defined contract.

LLM이 호출될 때 절대 코드를 생성하지 않습니다. 기존 레시피에 대한 JSON 패치 연산만 생성합니다. 이로써 LLM 출력이 감사 가능하고, 되돌릴 수 있으며, 잘 정의된 계약에 제한됩니다.

**Human-in-the-loop / 사람 참여 루프**

Critical decisions require human approval through GO/NOT GO checkpoint gates. The system never silently proceeds past a major failure — it escalates to a human with a screenshot and context.

중요한 결정은 GO/NOT GO 체크포인트 게이트를 통해 사람의 승인을 필요로 합니다. 시스템은 주요 실패를 조용히 넘어가지 않고, 스크린샷과 컨텍스트를 포함하여 사람에게 에스컬레이션합니다.

**Evidence-based healing / 증거 기반 힐링**

Self-healing only works when there's recorded evidence of a previously successful alternative. No evidence = no healing. This prevents hallucinated fixes.

자가 치유는 이전에 성공한 대안의 기록된 증거가 있을 때만 작동합니다. 증거 없음 = 힐링 없음. 이로써 환각된 수정을 방지합니다.

### Design Constraints / 설계 제약

| Constraint | Rationale (EN) | 근거 (KR) |
|------------|-----------------|-----------|
| LLM calls/run ≤ 0.2 | Most runs should be pure deterministic | 대부분의 실행은 순수 결정론적이어야 함 |
| No code generation | Patches are data, not programs | 패치는 데이터이지 프로그램이 아님 |
| Version immutability | v001 is frozen once created; patches create v002 | v001은 생성 후 동결; 패치가 v002를 생성 |
| Process separation | Node for speed, Python for intelligence | Node는 속도, Python은 지능 |
| Budget enforcement | Hard limits with automatic downgrade | 자동 다운그레이드가 있는 하드 리밋 |

---

## 2. System Architecture / 시스템 아키텍처

### High-Level Flow / 상위 수준 흐름

```
User Intent                                    Recipe Store
    │                                              │
    ▼                                              │
┌──────────────────┐                               │
│ Python Authoring │  compile-intent               │
│ Service          │──────────────────────────────► │
└──────────────────┘                               │
                                                   │
    ┌──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│ Node Runtime                                              │
│                                                           │
│  ┌─────────────────┐                                      │
│  │ Recipe Loader    │── Load 5 JSON files ──►  Recipe      │
│  │ Template Engine  │── Resolve {{vars}} ──►  object      │
│  └─────────────────┘                                      │
│           │                                               │
│           ▼                                               │
│  ┌─────────────────┐     ┌──────────────────┐             │
│  │ Workflow Runner  │────►│ Preflight Check  │             │
│  │                  │     │ (fingerprints)   │             │
│  │                  │     └──────────────────┘             │
│  │                  │                                      │
│  │  for each step:  │     ┌──────────────────┐             │
│  │  ┌───────────────┤────►│ Step Executor    │             │
│  │  │               │     │                  │             │
│  │  │  on success:  │     │  1. act_cached   │             │
│  │  │  next step    │     │  2. locator FB   │             │
│  │  │               │     │  3. observe()    │             │
│  │  │  on failure:  │     │  4. healing mem  │             │
│  │  │  recovery ────┤     │  5. plan-patch   │             │
│  │  │               │     │  6. checkpoint   │             │
│  │  └───────────────┤     └──────────────────┘             │
│  │                  │                                      │
│  │  after all:      │     ┌──────────────────┐             │
│  │  ┌───────────────┤────►│ Summary + Log    │             │
│  │  │ log + metrics │     │ JSONL + MD       │             │
│  │  └───────────────┘     └──────────────────┘             │
│  └─────────────────┘                                      │
└──────────────────────────────────────────────────────────┘
```

### Process Boundary / 프로세스 경계

```
┌──────────────────────┐         HTTP/JSON         ┌──────────────────────┐
│                      │◄─────────────────────────►│                      │
│   Node Runtime       │  POST /compile-intent     │   Python Authoring   │
│   (TypeScript)       │  POST /plan-patch         │   Service (FastAPI)  │
│                      │  POST /optimize-profile   │                      │
│   - Fast execution   │  GET  /profiles/:id       │   - DSPy programs    │
│   - Browser control  │                           │   - GEPA optimizer   │
│   - Deterministic    │  requestId idempotency    │   - Patch generation │
│                      │  Zod ↔ Pydantic schemas   │   - Profile storage  │
└──────────────────────┘                           └──────────────────────┘
```

**EN:** The Node runtime never imports Python code and vice versa. Communication is strictly HTTP with JSON bodies. Both sides validate with their respective schema libraries (Zod for Node, Pydantic for Python). The `requestId` field enables safe retries.

**KR:** Node 런타임은 Python 코드를 임포트하지 않으며 반대도 마찬가지입니다. 통신은 엄격하게 JSON 본문을 가진 HTTP입니다. 양쪽 모두 각자의 스키마 라이브러리로 검증합니다 (Node는 Zod, Python은 Pydantic). `requestId` 필드는 안전한 재시도를 가능하게 합니다.

---

## 3. Data Model / 데이터 모델

### Recipe Structure / 레시피 구조

A Recipe is the central data artifact. It is a versioned, immutable directory containing 5 JSON files.

Recipe는 중앙 데이터 산출물입니다. 5개의 JSON 파일을 포함하는 버전 관리되고 불변인 디렉터리입니다.

```
recipes/<domain>/<flow>/<version>/
├── workflow.json
├── actions.json
├── selectors.json
├── fingerprints.json
└── policies.json
```

### Type Definitions / 타입 정의

#### Workflow

```typescript
interface Workflow {
  id: string;
  version: string;
  steps: WorkflowStep[];
}

interface WorkflowStep {
  id: string;
  op: 'goto' | 'act_cached' | 'checkpoint' | 'extract' | 'wait';
  targetKey?: string;       // Reference into actions.json / actions.json 참조
  args?: Record<string, unknown>;
  expect?: Expectation[];   // Post-step verification / 단계 후 검증
  onFail?: 'fallback' | 'abort' | 'skip';
}

interface Expectation {
  kind: 'url_contains' | 'title_contains' | 'selector_exists' | 'text_contains';
  value: string;
}
```

#### ActionRef (Cached Stagehand Action)

```typescript
interface ActionRef {
  selector: string;
  description: string;
  method: 'click' | 'fill' | 'select' | 'hover' | 'focus' | 'press';
  arguments: string[];
}

// actions.json stores a map:
interface ActionsMap {
  [targetKey: string]: {
    instruction: string;
    preferred: ActionRef;
    observedAt: string;   // ISO timestamp / ISO 타임스탬프
  };
}
```

#### Selector (Playwright Fallback)

```typescript
interface SelectorEntry {
  primary: string;
  fallbacks: string[];
  strategy: 'css' | 'xpath' | 'role' | 'testid';
}

// selectors.json:
interface SelectorsMap {
  [targetKey: string]: SelectorEntry;
}
```

#### Fingerprint (Page Verification)

```typescript
interface Fingerprint {
  mustText?: string[];       // Page must contain these strings / 필수 포함 문자열
  mustSelectors?: string[];  // Page must have these elements / 필수 존재 요소
  urlContains?: string;      // URL must contain this / URL 필수 포함
}

// fingerprints.json:
interface FingerprintsMap {
  [name: string]: Fingerprint;
}
```

#### Policy (Candidate Selection)

```typescript
interface Policy {
  hardFilter?: Record<string, unknown>;  // Eliminate non-matching / 비매칭 제거
  score?: Record<string, number>;        // Weight by attribute / 속성별 가중치
  tieBreak?: 'domOrder' | 'shortest' | 'random';
}
```

#### Patch

```typescript
interface PatchOperation {
  path: string;    // e.g. "actions.login_button" or "selectors.email_input"
  op: 'replace' | 'add' | 'remove';
  value?: unknown;
}

interface PatchPayload {
  ops: PatchOperation[];
  reason: string;
}
```

### Schema Validation / 스키마 검증

All data passes through bidirectional validation:
모든 데이터는 양방향 검증을 거칩니다:

```
                    ┌─────────────┐
   JSON file ──────►│ Zod Schema  │──────► Typed TypeScript object
                    └─────────────┘

                    ┌──────────────┐
   HTTP request ───►│ Pydantic     │──────► Typed Python object
                    │ Model        │
                    └──────────────┘
```

**Key compatibility rule / 핵심 호환성 규칙:**
Zod schemas use `.nullable().optional()` for any field that Python might serialize as `null`. Python Pydantic serializes `None` as JSON `null`, but Zod `.optional()` only accepts `undefined`.

Zod 스키마는 Python이 `null`로 직렬화할 수 있는 필드에 `.nullable().optional()`을 사용합니다. Python Pydantic은 `None`을 JSON `null`로 직렬화하지만, Zod `.optional()`은 `undefined`만 허용합니다.

### Versioning / 버전 관리

```
v001/  ──── original recipe (immutable once created)
  │         원본 레시피 (생성 후 불변)
  │
  │  patch applied ──►  v002/ (new directory, full copy + patch merged)
  │  패치 적용            새 디렉터리, 전체 복사 + 패치 병합
  │
  v002/  ──── patched recipe (also immutable)
               패치된 레시피 (역시 불변)
```

Minor patches (selector updates) are auto-applied. Major patches (workflow structure changes) require GO/NOT GO approval.

마이너 패치(셀렉터 업데이트)는 자동 적용됩니다. 메이저 패치(워크플로우 구조 변경)는 GO/NOT GO 승인이 필요합니다.

---

## 4. Execution Engine / 실행 엔진

### BrowserEngine Interface / BrowserEngine 인터페이스

All browser interaction goes through this interface. Two implementations exist:
모든 브라우저 상호작용은 이 인터페이스를 통합니다. 두 가지 구현이 있습니다:

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

#### StagehandEngine

Wraps `@browserbasehq/stagehand` v3. Uses the Stagehand AI model for `observe()` and `extract()`. The `act()` method replays cached actions deterministically (no LLM) when a cached ActionRef is provided.

`@browserbasehq/stagehand` v3를 래핑합니다. `observe()`와 `extract()`에 Stagehand AI 모델을 사용합니다. `act()` 메서드는 캐시된 ActionRef가 제공되면 LLM 없이 결정론적으로 캐시된 액션을 재생합니다.

```
act(cached ActionRef)  →  No LLM cost (deterministic replay)
observe(instruction)   →  1 LLM call (returns ActionRef[])
extract(schema)        →  1 LLM call (returns structured data)
```

#### PlaywrightFallbackEngine

Pure Playwright locators. No LLM involvement at all. Uses a strict priority:

순수 Playwright 로케이터. LLM 개입 전무. 엄격한 우선순위 사용:

```
1. getByTestId(selector)     ── most stable / 가장 안정
2. getByRole(role, { name })  ── semantic / 시맨틱
3. page.locator(css)          ── CSS selector / CSS 셀렉터
4. page.locator(xpath)        ── XPath fallback / XPath 폴백
```

### Step Execution Flow / 단계 실행 흐름

```
WorkflowStep
    │
    ▼
┌───────────────────────────────────────┐
│ Step Executor                          │
│                                        │
│  1. Resolve targetKey from recipe      │
│     recipe에서 targetKey 해석           │
│                                        │
│  2. Match op:                          │
│     ├─ goto:       engine.goto(url)    │
│     ├─ act_cached: engine.act(action)  │
│     ├─ checkpoint: handler.approve()   │
│     ├─ extract:    engine.extract()    │
│     └─ wait:       setTimeout()        │
│                                        │
│  3. Validate expectations              │
│     기대치 검증                          │
│     ├─ url_contains                    │
│     ├─ title_contains                  │
│     ├─ selector_exists                 │
│     └─ text_contains                   │
│                                        │
│  4. On failure → Recovery Pipeline     │
│     실패 시 → 복구 파이프라인            │
│                                        │
│  5. Return StepResult                  │
│     StepResult 반환                     │
└───────────────────────────────────────┘
```

### WorkflowRunner Lifecycle / WorkflowRunner 수명주기

```
run(context) called
    │
    ├─ 1. Preflight: check fingerprints against current page
    │     사전점검: 현재 페이지 대비 지문 확인
    │     (skip URL check if page hasn't navigated yet)
    │     (페이지가 아직 탐색하지 않았으면 URL 검사 건너뜀)
    │
    ├─ 2. For each step in workflow.steps:
    │     │
    │     ├─ executor.execute(step, context)
    │     │
    │     ├─ If step.ok: continue to next step
    │     │              다음 단계로 계속
    │     │
    │     ├─ If step failed & onFail == 'fallback':
    │     │   → Recovery Pipeline
    │     │
    │     ├─ If step failed & onFail == 'abort':
    │     │   → Stop workflow, return failure
    │     │     워크플로우 중단, 실패 반환
    │     │
    │     └─ If step failed & onFail == 'skip':
    │         → Continue to next step
    │           다음 단계로 계속
    │
    ├─ 3. Collect all StepResults
    │     모든 StepResult 수집
    │
    ├─ 4. Log run (JSONL + summary.md)
    │     실행 로깅
    │
    └─ 5. Return RunResult { ok, stepResults, patchApplied, durationMs }
```

---

## 5. Fallback Ladder / 폴백 래더

The fallback ladder is the heart of the system's reliability. Each level escalates in cost and non-determinism.

폴백 래더는 시스템 신뢰성의 핵심입니다. 각 레벨은 비용과 비결정론성이 증가합니다.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FALLBACK LADDER                              │
│                                                                      │
│  Level │ Strategy         │ LLM Cost │ Deterministic │ Source        │
│  ──────┼──────────────────┼──────────┼───────────────┼─────────────  │
│   1    │ Cached action    │ Free     │ Yes           │ actions.json  │
│   2    │ Playwright locator│ Free    │ Yes           │ selectors.json│
│   3    │ Stagehand observe│ 1 call   │ No            │ Live page     │
│   4    │ Healing memory   │ Free     │ Yes           │ Local store   │
│   5    │ Authoring patch  │ 1+ calls │ No            │ Python API    │
│   6    │ Human checkpoint │ Free     │ No            │ User input    │
│                                                                      │
│  Cost increases →                                                    │
│  Determinism decreases →                                             │
│  비용 증가 →                                                          │
│  결정론성 감소 →                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Level 1: Cached Action / 캐시된 액션

```typescript
// actions.json에서 targetKey로 ActionRef 조회
const actionEntry = recipe.actions[step.targetKey];
const result = await stagehandEngine.act(actionEntry.preferred);
// Stagehand replays the cached action without LLM
// Stagehand가 LLM 없이 캐시된 액션을 재생
```

### Level 2: Playwright Strict Locator / Playwright 엄격 로케이터

```typescript
// selectors.json에서 폴백 셀렉터 조회
const selectorEntry = recipe.selectors[step.targetKey];
// Try primary, then each fallback
// primary 시도, 그 다음 각 fallback
for (const selector of [selectorEntry.primary, ...selectorEntry.fallbacks]) {
  const result = await playwrightEngine.act({ selector, method: 'click', ... });
  if (result) return success;
}
```

### Level 3: Stagehand Observe Refresh / Stagehand Observe 새로고침

```typescript
// Re-discover the action on the live page
// 라이브 페이지에서 액션 재발견
const candidates = await stagehandEngine.observe(
  actionEntry.instruction,
  scope  // Optional DOM scope to narrow search / 선택적 DOM 범위
);
// candidates is ActionRef[] — try each
```

### Level 4: Healing Memory / 힐링 메모리

```typescript
const suggestion = healingMemory.suggest(step.targetKey);
if (suggestion && suggestion.confidence > 0.7) {
  const result = await engine.act(suggestion.action);
  if (result) {
    healingMemory.record(step.targetKey, suggestion.selector, suggestion.action, evidence);
    return success;
  }
}
```

### Level 5: Authoring Patch / 오소링 패치

```typescript
const patch = await authoringClient.planPatch({
  requestId: uuid(),
  errorType: classified.type,
  failedSelector: step.targetKey,
  url: await engine.currentUrl(),
  title: await engine.currentTitle(),
  domSnippet: '...',
});

// Classify and apply
const severity = classifyPatch(patch); // 'minor' | 'major'
if (severity === 'minor') {
  applyPatch(recipe, patch);
} else {
  const approved = await checkpoint.approve(patch, screenshot);
  if (approved) applyPatch(recipe, patch);
}
```

### Level 6: Human Checkpoint / 사람 체크포인트

```typescript
const screenshot = await engine.screenshot();
const approved = await checkpoint.approve({
  message: `Step "${step.id}" failed after all recovery attempts`,
  screenshot,
  options: ['GO (skip and continue)', 'NOT GO (abort workflow)'],
});
```

---

## 6. Recovery Pipeline / 복구 파이프라인

### Pipeline Orchestration / 파이프라인 오케스트레이션

```typescript
class RecoveryPipeline {
  async recover(
    step: WorkflowStep,
    error: ClassifiedError,
    context: RecoveryContext,
  ): Promise<RecoveryResult> {
    // Try each level in order / 각 레벨을 순서대로 시도
    for (const strategy of this.strategies) {
      if (this.budgetGuard.canAfford(strategy.cost)) {
        const result = await strategy.attempt(step, error, context);
        if (result.recovered) {
          this.healingMemory.record(...);
          return result;
        }
      }
    }
    return { recovered: false, exhausted: true };
  }
}
```

### Error Classification / 에러 분류

```typescript
type ErrorType =
  | 'TargetNotFound'      // Selector doesn't exist in DOM / DOM에 셀렉터 없음
  | 'NotActionable'       // Element exists but can't be acted on / 요소 존재하나 액션 불가
  | 'ExpectationFailed'   // Step succeeded but post-condition unmet / 단계 성공하나 사후조건 미충족
  | 'ExtractionEmpty'     // extract() returned nothing / extract()가 빈 결과 반환
  | 'CanvasDetected'      // Non-DOM surface found / 비DOM 서피스 발견
  | 'CaptchaOr2FA';       // Human intervention needed / 사람 개입 필요
```

### Error → Strategy Mapping / 에러 → 전략 매핑

| ErrorType | Recovery Strategy (EN) | 복구 전략 (KR) |
|-----------|------------------------|---------------|
| TargetNotFound | Locator fallback → observe → healing → patch(generate alternative selectors) | 로케이터 폴백 → observe → 힐링 → 패치(대체 셀렉터 생성) |
| NotActionable | Method fallback chain (click → focus+enter → hover+click) | 메서드 폴백 체인 |
| ExpectationFailed | URL/title expectation update via patch | URL/제목 기대치 패치 업데이트 |
| ExtractionEmpty | Broaden extraction scope → patch selectors | 추출 범위 확대 → 셀렉터 패치 |
| CanvasDetected | Network parse → CV → LLM (special surface chain) | 네트워크 파싱 → CV → LLM |
| CaptchaOr2FA | Immediate human checkpoint | 즉시 사람 체크포인트 |

---

## 7. Patch Contract / 패치 계약

### Allowed Operations / 허용된 연산

The LLM patch contract (Blueprint §8) strictly limits what patches can do:
LLM 패치 계약(블루프린트 §8)은 패치가 할 수 있는 작업을 엄격히 제한합니다:

| Path Pattern | Allowed Ops | Description (EN) | 설명 (KR) |
|-------------|-------------|-------------------|-----------|
| `actions.*` | replace, add | Update cached actions | 캐시된 액션 업데이트 |
| `selectors.*` | replace, add | Update fallback selectors | 폴백 셀렉터 업데이트 |
| `workflow.steps[].expect` | replace | Update expectations | 기대치 업데이트 |
| `policies.*` | replace | Update selection policies | 선택 정책 업데이트 |

**Not allowed / 허용되지 않음:**
- Adding or removing workflow steps / 워크플로우 단계 추가 또는 제거
- Changing step operations / 단계 연산 변경
- Modifying fingerprints / 지문 수정
- Any operation outside recipe files / 레시피 파일 외부의 모든 연산

### Patch Input Minimization / 패치 입력 최소화

To minimize token usage, the system sends only essential context to the Python service:
토큰 사용을 최소화하기 위해 시스템은 필수 컨텍스트만 Python 서비스에 전송합니다:

```
Sent / 전송:                          NOT sent / 전송 안 함:
├─ errorType                          ├─ Full DOM tree
├─ failedSelector                     ├─ Conversation history
├─ current URL + title                ├─ Previous run logs
├─ DOM snippet (failed area only)     ├─ Other recipe files
└─ 1 screenshot (when needed)         └─ User credentials
```

### Patch Classification / 패치 분류

```typescript
function classifyPatch(patch: PatchPayload): 'minor' | 'major' {
  for (const op of patch.ops) {
    // Major if touching workflow structure
    if (op.path.startsWith('workflow.')) return 'major';
    // Major if removing anything
    if (op.op === 'remove') return 'major';
  }
  // Selector/action updates are minor
  return 'minor';
}

// Minor → auto-apply, no human approval
// Major → require GO/NOT GO checkpoint
// 마이너 → 자동 적용, 사람 승인 불필요
// 메이저 → GO/NOT GO 체크포인트 필요
```

---

## 8. Python Authoring Service / Python 오소링 서비스

### Service Architecture / 서비스 아키텍처

```
FastAPI Application
    │
    ├── /compile-intent (POST)
    │   └── IntentToWorkflow DSPy program
    │       ├── Parse procedure text into steps
    │       ├── Generate actions, selectors, fingerprints
    │       └── Fallback: rule-based pattern matching
    │
    ├── /plan-patch (POST)
    │   └── PatchPlanner DSPy program
    │       ├── Analyze error context
    │       ├── Select patch strategy by errorType
    │       ├── Generate patch operations
    │       └── Validate against §8 contract
    │
    ├── /optimize-profile (POST)
    │   └── GEPA Optimizer
    │       ├── Load task specs bank
    │       ├── Run optimization loop
    │       ├── Evaluate with harness
    │       └── Promote if score > 0.82
    │
    └── /profiles/:id (GET)
        └── ProfilesRepo file storage
```

### Patch Generation Strategies / 패치 생성 전략

```python
class PatchGenerator:
    strategies = {
        'TargetNotFound': TargetNotFoundStrategy,
        'ExpectationFailed': ExpectationFailedStrategy,
        'ExtractionEmpty': ExtractionEmptyStrategy,
        'NotActionable': NotActionableStrategy,
    }

    def generate(self, error_type: str, context: dict) -> PatchPayload:
        strategy = self.strategies[error_type]
        return strategy.generate(context)
```

#### TargetNotFound Strategy

```
Input: failed selector + DOM snippet
  │
  ├─ Extract all interactive elements from DOM
  ├─ Score by similarity to original selector
  ├─ Generate alternative selectors (CSS, text, role)
  └─ Return: selectors.replace or actions.replace patch
```

#### ExpectationFailed Strategy

```
Input: expected URL/title + actual URL/title
  │
  ├─ Analyze URL pattern change (e.g., www.site.com → site.com)
  ├─ Generate updated expectation
  └─ Return: workflow.steps[n].expect.replace patch
```

#### ExtractionEmpty Strategy

```
Input: failed extraction scope + DOM snippet
  │
  ├─ Broaden CSS scope (e.g., "#narrow" → ".container")
  ├─ Try removing scope entirely
  └─ Return: selectors.replace with broader scope
```

#### NotActionable Strategy

```
Input: failed method + element info
  │
  ├─ Generate method fallback chain:
  │   click → focus + enter
  │   fill  → click + type
  │   select → click option
  └─ Return: actions.replace with alternative method
```

### Patch Validation / 패치 검증

```python
class PatchValidator:
    ALLOWED_PATHS = {
        'actions': {'replace', 'add'},
        'selectors': {'replace', 'add'},
        'workflow.steps': {'replace'},  # only .expect sub-path
        'policies': {'replace'},
    }

    def validate(self, patch: PatchPayload) -> bool:
        for op in patch.ops:
            root = op.path.split('.')[0]
            if root not in self.ALLOWED_PATHS:
                raise ValidationError(f"Path {op.path} not allowed")
            if op.op not in self.ALLOWED_PATHS[root]:
                raise ValidationError(f"Op {op.op} not allowed on {root}")
        return True
```

---

## 9. DSPy & GEPA / DSPy와 GEPA

### DSPy Program Architecture / DSPy 프로그램 아키텍처

```
┌─────────────────────────────────────────────┐
│ DSPy Program                                 │
│                                              │
│  ┌─────────────┐    ┌──────────────────┐     │
│  │ Signature    │───►│ ChainOfThought   │     │
│  │ (typed I/O)  │    │ or Predict       │     │
│  └─────────────┘    └──────────────────┘     │
│                            │                  │
│                            ▼                  │
│                     ┌──────────────────┐      │
│                     │ LLM Call         │      │
│                     └──────────────────┘      │
│                            │                  │
│                            ▼                  │
│                     ┌──────────────────┐      │
│                     │ Output parsing   │      │
│                     │ + validation     │      │
│                     └──────────────────┘      │
│                                              │
│  Fallback: rule-based when no LLM configured │
│  폴백: LLM 미설정 시 규칙 기반               │
└─────────────────────────────────────────────┘
```

#### IntentToWorkflow Signature

```python
class IntentToWorkflowSignature(dspy.Signature):
    """Convert a user's goal and procedure into a structured workflow."""

    goal: str = dspy.InputField(desc="What the user wants to achieve")
    domain: str = dspy.InputField(desc="Target website domain")
    procedure: str = dspy.InputField(desc="Step-by-step procedure text")

    workflow_json: str = dspy.OutputField(desc="Complete workflow.json")
    actions_json: str = dspy.OutputField(desc="Initial actions.json")
    selectors_json: str = dspy.OutputField(desc="Fallback selectors.json")
```

#### PatchPlanner Signature

```python
class PatchPlannerSignature(dspy.Signature):
    """Generate a minimal JSON patch to fix a workflow step failure."""

    error_type: str = dspy.InputField(desc="Classification of the error")
    failed_selector: str = dspy.InputField(desc="The selector that failed")
    current_url: str = dspy.InputField(desc="Current page URL")
    dom_snippet: str = dspy.InputField(desc="Relevant DOM fragment")

    patch_ops: str = dspy.OutputField(desc="JSON array of patch operations")
    reason: str = dspy.OutputField(desc="Human-readable explanation")
```

### GEPA Self-Improving Loop / GEPA 자기 개선 루프

GEPA (Generate → Evaluate → Promote → Archive) optimizes DSPy programs offline.
GEPA(생성 → 평가 → 승격 → 보관)는 DSPy 프로그램을 오프라인으로 최적화합니다.

```
┌─────────────────────────────────────────────────────┐
│                    GEPA Loop                         │
│                                                      │
│   1. Generate: Run DSPy program on task specs bank   │
│      생성: 태스크 스펙 뱅크에서 DSPy 프로그램 실행    │
│                                                      │
│   2. Evaluate: Score outputs with eval harness       │
│      평가: 평가 하네스로 출력 점수 산정               │
│      ┌──────────────────────────────────┐            │
│      │ Score = 0.45 × dry_run_success   │            │
│      │       + 0.25 × schema_valid      │            │
│      │       + 0.20 × determinism       │            │
│      │       - 0.10 × cost              │            │
│      └──────────────────────────────────┘            │
│                                                      │
│   3. Promote: If score ≥ 0.82, save as new profile   │
│      승격: 점수 ≥ 0.82이면 새 프로필로 저장           │
│                                                      │
│   4. Archive: Store evaluation results for analysis  │
│      보관: 분석을 위해 평가 결과 저장                 │
│                                                      │
│   Repeat until convergence or max iterations         │
│   수렴 또는 최대 반복까지 반복                        │
└─────────────────────────────────────────────────────┘
```

#### Scoring Breakdown / 점수 분해

| Factor | Weight | Measures (EN) | 측정 (KR) |
|--------|--------|---------------|-----------|
| dry_run_success | 0.45 | Does the generated recipe parse and structurally validate? | 생성된 레시피가 파싱되고 구조적으로 유효한가? |
| schema_valid | 0.25 | Does output match Pydantic/Zod schemas exactly? | 출력이 Pydantic/Zod 스키마에 정확히 일치하는가? |
| determinism | 0.20 | Does same input produce same output across runs? | 같은 입력이 실행 간 같은 출력을 생성하는가? |
| cost | -0.10 | Penalty for LLM token usage | LLM 토큰 사용에 대한 페널티 |

---

## 10. Special Surface Handling / 특수 서피스 처리

For pages with non-DOM content (canvas games, PDF viewers, SVG charts), the standard selector-based approach fails. The system uses a cost-ordered chain:

비DOM 콘텐츠가 있는 페이지(캔버스 게임, PDF 뷰어, SVG 차트)에서는 표준 셀렉터 기반 접근이 실패합니다. 시스템은 비용 순서 체인을 사용합니다:

```
Canvas/Special Surface Detected
    │
    ├─ 1. Network Parser (FREE)
    │     Intercept JSON responses from XHR/fetch
    │     XHR/fetch의 JSON 응답을 인터셉트
    │     → If data found, use it directly
    │
    ├─ 2. CV Engine (CHEAP)
    │     Screenshot + template matching
    │     스크린샷 + 템플릿 매칭
    │     → Find visual elements by pixel comparison
    │
    └─ 3. LLM Vision (EXPENSIVE, last resort)
        Send screenshot to vision model
        스크린샷을 비전 모델에 전송
        → Only if levels 1-2 fail
```

### Canvas Detection / 캔버스 감지

```typescript
class CanvasDetector {
  detect(page: Page): Promise<SurfaceType[]> {
    // Checks for:
    return [
      'canvas',       // <canvas> elements
      'iframe',       // Cross-origin iframes
      'shadow-dom',   // Shadow DOM roots
      'pdf-embed',    // <embed type="application/pdf">
      'svg',          // Complex SVG graphics
    ];
  }
}
```

### Network Parser / 네트워크 파서

```typescript
class NetworkParser {
  // Intercept all JSON responses during step execution
  // 단계 실행 중 모든 JSON 응답을 인터셉트
  async captureJsonResponses(
    page: Page,
    action: () => Promise<void>,
  ): Promise<JsonResponse[]> {
    const responses: JsonResponse[] = [];
    page.on('response', async (response) => {
      if (response.headers()['content-type']?.includes('json')) {
        responses.push(await response.json());
      }
    });
    await action();
    return responses;
  }
}
```

### CV Engine / CV 엔진

```typescript
class CVEngine {
  // Pure-buffer PNG analysis without external libraries
  // 외부 라이브러리 없이 순수 버퍼 PNG 분석
  async templateMatch(
    screenshot: Buffer,
    template: Buffer,
    threshold: number,
  ): Promise<{ x: number; y: number; confidence: number } | null>;

  async findText(
    screenshot: Buffer,
    text: string,
  ): Promise<{ x: number; y: number } | null>;
}
```

---

## 11. Memory Systems / 메모리 시스템

### Healing Memory / 힐링 메모리

```
┌─────────────────────────────────────────────────────────┐
│ HealingMemory                                            │
│                                                          │
│  Storage: Map<targetKey, HealingRecord[]>                │
│                                                          │
│  HealingRecord:                                          │
│  ├─ selector: string                                     │
│  ├─ action: ActionRef                                    │
│  ├─ successCount: number                                 │
│  ├─ failureCount: number                                 │
│  ├─ confidence: successCount / (successCount + failCount)│
│  ├─ evidence: HealingEvidence                            │
│  │   ├─ url: string                                      │
│  │   ├─ originalSelector: string                         │
│  │   └─ errorType: ErrorType                             │
│  └─ lastUsed: Date                                       │
│                                                          │
│  Rules:                                                  │
│  ├─ suggest() only returns if confidence > threshold     │
│  ├─ record() requires evidence (no evidence = no record) │
│  ├─ recordFailure() decreases confidence                 │
│  └─ prune() removes low-confidence and old entries       │
│                                                          │
│  규칙:                                                    │
│  ├─ suggest()는 신뢰도 > 임계값일 때만 반환              │
│  ├─ record()는 증거 필요 (증거 없음 = 기록 없음)        │
│  ├─ recordFailure()는 신뢰도를 감소                      │
│  └─ prune()는 낮은 신뢰도와 오래된 항목 제거             │
└─────────────────────────────────────────────────────────┘
```

### Auth Profile Manager / 인증 프로필 관리자

```
┌─────────────────────────────────────────────────────┐
│ AuthProfileManager                                   │
│                                                      │
│  Profile:                                            │
│  ├─ id: string                                       │
│  ├─ domain: string                                   │
│  ├─ credentials: encrypted                           │
│  ├─ sessionState: cookies + localStorage             │
│  ├─ expiresAt: Date                                  │
│  └─ loginWorkflowId: string (reference to recipe)    │
│                                                      │
│  Operations:                                         │
│  ├─ verify(): Check if session is still valid        │
│  │            세션이 아직 유효한지 확인                │
│  ├─ refresh(): Re-run login workflow to get new session│
│  │             로그인 워크플로우 재실행으로 새 세션 취득│
│  ├─ rotate(): Switch to next available profile       │
│  │            다음 사용 가능한 프로필로 전환           │
│  └─ isExpired(): Check expiry timestamp              │
│                  만료 타임스탬프 확인                  │
└─────────────────────────────────────────────────────┘
```

---

## 12. Metrics & SLOs / 메트릭과 SLO

### Per-Run Metrics / 실행당 메트릭

```typescript
interface RunMetrics {
  runId: string;
  domain: string;
  flow: string;
  version: string;
  startedAt: string;
  durationMs: number;
  stepsTotal: number;
  stepsPassed: number;
  stepsFailed: number;
  llmCalls: number;
  authoringCalls: number;
  promptCharsUsed: number;
  patchesApplied: { minor: number; major: number };
  healingMemoryHits: number;
  fallbackLadderMaxLevel: number;  // Highest level reached (1-6) / 도달한 최고 레벨
  success: boolean;
}
```

### SLO Aggregation / SLO 집계

```typescript
class MetricsAggregator {
  computeSLOs(runs: RunMetrics[]): SLOReport {
    return {
      successRate: passed / total,
      avgLlmCallsPerRun: totalLlmCalls / total,
      secondRunSuccessRate: ...,     // Target: ≥ 95%
      postPatchRecoveryRate: ...,    // Target: ≥ 80%
      avgDurationMs: ...,
      patchOccurrenceRate: ...,
      sloCompliance: {
        llmCallsPerRun: avgLlmCalls <= 0.2,
        secondRunSuccess: secondRunRate >= 0.95,
        postPatchRecovery: recoveryRate >= 0.80,
      },
    };
  }
}
```

### Reporting / 리포팅

The reporter generates both JSON (machine-readable) and Markdown (human-readable) dashboards:
리포터는 JSON(기계 판독 가능)과 Markdown(사람 판독 가능) 대시보드를 모두 생성합니다:

```markdown
# Metrics Report — example.com/basic

## SLO Compliance
| SLO | Target | Actual | Status |
|-----|--------|--------|--------|
| LLM calls/run | ≤ 0.2 | 0.05 | PASS |
| 2nd run success | ≥ 95% | 98% | PASS |
| Post-patch recovery | ≥ 80% | 85% | PASS |

## Recent Runs
| Run ID | Duration | Steps | LLM Calls | Result |
|--------|----------|-------|-----------|--------|
| run-001 | 4.2s | 4/4 | 0 | SUCCESS |
| run-002 | 62.1s | 3/4 | 1 | SUCCESS (patched) |
```

---

## 13. Logging & Tracing / 로깅과 트레이싱

### JSONL Run Log / JSONL 실행 로그

Each step writes one line to `logs.jsonl`:
각 단계는 `logs.jsonl`에 한 줄씩 기록합니다:

```jsonl
{"ts":"2026-02-21T00:00:01Z","step":"open","op":"goto","ok":true,"durationMs":1200}
{"ts":"2026-02-21T00:00:02Z","step":"verify_page","op":"checkpoint","ok":true,"durationMs":50}
{"ts":"2026-02-21T00:00:03Z","step":"click_link","op":"act_cached","ok":true,"durationMs":800,"fallbackLevel":1}
{"ts":"2026-02-21T00:00:04Z","step":"verify_nav","op":"checkpoint","ok":true,"durationMs":30}
```

### Summary Writer / 요약 작성기

```markdown
# Run Summary
- Goal: basic (example.com)
- Result: Success
- Duration: 00m 04s
- LLM Calls: 0
- Steps: 4/4 passed

## Key Events
- All steps completed successfully

## Version
- Input recipe: v001
- No patches applied
```

### Trace Bundler / 트레이스 번들러

```typescript
interface TraceBundle {
  runId: string;
  steps: TraceStep[];
  screenshots: { stepId: string; buffer: Buffer }[];
  domSnapshots: { stepId: string; html: string }[];
  networkLog: { url: string; status: number; body?: unknown }[];
}
```

### Trace-Based Regression / 트레이스 기반 회귀

```
Recorded trace (from successful run)
기록된 트레이스 (성공적인 실행에서)
    │
    ▼
┌───────────────────────────────────┐
│ TraceReplayer                      │
│                                    │
│  For each step in trace:           │
│  ├─ Execute step                   │
│  ├─ Compare result with recorded   │
│  │   결과를 기록과 비교              │
│  ├─ If match: continue             │
│  └─ If mismatch: flag regression   │
│                  회귀 플래그         │
│                                    │
│  Output: regression report (MD)    │
│  출력: 회귀 리포트 (MD)             │
└───────────────────────────────────┘
```

---

## 14. Block Registry / 블록 레지스트리

Workflow Blocks are reusable, parameterized step templates. They enable recipe authors to use high-level building blocks instead of raw step definitions.

워크플로우 블록은 재사용 가능하고 매개변수화된 단계 템플릿입니다. 레시피 작성자가 원시 단계 정의 대신 고수준 빌딩 블록을 사용할 수 있게 합니다.

### Block Interface / 블록 인터페이스

```typescript
interface WorkflowBlock {
  name: string;
  description: string;
  parameters: ParameterSchema[];
  validate(params: Record<string, unknown>): ValidationResult;
  expand(params: Record<string, unknown>): WorkflowStep[];
}
```

### Built-in Blocks / 내장 블록

| Block | Parameters | Expands To (EN) | 확장 결과 (KR) |
|-------|------------|-----------------|---------------|
| `navigation` | url, waitFor? | goto + optional wait step | goto + 선택적 대기 단계 |
| `action` | targetKey, method, args? | act_cached with fallback config | 폴백 설정이 있는 act_cached |
| `extract` | schema, scope? | extract with scope narrowing | 범위 축소가 있는 extract |
| `validation` | expectations[] | checkpoint with multiple expects | 다중 기대치가 있는 checkpoint |

### Registry Usage / 레지스트리 사용

```typescript
const registry = new BlockRegistry();

// Register builtins / 내장 블록 등록
registry.register(new NavigationBlock());
registry.register(new ActionBlock());
registry.register(new ExtractBlock());
registry.register(new ValidationBlock());

// Expand a block into steps / 블록을 단계로 확장
const steps = registry.expand('navigation', {
  url: 'https://example.com',
  waitFor: 2000,
});
// Returns: [
//   { id: 'nav-goto', op: 'goto', args: { url: '...' } },
//   { id: 'nav-wait', op: 'wait', args: { ms: 2000 } },
// ]
```

---

## 15. Security Considerations / 보안 고려사항

### Credential Handling / 자격 증명 처리

- Credentials are stored in auth profiles, not in recipe files
  자격 증명은 레시피 파일이 아닌 인증 프로필에 저장됩니다
- Template variables (`{{vars.password}}`) are resolved at runtime only
  템플릿 변수는 런타임에만 해석됩니다
- Credentials never appear in logs or summaries
  자격 증명은 로그나 요약에 나타나지 않습니다
- `.env` files are excluded from git via `.gitignore`
  `.env` 파일은 `.gitignore`를 통해 git에서 제외됩니다

### Patch Safety / 패치 안전성

- All patches are validated against the §8 contract before application
  모든 패치는 적용 전에 §8 계약에 대해 검증됩니다
- Major patches require human approval
  메이저 패치는 사람의 승인이 필요합니다
- Patch operations cannot execute arbitrary code
  패치 연산은 임의의 코드를 실행할 수 없습니다
- Recipe versions are immutable (patches create new versions)
  레시피 버전은 불변입니다 (패치가 새 버전을 생성)

### Input Validation / 입력 검증

- All HTTP inputs validated by Pydantic (Python) and Zod (Node)
  모든 HTTP 입력은 Pydantic(Python)과 Zod(Node)로 검증됩니다
- DOM snippets are size-limited before sending to Python service
  DOM 스니펫은 Python 서비스로 전송하기 전에 크기가 제한됩니다
- requestId enables idempotent retries without side effects
  requestId로 부작용 없는 멱등 재시도가 가능합니다

### Browser Isolation / 브라우저 격리

- Each workflow run gets a fresh browser context
  각 워크플로우 실행은 새로운 브라우저 컨텍스트를 받습니다
- Auth sessions are isolated per profile
  인증 세션은 프로필별로 격리됩니다
- Screenshots are stored locally, never sent to external services (except LLM when needed)
  스크린샷은 로컬에 저장되며 외부 서비스로 전송되지 않습니다 (필요시 LLM 제외)

---

## 16. Module Dependency Map / 모듈 의존성 맵

```
                          types/
                            │
                   ┌────────┼────────┐
                   │        │        │
                schemas/  recipe/  engines/
                   │        │        │
                   └────┬───┘        │
                        │            │
                   runner/ ──────────┘
                     │  │
              ┌──────┘  └──────┐
              │                │
         exception/      memory/
              │                │
              └────────┬───────┘
                       │
                  logging/
                       │
              ┌────────┼────────┐
              │        │        │
          metrics/  blocks/  testing/
              │        │        │
              └────────┼────────┘
                       │
              authoring-client/
                       │
                       ▼
              Python Authoring Service
```

### Import Rules / 임포트 규칙

| Module | Can Import | Cannot Import |
|--------|-----------|---------------|
| types/ | (none) | everything else |
| schemas/ | types/ | runner/, engines/ |
| recipe/ | types/, schemas/ | runner/, engines/ |
| engines/ | types/ | runner/, recipe/ |
| runner/ | types/, schemas/, recipe/, engines/, exception/, memory/ | metrics/, blocks/ |
| exception/ | types/ | runner/, engines/ |
| memory/ | types/ | runner/ |
| logging/ | types/ | runner/ |
| metrics/ | types/ | runner/ |
| blocks/ | types/, schemas/ | runner/ |
| testing/ | types/, logging/ | runner/ |
| authoring-client/ | types/, schemas/ | runner/ |

---

## Appendix A: File Inventory / 파일 목록

### Node Runtime (57 source files, 501 unit tests)

| Directory | Files | Lines (approx) | Purpose (EN) | 용도 (KR) |
|-----------|-------|-----------------|--------------|-----------|
| types/ | 10 | ~300 | Type definitions | 타입 정의 |
| schemas/ | 7 | ~400 | Zod validators | Zod 검증기 |
| recipe/ | 4 | ~350 | Recipe loading, templating, versioning | 레시피 로딩, 템플릿, 버전 관리 |
| engines/ | 8 | ~600 | Browser engines + special surfaces | 브라우저 엔진 + 특수 서피스 |
| runner/ | 7 | ~800 | Workflow execution + recovery | 워크플로우 실행 + 복구 |
| exception/ | 2 | ~200 | Error classification + routing | 에러 분류 + 라우팅 |
| logging/ | 3 | ~300 | JSONL, summary, trace | 로깅, 요약, 트레이스 |
| memory/ | 2 | ~350 | Healing memory + auth profiles | 힐링 메모리 + 인증 프로필 |
| metrics/ | 4 | ~400 | Collection, aggregation, reporting | 수집, 집계, 리포팅 |
| blocks/ | 6 | ~350 | Block registry + 4 builtins | 블록 레지스트리 + 4 내장 |
| testing/ | 2 | ~250 | Trace replay + regression | 트레이스 재생 + 회귀 |
| authoring-client/ | 4 | ~300 | Python service HTTP client | Python 서비스 HTTP 클라이언트 |

### Python Authoring Service (25 source files, 185 unit tests)

| Directory | Files | Lines (approx) | Purpose (EN) | 용도 (KR) |
|-----------|-------|-----------------|--------------|-----------|
| api/ | 5 | ~300 | REST endpoints | REST 엔드포인트 |
| dspy_programs/ | 5 | ~400 | DSPy AI programs | DSPy AI 프로그램 |
| gepa/ | 4 | ~350 | Self-improving optimizer | 자기 개선 옵티마이저 |
| services/ | 3 | ~300 | Patch generation + validation | 패치 생성 + 검증 |
| storage/ | 3 | ~200 | File-based storage | 파일 기반 스토리지 |
| schemas/ | 3 | ~200 | Pydantic models | Pydantic 모델 |

---

## Appendix B: Technology Stack / 기술 스택

| Component | Technology | Version | Purpose (EN) | 용도 (KR) |
|-----------|-----------|---------|--------------|-----------|
| Runtime | TypeScript | 5.7+ | Primary language | 주요 언어 |
| Browser | Playwright | 1.50+ | Browser automation | 브라우저 자동화 |
| AI Engine | Stagehand | 3.0+ | Observe/act/extract with LLM | LLM 기반 관찰/액션/추출 |
| Validation (Node) | Zod | 3.24+ | Runtime type validation | 런타임 타입 검증 |
| Service | FastAPI | 0.115+ | Python REST API | Python REST API |
| Validation (Python) | Pydantic | 2.0+ | Request/response validation | 요청/응답 검증 |
| AI Programs | DSPy | 2.6+ | Prompt optimization | 프롬프트 최적화 |
| Test (Node) | Vitest | 3.0+ | Unit testing | 단위 테스트 |
| Test (Python) | pytest | 8.0+ | Unit testing | 단위 테스트 |
| Build | tsx | 4.19+ | TypeScript execution | TypeScript 실행 |
