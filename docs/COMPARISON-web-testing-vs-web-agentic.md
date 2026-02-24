# web-testing vs web-agentic 비교 분석

> **목적**: 동일 도메인(적응형 웹 자동화)의 두 레포 비교 분석. 수용/개선/보류 판단.
>
> **날짜**: 2026-02-24

---

## 1. 프로젝트 개요 비교

| 항목 | web-testing (TS) | web-agentic (Python) |
|------|-----------------|---------------------|
| **언어** | TypeScript / Node.js | Python 3.11+ |
| **실행 철학** | Rule-first (결정론 우선) | LLM-First (LLM이 주체) |
| **브라우저** | Playwright (TS) | Playwright (async Python) |
| **LLM** | Gemini + OpenAI (멀티프로바이더) | Gemini only (google-genai) |
| **모델** | gemini-3.1-pro / gemini-3.0-flash / gpt-5.2-codex / gpt-5-mini | gemini-3.1-pro-preview / gemini-3-flash-preview |
| **테스트** | 140 tests (vitest) | 1207 tests (pytest) |
| **저장소** | 파일 기반 JSON | SQLite (aiosqlite) |
| **UI** | 임베디드 HTML (backend-ui, chat-ui) | React 19 + Vite + Tailwind (evolution-ui) |
| **진화 엔진** | bug/exception 트리거 + git worktree | 상태 머신 + git sandbox + SSE |
| **배포 모드** | Backend Simple(HTTP) + SDK(임베딩) + Chat Automation | FastAPI 서버 + React UI |

---

## 2. 아키텍처 철학 차이

### 2.1 실행 모델

**web-testing**: `Rule-first → Patch-only → Verify-always`
```
Workflow DSL → Deterministic Runner → (실패 시) Selector Recovery → Visual Recovery → Human Loop
```
- 워크플로우 DSL을 먼저 실행하고, 실패한 곳만 LLM에 물어봄
- LLM은 "후보 선택" / "패치 생성" 역할만 수행 (Candidate-only)
- 반복 실행할수록 LLM 호출이 줄어드는 수렴 모델

**web-agentic**: `LLM-First → Smart Caching`
```
LLM 의도 분석 → 캐시 조회 → LLM 요소 선택 → 실행 → 검증 → (실패 시) Vision → Human Handoff
```
- LLM이 처음부터 의도를 분석하고 실행 계획을 수립
- 성공한 셀렉터를 캐시하여 반복 비용 절감
- 새 사이트에서도 즉시 동작 가능 (규칙 불필요)

### 2.2 장단점 비교

| 관점 | web-testing 장점 | web-agentic 장점 |
|------|-----------------|-----------------|
| **비용** | 반복 실행 시 LLM 호출 0 | 첫 실행에서도 동작 |
| **안정성** | 결정론적 경로 우선 | LLM이 유연하게 대응 |
| **확장성** | 새 사이트마다 워크플로우 필요 | 크로스사이트 일반화 |
| **예측성** | 동일 입력 = 동일 결과 | LLM 출력 변동 가능 |
| **초기 비용** | 워크플로우 작성 필요 | ~$0.02/태스크로 즉시 시작 |

---

## 3. 모듈별 상세 비교

### 3.1 워크플로우 / 계획

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 워크플로우 DSL | JSON 기반 9개 노드 타입 (Navigate, Discover, Decide, Action, Verify, Loop, Branch, Checkpoint, Handoff) | YAML DSL (dsl_parser.py) + LLM이 동적 계획 | web-testing이 더 체계적 |
| 워크플로우 검증 | validate-workflow.ts (중복 ID, 참조 검증) | 없음 (LLM이 직접 생성) | **수용 대상** |
| 실행 경로 빌드 | build-execution-path.ts (DAG→선형) | LLM planner가 atomic 스텝 생성 | 각각 장점 있음 |
| 루프/분기 | LoopNode, BranchNode | LLM이 재계획 | web-testing이 구조적 |

