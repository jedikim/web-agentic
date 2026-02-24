# ARCHITECTURE.md — 모듈별 상세 아키텍처

## 시스템 구조 개요

```
사용자 자연어 → DSL Parser → StepQueue → Orchestrator
                                            │
                                   ┌────────┴────────┐
                                   │ 에스컬레이션 루프  │
                                   │                  │
                               [1] R(규칙매칭) ─ $0    │
                                   ├─ 성공 → X → V    │
                                   └─ 실패 ↓          │
                               [2] E+R(휴리스틱) ─ $0  │
                                   ├─ 성공 → X → V    │
                                   └─ 실패 ↓          │
                               [3] F(분류) → 복구 경로  │
                                   ├─ L1(Flash)       │
                                   ├─ L2(Pro)         │
                                   ├─ YOLO → VLM      │
                                   └─ Human Handoff   │
                                   │                  │
                                   │ V(검증) 성공 →    │
                                   │ Memory 기록 →    │
                                   │ 3회 성공 → R 승격 │
                                   └──────────────────┘
```

## 모듈 간 의존성

```
Orchestrator
├── StepQueue              — 스텝 관리
├── R (Rule Engine)        — 규칙 매칭
│   └── config/rules/*.yaml, config/synonyms.yaml
├── E (Extractor)          — DOM 추출
├── X (Executor)           — Playwright 브라우저
├── V (Verifier)           — 상태 검증
├── F (Fallback Router)    — 실패 분류 + 복구
│   ├── L (LLM Planner)   — Gemini API
│   │   ├── Prompt Manager — 프롬프트 템플릿
│   │   └── Patch System   — 구조화 패치
│   └── Vision
│       ├── YOLO Detector  — 로컬 객체 탐지
│       ├── VLM Client     — Gemini 멀티모달
│       ├── Image Batcher  — 이미지 전처리
│       └── Coord Mapper   — 좌표 역매핑
├── Memory Manager
│   ├── Working Memory     — dict (1 스텝)
│   ├── Episode Memory     — JSON 파일 (1 태스크)
│   ├── Policy Memory      — SQLite (영구)
│   └── Artifact Memory    — 파일시스템 (TTL)
├── Handoff Manager        — 사람 위임
├── Learning
│   ├── Pattern DB         — SQLite 패턴 기록
│   ├── Rule Promoter      — 자동 규칙 승격
│   ├── Element Fingerprint — Similo 다속성 매칭 (LLM-free 셀렉터 복구)
│   ├── Plan Cache         — 키워드 퍼지 매칭 + 플랜 적응
│   ├── Replay Store       — 실행 이력 저장 (키워드 포함)
│   └── DSPy Optimizer     — 프롬프트 최적화 placeholder (DSPy 미연동, 경량 휴리스틱)
├── AI
│   ├── LLM Planner        — Gemini/OpenAI 멀티프로바이더
│   ├── Cascaded Router    — Flash-first 라우팅 + Pro 에스컬레이션
│   └── Context Reducer    — LLM 컨텍스트 최적화
└── Self-Healing
    ├── Failure Classifier — 6분류 (selector/timing/hidden/stale/nav/data)
    └── Healing Planner    — 분류별 전용 복구 전략
```

## 인터페이스 (Protocol 정의)

각 모듈은 Python Protocol로 정의된 인터페이스로만 통신합니다.
모든 인터페이스는 `src/core/types.py`에 정의되어 있습니다.

