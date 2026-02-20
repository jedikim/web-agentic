# Web-Agentic Platform — Full Implementation Report

**Date:** 2026-02-21
**Repository:** https://github.com/jedikim/web-agentic

---

## Overview

Operational web automation platform built with a deterministic-first architecture:
- **Node Runtime** (TypeScript): Executes workflow recipes via cached Stagehand actions with Playwright fallback
- **Python Authoring Service** (FastAPI): Generates and patches recipes via DSPy + GEPA

---

## Phase Completion Summary

| Phase | Description | Status | Tests |
|-------|-------------|--------|-------|
| Phase 1 | Deterministic Core MVP | COMPLETE | 289 |
| Phase 2 | Patch-only Recovery | COMPLETE | +208 |
| Phase 3 | DSL Authoring Auto-Improve | COMPLETE | +169 |
| Phase 4 | Special Surface Handling | COMPLETE | +93 |
| Phase 5 | OSS Pattern Hardening | COMPLETE | +119 |
| E2E Testing | Real Browser + Integration | COMPLETE | +18 |
| **Total** | | **ALL COMPLETE** | **686 unit + 18 E2E** |

---

## Git History

```
<latest>  test: add E2E testing infrastructure and fix 4 bugs found during real browser testing
c6782c9d docs: add full implementation report for Phase 1-5
f2f4feb4 feat: implement Phase 4 (Special Surfaces) and Phase 5 (OSS Hardening)
73adea58 feat: implement Phase 2 (Patch Recovery) and Phase 3 (DSL Authoring)
a54a8f12 feat: implement Phase 1 Deterministic Core MVP
e5159d9e fix: add .gitignore and remove node_modules from tracking
2dcd7c26 docs: add blueprint and phase 1 implementation plan
```

---

## Phase 1: Deterministic Core MVP

**Node Runtime (TypeScript):**
- 10 type definitions (workflow, action, selector, policy, fingerprint, step-result, patch, budget, recipe)
- 7 Zod schema validators with comprehensive tests
- Recipe system: loader, template interpolation ({{vars.key}}), versioning (v001→v002), patch merger
- Browser engines: Stagehand wrapper (observe/act/extract), Playwright fallback (strict locators)
- Policy engine: hard filter + score + tie-break candidate selection
- Workflow execution: step executor with 6-level fallback ladder, runner, validator, checkpoint GO/NOT GO
- Exception classifier (6 error types) and router
- Token budget guard with usage tracking and downgrade logic
- Logging: JSONL run logger, MD summary writer, trace bundler
- Memory: healing memory store, auth profile manager
- Authoring HTTP client: compile-intent, plan-patch, profiles

**Python Authoring Service (FastAPI):**
- Pydantic schemas for recipes and patches with requestId idempotency
- 4 API endpoints: POST /compile-intent, POST /plan-patch, POST /optimize-profile, GET /profiles/:id
- DSPy program stubs for Phase 3
- Storage layer stubs for Phase 3

---

## Phase 2: Patch-only Recovery

**Node Additions:**
- Recovery pipeline orchestrating full fallback ladder: retry → observe refresh → selector fallback → healing memory → authoring patch → checkpoint
- Observe refresher for scoped action re-discovery via Stagehand observe()
- Patch workflow: minor/major classification, auto-apply minor patches, GO/NOT GO for major
- Enhanced exception router with RecoveryPlan and FailureContext
- Step executor wired to real recovery pipeline

**Python Additions:**
- Patch generator with 4 strategy patterns:
  - TargetNotFound: DOM-based alternative selector generation
  - ExpectationFailed: URL/title expectation updates
  - ExtractionEmpty: Selector scope broadening
  - NotActionable: Method fallback chain (click→focus+enter, etc.)
- Patch validator enforcing Blueprint §8 contract (allowed ops only)

---

## Phase 3: DSL Authoring Auto-Improve

**Python Additions:**
- DSPy signatures: IntentToWorkflowSignature, IntentToPolicySignature, PatchPlannerSignature
- Real DSPy programs with ChainOfThought/Predict + rule-based fallback:
  - IntentToWorkflow: procedure parser with pattern recognition
  - IntentToPolicy: constraint/preference extraction
  - PatchPlanner: DSPy-enhanced with PatchGenerator fallback