### 3.2 브라우저 실행

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 액션 세트 | click, double_click, right_click, drag, hover, scroll, type, key_press, wait_for, select_option, upload_file | click, type_text, scroll + 스텔스 + 베지어 마우스 | web-agentic이 스텔스 강점 |
| 스텔스 | 없음 (anti-bot 비수용) | 3단계 JS 패치, UA 로테이션 | **web-agentic 우위** |
| 휴먼 행동 | 없음 | 베지어 마우스, 자연 타이핑, 점진 스크롤 | **web-agentic 우위** |
| 봇 감지 방어 | human handoff로 전환 | stealth + human_behavior로 회피 | 접근 방식 차이 |
| 어댑터 패턴 | DeterministicAdapter 인터페이스 | 직접 Executor 구현 | web-testing이 테스트 용이 |

### 3.3 폴백 / 복구

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 체인 | Deterministic → Selector Recovery → Visual Recovery → Human Loop | LLM → Cache → Vision → Human Handoff | 유사 |
| 셀렉터 복구 | context-reducer + patch-validator + recipe-version | FallbackRouter + LLM 재시도 | web-testing이 구조적 |
| 패치 검증 | SelectorPatch JSON 스키마 검증 | 없음 (LLM 출력 직접 사용) | **수용 대상** |
| 레시피 버전 | v001→v002 자동 증분 | 캐시 TTL 기반 | **수용 대상** |
| 재시도 정책 | shouldRetry() + maxTotalSteps | 지수 백오프 + 서킷 브레이커 | **web-agentic 우위** |
| 재계획 | 없음 | 연속 실패 시 LLM 재계획 | **web-agentic 우위** |

### 3.4 비전 시스템

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| ROI 배칭 | roi-batcher.ts (공간 그룹핑) | image_batcher.py (그리드 배칭) | 유사 |
| 컴포지트 시트 | composite-sheet.ts (jimp) | batch_vision_pipeline.py (Pillow) | 유사 |
| 반복 아이템 판단 | repeated-item-judgement.ts (YOLO→VLM 체인) | 없음 | **수용 대상** |
| 역매핑 | mapDetectionsToSourceItems() | coord_mapper.py | 유사 |
| VLM 폴백 | YOLO 신뢰도 < threshold → VLM | LLM 신뢰도 < 0.7 → YOLO/VLM | 유사 |

### 3.5 세션 관리

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 저장소 | 파일 기반 JSON | SQLite (aiosqlite) | **web-agentic 우위** |
| 멀티턴 | SessionStore + MultiTurnEngine | SessionManager + SessionDB | 유사 |
| 턴 엔진 | RuleBasedTurnEngine / GeminiTurnEngine | LLM Orchestrator | web-agentic이 강력 |
| 동시성 제어 | SessionManager (maxConcurrent) | ExecutorPool (세션 풀) | 유사 |
| SSE 스트리밍 | EventEmitter + /stream | FastAPI SSE | 유사 |

### 3.6 진화 시스템

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 트리거 | bug/exception만 (보수적) | 수동 트리거 + 자동 감지 | web-testing이 안전 |
| 격리 | git worktree | git branch sandbox | web-testing이 안전 |
| 자동 수정 | gemini-autofix.ts (diff 추출) | code_generator.py (Gemini Pro) | 유사 |
| 상태 머신 | draft→sandbox_prepared→testing→auto_fixing→awaiting_approval→promoted/rejected | PENDING→ANALYZING→GENERATING→TESTING→AWAITING_APPROVAL→MERGED/REJECTED | web-testing이 세분화 |
| 시나리오 팩 | scenario-growth.ts | scenarios API | 유사 |
| 자동 승인 | autoApprove 정책 (함수/boolean) | 없음 (항상 수동) | **수용 검토** |
| 버전 관리 | active-versions.json | version_manager.py (태깅) | 유사 |

### 3.7 SDK / 백엔드

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| SDK | WebAutomationSdk + MultiTurnAutomationSdk | WebAgent (async context manager) | 유사 |
| HTTP 모드 | Backend Simple (4888) + Chat Automation (4999) | FastAPI (8000) | web-testing이 분리 잘됨 |
| 채팅 자동화 | 풀 구현 (pause/resume/cancel/captcha/SSE/이미지 첨부) | 없음 | **수용 대상** |
| headful/headless 전환 | 메시지별 선택 가능 | 세션 생성 시 결정 | **수용 대상** |
| 이미지 첨부 | ChatMessageAttachment (upload/url/path) | 없음 | **수용 대상** |
| 자동 일시정지 | 같은 오퍼레이터의 다른 세션 자동 일시정지 | 없음 | **수용 대상** |