```python
class IExecutor(Protocol):
    """브라우저 자동화 인터페이스 — X 모듈"""
    async def goto(self, url: str) -> None: ...
    async def click(self, selector: str, options: ClickOptions | None = None) -> None: ...
    async def type_text(self, selector: str, text: str) -> None: ...
    async def press_key(self, key: str) -> None: ...
    async def scroll(self, direction: str = "down", amount: int = 300) -> None: ...
    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes: ...
    async def wait_for(self, condition: WaitCondition) -> None: ...
    async def get_page(self) -> Page: ...

class IExtractor(Protocol):
    """DOM 추출 인터페이스 — E 모듈"""
    async def extract_inputs(self, page: Page) -> list[ExtractedElement]: ...
    async def extract_clickables(self, page: Page) -> list[ExtractedElement]: ...
    async def extract_products(self, page: Page) -> list[ProductData]: ...
    async def extract_state(self, page: Page) -> PageState: ...

class IRuleEngine(Protocol):
    """규칙 매칭 인터페이스 — R 모듈"""
    def match(self, intent: str, context: PageState) -> RuleMatch | None: ...
    def heuristic_select(
        self, candidates: list[ExtractedElement], intent: str
    ) -> str | None: ...
    def register_rule(self, rule: RuleDefinition) -> None: ...

class IVerifier(Protocol):
    """검증 인터페이스 — V 모듈"""
    async def verify(self, condition: VerifyCondition, page: Page) -> VerifyResult: ...

class IFallbackRouter(Protocol):
    """실패 분류 + 라우팅 인터페이스 — F 모듈"""
    def classify(self, error: Exception, context: StepContext) -> FailureCode: ...
    def route(self, failure: FailureCode) -> RecoveryPlan: ...

class ILLMPlanner(Protocol):
    """LLM 기반 계획/선택 인터페이스 — L 모듈"""
    async def plan(self, instruction: str) -> list[StepDefinition]: ...
    async def select(
        self, candidates: list[ExtractedElement], intent: str
    ) -> PatchData: ...

class IMemoryManager(Protocol):
    """4계층 메모리 인터페이스"""
    def get_working(self, key: str) -> Any: ...
    def set_working(self, key: str, value: Any) -> None: ...
    async def save_episode(self, task_id: str, data: dict[str, Any]) -> None: ...
    async def load_episode(self, task_id: str) -> dict[str, Any] | None: ...
    async def query_policy(self, intent: str, site: str) -> RuleMatch | None: ...
    async def save_policy(self, rule: RuleDefinition, success_count: int) -> None: ...
```

## 의존성 주입 (DI 패턴)

모든 모듈은 생성자에서 의존성을 주입받습니다.
선택적 모듈(planner, memory)은 `None`이면 해당 기능이 비활성화됩니다.

```python
class Orchestrator:
    def __init__(
        self,
        executor: IExecutor,
        extractor: IExtractor,
        rule_engine: IRuleEngine,
        verifier: IVerifier,
        fallback_router: IFallbackRouter,
        planner: ILLMPlanner | None = None,   # 없으면 LLM 비활성화
        memory: IMemoryManager | None = None,  # 없으면 메모리 비활성화
    ): ...
```

`scripts/run_poc.py`의 `create_engine()` 함수에서 전체 와이어링 예시를 확인할 수 있습니다.

## 에러 계층

실패 유형별 예외 클래스가 정의되어 있어 F(Fallback Router)가 정확히 분류합니다:

```python
class AutomationError(Exception): ...           # 기본 예외
class SelectorNotFoundError(AutomationError): ...  # 셀렉터 미발견
class NotInteractableError(AutomationError): ...   # 상호작용 불가
class StateNotChangedError(AutomationError): ...   # 상태 미변경
class VisualAmbiguityError(AutomationError): ...   # 시각적 모호성
class NetworkError(AutomationError): ...           # 네트워크 에러
class CaptchaDetectedError(AutomationError): ...   # CAPTCHA 감지
class AuthRequiredError(AutomationError): ...      # 인증 필요
class BudgetExceededError(AutomationError): ...    # 예산 초과
```

각 예외에는 `failure_code` 속성이 있어 F 모듈이 자동으로 분류합니다.

## 에스컬레이션 흐름 상세

```
[Step 실행 시작]
│
├─[1] R.match(intent, page_state) ──── 토큰: 0, 비용: $0
│  ├─ 매칭 성공 → X.execute(rule.selector, rule.method)
│  │              → V.verify(condition) ─── 성공 → 완료
│  │                                    └── 실패 → [3]
│  └─ 매칭 실패 → [2]
│
├─[2] E.extract(page) + R.heuristic_select(candidates) ──── 토큰: 0
│  ├─ 후보 선택 성공 → X.execute(eid)
│  │                   → V.verify(condition) ─── 성공 → 완료
│  │                                         └── 실패 → [3]
│  └─ 후보 없음/선택 실패 → [3]
│
├─[3] F.classify(error) → F.route(failure_code) ──── 에스컬레이션 결정
│  ├─ SelectorNotFound:
│  │   → L1(Flash) — select(candidates) ──── ~$0.001
│  │     ├─ confidence >= 0.7 → X → V
│  │     └─ confidence < 0.7 → L2(Pro) ──── ~$0.01
│  │
│  ├─ VisualAmbiguity:
│  │   → YOLO.detect(screenshot) ──── 로컬 (무료)
│  │     ├─ 탐지 성공 → CoordMapper → X → V
│  │     └─ 탐지 실패 → VLM(Flash) → VLM(Pro) ──── ~$0.02
│  │
│  ├─ CaptchaDetected:
│  │   → Handoff.request(CAPTCHA) ──── 사람에게 위임
│  │
│  ├─ AuthRequired:
│  │   → Handoff.request(AUTH) ──── 사람에게 위임
│  │
│  └─ DynamicLayout (attempt >= 3):
│     → strategy_switch → 다른 접근 방식 시도
│
└─ 모든 시도 실패 → StepResult(success=False)
```