- GEPA self-improving optimizer with optimization loop
- Eval harness: weighted scoring (0.45 dry_run + 0.25 schema + 0.20 determinism - 0.10 cost)
- Promotion threshold: 0.82
- Real file-based storage for profiles and task specs
- Connected optimize-profile and profiles API endpoints

---

## Phase 4: Special Surface Handling

**Node Additions:**
- Canvas detector: identifies canvas, iframe, shadow DOM, PDF embed, SVG surfaces
- Network parser: response interception, JSON extraction (free, LLM-less)
- CV engine: pure-Buffer PNG template matching and text finding (no external libraries)
- CanvasDetected chain: network parse (free) → CV (cheap) → LLM (last resort)
- Metrics collector: per-run operational metrics tracking
- Metrics aggregator: cross-run SLO compliance
  - LLM calls/run ≤ 0.2
  - 2nd run success rate ≥ 95%
  - Post-patch recovery rate ≥ 80%
- Metrics reporter: JSON + Markdown dashboards
- File-based metrics store with filtering

---

## Phase 5: OSS Pattern Hardening

**Node Additions:**
- Auth profile manager hardening:
  - Session expiry detection
  - Auto-refresh via login workflow replay
  - Multi-profile rotation
  - Profile verification
- Workflow Block Registry:
  - Parameter validation and template expansion
  - 4 builtin blocks: navigation, action, extract, validation
- Healing memory hardening:
  - Evidence-based healing (no evidence = no healing)
  - Confidence scoring (successCount / total)
  - Failure tracking with confidence decay
  - Pruning by confidence threshold and age
- Trace bundler: structured TraceBundle packaging
- Trace replayer: step-by-step regression verification
- Regression runner: automated trace-based regression suites with Markdown reports

---

## Architecture

```
Node Runtime (Execution)          Python Authoring Service (Generation)
┌──────────────────────────┐     ┌─────────────────────────────┐
│ Workflow Runner           │     │ FastAPI                      │
│  ├─ Step Executor         │     │  ├─ POST /compile-intent     │
│  │   ├─ Stagehand Engine  │────▶│  ├─ POST /plan-patch         │
│  │   ├─ Playwright FB     │     │  ├─ POST /optimize-profile   │
│  │   ├─ Canvas Detector   │     │  └─ GET /profiles/:id        │
│  │   ├─ Network Parser    │     │                               │
│  │   ├─ CV Engine         │     │ DSPy Programs                 │
│  │   └─ Policy Engine     │     │  ├─ IntentToWorkflow          │
│  ├─ Recovery Pipeline     │     │  ├─ IntentToPolicy            │
│  ├─ Validator             │     │  └─ PatchPlanner              │
│  └─ Checkpoint (GO/NOTGO)│     │                               │
│                           │     │ GEPA Optimizer                │
│ Recipe System             │     │  ├─ Eval Harness              │
│  ├─ Loader + Versioning   │     │  └─ Scoring Functions         │
│  ├─ Template Engine       │     │                               │
│  └─ Patch Merger          │     │ Storage                       │
│                           │     │  ├─ Profiles Repo             │
│ Exception Handling        │     │  └─ Task Specs Repo           │
│  ├─ Classifier            │     └─────────────────────────────┘
│  ├─ Router                │
│  └─ Budget Guard          │
│                           │
│ Memory                    │
│  ├─ Healing Memory        │
│  └─ Auth Profile Manager  │
│                           │
│ Blocks                    │
│  ├─ Block Registry        │
│  └─ 4 Builtin Blocks     │
│                           │
│ Metrics                   │
│  ├─ Collector             │
│  ├─ Aggregator            │
│  ├─ Reporter              │
│  └─ Store                 │
│                           │
│ Testing                   │
│  ├─ Trace Replayer        │
│  └─ Regression Runner     │
│                           │
│ Logging                   │
│  ├─ Run Logger            │
│  ├─ Summary Writer        │
│  └─ Trace Bundler         │
└──────────────────────────┘
```