### 3.8 Human-in-the-Loop

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 인터페이스 | DecisionPort (go/not_go/revise/unknown) | HandoffManager | web-testing이 체계적 |
| 스크린샷 체크포인트 | evaluateCheckpoint (confidence + threshold + sensitiveAction) | 없음 | **수용 대상** |
| 플랫폼 정규화 | ChatPlatform (telegram/slack/whatsapp 등) | 없음 | **수용 대상** |
| 캡차 처리 | 전용 UI + captcha 핸들러 | Human Handoff 제네릭 | web-testing이 구체적 |
| 수정 루프 | revise → LLM 최적화 → 재실행 | 없음 | **수용 대상** |

### 3.9 학습 시스템

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 규칙 승격 | evaluateCanaryGate (회귀 체크 + 임계치) | rule_promoter.py | web-testing이 안전 |
| 적응형 컨트롤러 | adaptive-controller.ts (반복 시 자동 승격) | 없음 | **수용 대상** |
| 리플레이 저장 | replay-store.ts | 없음 | **수용 대상** |
| DSPy/GEPA | Python 서비스로 분리 설계 | dspy_optimizer.py 직접 내장 | 각각 장점 |

### 3.10 운영 / 모니터링

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 메트릭 대시보드 | metrics-dashboard.ts (성공률, 지연, 비용) | FastAPI + React UI | web-agentic이 UI 강점 |
| 회복력 오케스트레이터 | resilience-orchestrator.ts (병렬 시나리오 + 롤백) | 없음 | **수용 대상** |
| 롤백 로그 | rollback-log.ts | version_manager.py (롤백 지원) | 유사 |
| 동시성 | maxConcurrentSessions 제어 | ExecutorPool | 유사 |

### 3.11 설정 / 환경

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 멀티프로바이더 | LLM_PROVIDER=gemini\|openai, 프로바이더별 env | Gemini only | **수용 대상** |
| 모델 레지스트리 | model-registry.ts (지원 모델 목록 + 검증) | 환경변수 기본값 | **수용 대상** |
| 모델 정책 | model-policy.ts (코딩 vs 자동화 분리) | GEMINI_FLASH_MODEL / GEMINI_PRO_MODEL | 유사하지만 web-testing이 명확 |
| 환경 파싱 | loadRuntimeEnv() (타입 안전) | config.py + settings.yaml | web-agentic이 YAML 지원 |

### 3.12 문서화

| 항목 | web-testing | web-agentic | 판정 |
|------|------------|------------|------|
| 이중 언어 | 모든 문서 영어/한국어 페어 | README + EVOLUTION-ENGINE 이중 | **web-testing 우위** |
| Codex 지시서 | CODEX-RUNBOOK, CODEX-IMPLEMENTATION-PLAN 등 14개 | CLAUDE.md + agents/ | 각각 장점 |
| 실행 아티팩트 | runs/samples/ (리뷰 + 리포트) | 없음 | **수용 대상** |
| 실사용 가이드 | CODEX-PRACTICAL-USAGE, CODEX-SDK-BACKEND-USAGE | API-REFERENCE | web-testing이 상세 |

---

## 4. web-testing에만 있는 기능 (web-agentic에 없음)

### 4.1 즉시 수용 대상

| # | 기능 | 설명 | 수용 이유 | 적용 위치 |
|---|------|------|----------|----------|
| A1 | **Chat Automation Backend** | pause/resume/cancel, 캡차 핸들러, SSE 로그 스트림, headful/headless 전환, 이미지 첨부 | 실제 운영에 필수적인 UX. 현재 web-agentic의 세션 API가 이를 지원하지 않음 | `src/api/routes/sessions.py` 확장 |
| A2 | **메시지별 headful/headless 전환** | 사용자가 메시지마다 브라우저 모드 선택 | 디버깅/모니터링 유연성 | `src/api/session_manager.py` |
| A3 | **스크린샷 체크포인트** | confidence + threshold + sensitiveAction 기반 go/not_go/ask_user 판단 | 민감 액션 전 안전 게이트 | 신규: `src/core/checkpoint.py` |
| A4 | **적응형 컨트롤러** | 반복 실행 시 자동 규칙 승격, LLM 호출 점진 감소 | 비용 최적화의 핵심 | `src/learning/` 확장 |
| A5 | **리플레이 저장소** | 성공 실행 트레이스 저장 → 오프라인 리플레이 평가 | 카나리 게이트 + 회귀 테스트 | 신규: `src/learning/replay_store.py` |
| A6 | **카나리 게이트** | 회귀 체크 + 최소 개선 임계치 기반 승격 판단 | 안전한 규칙 승격 | `src/learning/rule_promoter.py` 강화 |
| A7 | **회복력 오케스트레이터** | 병렬 시나리오 실행 + 자동 복구 + 롤백 로그 | 대규모 시나리오 실행에 필수 | 신규: `src/ops/resilience.py` |