## 자기학습 루프

```
실행 성공 시:
  1. PatternDB.record_success(intent, site, selector, method)
  2. 해당 패턴의 success_count 조회
  3. success_count >= 3 AND success_ratio >= 0.8:
     → RulePromoter.promote() → RuleEngine.register_rule()
     → 다음 실행부터 R에서 직접 매칭 ($0)

실행 실패 시:
  1. PatternDB.record_failure(intent, site, selector, method)
  2. 실패 패턴 분석 → 에스컬레이션 경로 최적화
```

## 비동기 패턴

모든 브라우저 상호작용은 `async/await`로 처리됩니다:

```python
async def execute_step(self, step: StepDefinition) -> StepResult:
    page = await self.executor.get_page()
    page_state = await self.extractor.extract_state(page)

    for attempt in range(step.max_attempts):
        try:
            # 1. 규칙 매칭
            rule_match = self.rule_engine.match(step.intent, page_state)
            if rule_match:
                await self._dispatch_action(rule_match)
            else:
                # 2. 휴리스틱 선택
                candidates = await self.extractor.extract_clickables(page)
                eid = self.rule_engine.heuristic_select(candidates, step.intent)
                if eid:
                    await self.executor.click(eid)
                else:
                    # 3. 에스컬레이션
                    ...

            # 4. 검증
            if step.verify_condition:
                result = await self.verifier.verify(step.verify_condition, page)
                if result.success:
                    return StepResult(success=True, method="R")

        except AutomationError as e:
            failure = self.fallback_router.classify(e, context)
            recovery = self.fallback_router.route(failure)
            # 복구 시도 ...
```

## 설정 파일 로드

- 엔진 설정: `config/settings.yaml` — 시작 시 로드
- 규칙 파일: `config/rules/*.yaml` — `RuleEngine.__init__()` 에서 자동 로드
- 동의어: `config/synonyms.yaml` — `RuleEngine.__init__()` 에서 자동 로드
- 워크플로우: `config/workflows/*.yaml` — `parse_workflow()` 로 명시적 로드

## Research Wave 모듈 (v3.1)

### R1: Similo 다속성 Fingerprint (`src/learning/element_fingerprint.py`)

셀렉터가 깨졌을 때 LLM 호출 없이 다속성 유사도 매칭으로 요소 복구.
7가지 속성(tag, role, text, class_list, nearby_text, bbox, attributes_hash)의 가중 유사도를 계산하여
임계값(기본 0.6) 이상인 후보를 자동 선택.

```
셀렉터 실패 → Element Fingerprint 매칭 (비용 $0)
    ├─ 매칭 성공 → 재시도 (LLM 호출 생략)
    └─ 매칭 실패 → LLM 패치 요청 (기존 플로우)
```

### R2: Adaptive Plan Caching (`src/learning/plan_cache.py`)

exact match 실패 시 키워드 Jaccard 유사도로 퍼지 매칭.
유사한 과거 플랜의 인자만 교체하여 적응 재사용.

```
새 인텐트 → exact match 조회 → 실패
    → 키워드 추출 (EN/KO 불용어 제거)
    → Jaccard 유사도 기반 퍼지 매칭
    → 인자 diff → 플랜 적응
```

### R3: Cascaded Flash-First Router (`src/ai/cascaded_router.py`)

항상 Flash(저비용) 모델을 먼저 시도. 신뢰도 < 0.7 또는 파싱 실패 시만 Pro 에스컬레이션.
complexity별 성공률 추적으로 라우팅 최적화.

```
인텐트 → 복잡도 분류 (SIMPLE/MODERATE/COMPLEX)
    → Flash 모델 시도
    → 신뢰도 체크
        ├─ >= 임계값 → Flash 결과 사용
        └─ < 임계값 → Pro 에스컬레이션
```

### R4: Self-Healing 6분류 (`src/core/self_healing.py`)

셀렉터 실패(28%) 외에 timing/hidden/stale/navigation/data 실패도 전용 복구 전략 적용.

| 분류 | 우선 전략 | 예시 에러 |
|------|----------|----------|
| selector_not_found | RE_EXTRACT | 셀렉터 미발견 |
| timing_timeout | INCREASE_TIMEOUT | TimeoutError |
| element_hidden | SCROLL_INTO_VIEW | "not visible" |
| stale_element | WAIT_AND_RETRY | "detached from DOM" |
| navigation_incomplete | WAIT_FOR_NETWORK | "net::err" |
| data_mismatch | RE_EXTRACT | "assertion failed" |