---

## Test Distribution

| Module | Files | Tests |
|--------|-------|-------|
| Schemas | 6 | 64 |
| Recipe | 4 | 30 |
| Engines | 8 | 73 |
| Runner | 7 | 76 |
| Exception | 3 | 56 |
| Logging | 3 | 25 |
| Memory | 2 | 52 |
| Auth Client | 3 | 15 |
| Metrics | 4 | 59 |
| Blocks | 2 | 32 |
| Testing | 2 | 21 |
| **Node Total** | **44** | **501** |
| Python API | 2 | 18 |
| Python DSPy | 2 | 66 |
| Python GEPA | 3 | 34 |
| Python Patch | 2 | 45 |
| Python Storage | 2 | 24 |
| **Python Total** | **11** | **185** |
| **Grand Total** | **55** | **686** |

---

## E2E Testing Results

Real end-to-end testing was performed against live websites using headless Chromium (Playwright). This testing phase discovered and fixed 4 bugs.

### Browser E2E Tests (5/5 passed)

| Test | Target | Duration | Result |
|------|--------|----------|--------|
| Basic navigation | example.com → IANA | 4.9s | PASS |
| Broken selector fallback | example.com (intentionally broken selector) | 62.2s | PASS (ladder recovered) |
| Form interaction | httpbin.org/forms/post | 2.6s | PASS |
| Multi-step extraction | example.com (navigate + extract + wait) | 4.6s | PASS |
| Total failure recovery | example.com (all selectors broken) | 120.6s | PASS (checkpoint recovery) |

### Node ↔ Python Integration Tests (13/13 passed)

- Compile intent endpoint: request/response round-trip
- Plan patch endpoint: 4 error types × strategy selection
- Optimize profile endpoint: GEPA loop execution
- Profiles endpoint: CRUD operations
- Error handling: timeout, invalid input, schema validation

### Bugs Found and Fixed

1. **Zod `.optional()` vs Python `null`** — Python Pydantic serializes `None` as JSON `null`, but Zod `.optional()` only accepts `undefined`. Fixed by changing to `.nullable().optional()` in 4 schema files.

2. **Preflight fingerprint on fresh page** — `preflight()` called `currentUrl()` before the first `goto`, URL is `about:blank`, fails fingerprint check. Fixed by skipping URL fingerprint checks when `hasNavigated` is false.

3. **`healingMemory.record()` wrong arity** — Phase 5 enhanced HealingMemory to require evidence (4 params), but two call sites in step-executor and recovery-pipeline still used old 3-param signature. Fixed with proper HealingEvidence objects.

4. **Stale example.com selectors** — example.com changed link text from "More information..." to "Learn more" and URL from `www.iana.org` to `iana.org`. Updated recipe selectors and actions to match.

### Test Infrastructure

- `node-runtime/e2e/run-pipeline.ts` — Full browser E2E (5 scenarios with screenshots)
- `node-runtime/e2e/run-integration.ts` — Node ↔ Python HTTP integration (13 tests)
- `node-runtime/e2e/recipes/` — Test recipes for example.com (4 variants) and httpbin.org (1 form test)
- Screenshots verified: IANA navigation, httpbin JSON response with submitted form data, multi-step workflow

---

## Key Design Decisions

1. **Deterministic-first**: Runtime executes cached actions by default, LLM only for recovery
2. **Patch-only LLM**: LLM output is always JSON patch data, never code
3. **6-level fallback ladder**: cached action → strict locator → observe → healing memory → authoring patch → checkpoint
4. **Process separation**: Node (execution speed) + Python (generation intelligence) via HTTP
5. **Evidence-based healing**: No healing without recorded evidence of why it works
6. **Canvas chain**: network parse (free) → CV (cheap) → LLM (expensive, last resort)
7. **Budget guard**: Hard limits on LLM/authoring calls, automatic downgrade
8. **Human-in-the-loop**: GO/NOT GO gates at critical points, screenshot checkpoints