### 4.2 수용 검토 대상 (부분 수용)

| # | 기능 | 설명 | 검토 사유 | 적용 방안 |
|---|------|------|----------|----------|
| B1 | **멀티 LLM 프로바이더** | Gemini + OpenAI 지원, 프로바이더별 env 분리 | OpenAI 추가 시 비용 모델 다변화 가능. 하지만 현재 Gemini 전용 설계와 충돌 | `src/ai/model_registry.py` 신규 + planner 추상화 |
| B2 | **워크플로우 DSL 검증** | 노드 ID 중복, 참조 유효성, 필수 필드 검증 | web-agentic은 LLM이 동적 생성하므로 별도 검증기 필요 | `src/workflow/dsl_parser.py` 확장 |
| B3 | **패치 검증기** | LLM이 생성한 패치의 스키마/형식 검증 | LLM 출력 신뢰도 향상에 유용. 현재 구조화 출력으로 일부 커버 | `src/ai/patch_system.py` 강화 |
| B4 | **셀렉터 레시피 버전** | v001→v002 자동 증분 + 패치 이력 | 셀렉터 캐시에 버전 추적 추가 | `src/learning/pattern_db.py` 확장 |
| B5 | **반복 아이템 판단 체인** | composite sheet → YOLO → VLM 폴백 → 역매핑 | 쇼핑몰 리스트 자동화에 유용. 현재 batch_vision_pipeline이 부분 커버 | `src/vision/` 확장 |
| B6 | **자동 승인 정책** | 진화 작업의 자동 승인 (함수/boolean 정책) | 편의성 증가. 하지만 현재 "사람 검토 필수" 원칙과 충돌 | `src/evolution/pipeline.py` 옵션 추가 |
| B7 | **채팅 플랫폼 정규화** | Telegram/Slack/WhatsApp 등 메시지 정규화 | 외부 연동 확장성. 하지만 현재 범위 밖 | 향후 `src/chat/` 모듈 |
| B8 | **어댑터 패턴 (Executor)** | DeterministicAdapter 인터페이스로 실행 엔진 추상화 | 테스트 용이성 향상. 현재 Executor가 직접 구현 | `src/core/executor.py` 리팩토링 |

### 4.3 보류/비수용 대상

| # | 기능 | 설명 | 보류 이유 |
|---|------|------|----------|
| C1 | **Rule-first 실행 모델** | 결정론적 워크플로우 우선 실행 | web-agentic의 핵심 철학 (LLM-First)과 정면 충돌. 이미 캐시로 유사 효과 달성 |
| C2 | **파일 기반 세션 저장** | JSON 파일로 세션 저장 | SQLite가 더 안정적이고 동시성 지원 우수 |
| C3 | **TypeScript 런타임** | Node.js 기반 실행 엔진 | Python 기반으로 이미 성숙. 언어 전환 불필요 |
| C4 | **임베디드 HTML UI** | 백엔드에 HTML 직접 임베드 | React UI가 이미 더 풍부 |
| C5 | **Patch-only 제약** | LLM 출력을 JSON 패치로만 제한 | web-agentic은 구조화된 LLM 출력으로 이미 제어 중 |
| C6 | **anti-bot 비수용 방침** | 스텔스/봇 회피를 PRD에서 명시적 비수용 | web-agentic은 프로덕션 환경에서 스텔스 필수 |

---

## 5. web-agentic에만 있는 기능 (유지/강화)

| 기능 | 설명 | 중요도 |
|------|------|--------|
| **스텔스 레이어** | 3단계 JS 패치, UA 로테이션, WebGL/Canvas 위장 | 프로덕션 필수 |
| **휴먼 행동 시뮬레이션** | 베지어 마우스, 자연 타이핑, 점진 스크롤 | 프로덕션 필수 |
| **적응형 재시도 + 재계획** | 지수 백오프, 서킷 브레이커, 실패 시 재계획 | 핵심 기능 |
| **네비게이션 인텔리전스** | robots.txt, 레이트리밋, 홈페이지 워밍 | 프로덕션 필수 |
| **React UI (6페이지)** | Dashboard, Evolutions, Scenarios, Versions, Automation, Sessions | UI 강점 |
| **CAPTCHA VLM 파이프라인** | VLM으로 CAPTCHA 읽기 → LLM으로 응답 생성 | 고유 기능 |
| **SQLite 세션/진화 DB** | 동시성, 트랜잭션 안전성 | 인프라 강점 |
| **통합 설정 (YAML)** | StealthConfig, BehaviorConfig, NavigationConfig, RetryConfig | 운영 편의성 |
| **WebAgent SDK** | async context manager, 원라인 사용 | DX 강점 |
| **비용 추적** | 모델별 per-million-token 요금, 세션별 누적 | 비용 관리 |

---

## 6. 수용 시 구현 계획 (우선순위 순)

### Phase 1: Chat Automation 기능 강화 (A1, A2, A3)

**목표**: 세션 API를 Chat Automation 수준으로 업그레이드

| 파일 | 변경 |
|------|------|
| `src/api/routes/sessions.py` | pause/resume/cancel 엔드포인트 추가 |
| `src/api/session_manager.py` | ChatAutomationRunState 유사 상태 관리, headful/headless 턴별 전환, 자동 일시정지 |
| `src/core/checkpoint.py` (신규) | evaluateCheckpoint() — confidence 기반 go/not_go/ask_user |
| `src/api/models.py` | BrowserMode, RunStatus 확장 |
| `evolution-ui/src/pages/Sessions.tsx` | pause/resume/cancel UI, 캡차 입력 UI |

**예상 테스트**: ~20개

### Phase 2: 학습 시스템 강화 (A4, A5, A6)

**목표**: 반복 실행 시 LLM 호출을 점진적으로 줄이는 수렴 모델 구축

| 파일 | 변경 |
|------|------|
| `src/learning/replay_store.py` (신규) | 성공 실행 트레이스 저장/조회 |
| `src/learning/rule_promoter.py` | 카나리 게이트 추가 (회귀 체크 + 임계치) |
| `src/learning/adaptive_controller.py` (신규) | 반복 감지 → 자동 승격 → LLM 호출 축소 |
| `src/core/llm_orchestrator.py` | adaptive_controller 연결 |

**예상 테스트**: ~15개

### Phase 3: 운영 강화 (A7, B7)

**목표**: 대규모 시나리오 실행 + 복구 자동화

| 파일 | 변경 |
|------|------|
| `src/ops/resilience.py` (신규) | ResilienceOrchestrator — 병렬 시나리오 + 복구 + 롤백 |
| `src/ops/rollback_log.py` (신규) | 롤백 이력 관리 |
| `scripts/run_scenarios.py` | resilience orchestrator 연결 |

**예상 테스트**: ~10개

### Phase 4: 비전 확장 (B5)

**목표**: 반복 아이템 판단 체인 (쇼핑몰 리스트 자동화)

| 파일 | 변경 |
|------|------|
| `src/vision/repeated_item.py` (신규) | composite sheet → YOLO → VLM 폴백 → 역매핑 체인 |
| `src/vision/composite_sheet.py` (신규) | 아이템 이미지 → 그리드 합성 + 매니페스트 |
| `src/vision/image_batcher.py` | composite sheet 연동 |

**예상 테스트**: ~10개

### Phase 5: 모델 추상화 (B1, B3, B8)

**목표**: 멀티 LLM 프로바이더 지원 + 패치 검증 + Executor 추상화

| 파일 | 변경 |
|------|------|
| `src/ai/model_registry.py` (신규) | LLM 프로바이더 레지스트리 (Gemini + OpenAI) |
| `src/ai/patch_system.py` | 패치 스키마 검증 강화 |
| `src/core/executor.py` | ExecutorAdapter 인터페이스 추출 |
| `src/ai/llm_planner.py` | model_registry 연동 |

**예상 테스트**: ~12개

---

## 7. 구조적 개선 포인트

### 7.1 web-testing에서 배울 패턴

1. **어댑터 패턴**: Executor를 인터페이스로 추상화하면 테스트 시 Mock 주입이 쉬워짐
2. **이벤트 기반 상태 전파**: EventEmitter로 실시간 상태 전달 (SSE와 자연스럽게 연결)
3. **엄격한 실패 코드 분류**: FailureCode enum으로 복구 전략을 결정적으로 매핑
4. **워크플로우 검증 분리**: 실행 전 구조적 검증을 별도 함수로 분리
5. **이중 언어 문서 관행**: 모든 문서에 영어/한국어 페어 + 상호 링크

### 7.2 web-agentic이 이미 우월한 부분 (변경 불필요)

1. **LLM-First 아키텍처**: 새 사이트 일반화 능력이 Rule-first보다 우수
2. **스텔스 + 봇 방어**: web-testing은 이를 명시적 비수용으로 처리 (프로덕션에서 불리)
3. **SQLite 저장소**: 파일 기반보다 동시성, 쿼리, 트랜잭션 우수
4. **React UI**: 임베디드 HTML보다 확장 가능
5. **비용 추적**: 모델별 정밀 비용 계산
6. **적응형 재시도**: 지수 백오프 + 서킷 브레이커 + 재계획

---

## 8. 요약

### Wave 1 수용 완료 (9개 기능, 110 tests)

1. **Chat Automation Backend** — pause/resume/cancel/captcha/이미지첨부/headful 전환 ✅
2. **스크린샷 체크포인트** — confidence 기반 go/not_go/ask_user 판정 ✅
3. **적응형 컨트롤러 + 리플레이 저장소** — 반복 실행 비용 수렴 모델 ✅
4. **카나리 게이트** — 회귀 체크 기반 규칙 승격 게이트 ✅
5. **회복력 오케스트레이터** — 병렬 시나리오 실행 + 복구 + 롤백 ✅
6. **멀티 LLM 프로바이더** — ILLMProvider Protocol + Gemini/OpenAI ✅
7. **패치 검증기** — LLM 생성 패치 구조/구문 검증 ✅
8. **반복 아이템 판단 체인** — YOLO→VLM 캐스케이드 ✅
9. **Executor 어댑터 패턴** — IExecutor Protocol + MockExecutor ✅

### Wave 2 수용 완료 (9개 기능, 105 tests)

1. **Metrics Dashboard** — 런타임 메트릭 집계 (비용/지연/실패율) ✅
2. **Retry Policy** — non-retryable 코드 분류 (auth_blocked/review_rejected/captcha) ✅
3. **Context Reducer** — LLM 컨텍스트 최적화 (후보 요소 축소, score 기반 정렬) ✅
4. **Evolution Model Policy** — 코딩=Pro / 자동화=Flash 티어 강제 ✅
5. **Recipe Versioning** — 셀렉터 레시피 버전 관리 + 패치 적용 (v001→v002) ✅
6. **Decision Port + Human Loop** — DecisionPort Protocol + go/not_go/revise 루프 ✅
7. **Selector Recovery Pipeline** — SelectorNotFound 자동 복구 (후보→패치→재시도) ✅
8. **Scenario Pack Builder** — baseline + exception matrix 시나리오 생성 ✅
9. **Auto-Improvement Orchestrator** — 실패 시 자동 진화 트리거 ✅

### 비수용 항목

1. **Rule-first 실행 모델** — LLM-First 유지
2. **파일 기반 세션 저장** — SQLite 유지
3. **TypeScript 런타임** — Python 유지
4. **anti-bot 비수용 방침** — 스텔스 유지

---

## 9. 예상 작업량

| Phase | 신규 파일 | 수정 파일 | 테스트 수 | 복잡도 |
|-------|----------|----------|----------|--------|
| Phase 1: Chat Automation | 1 | 4 | ~20 | 중 |
| Phase 2: Learning 강화 | 2 | 2 | ~15 | 중 |
| Phase 3: Ops 강화 | 2 | 1 | ~10 | 하 |
| Phase 4: Vision 확장 | 2 | 1 | ~10 | 중 |
| Phase 5: Model 추상화 | 1 | 3 | ~12 | 상 |
| **합계** | **8** | **11** | **~67** | — |
