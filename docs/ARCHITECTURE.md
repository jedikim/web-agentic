# ARCHITECTURE.md — 모듈별 상세 아키텍처

## 시스템 구조 개요

```
사용자 자연어 → L(Plan) → StepQueue → R(규칙매칭)
                                        ├─ 성공 → X(실행) → V(검증) → 다음스텝
                                        └─ 실패 → E(추출) → F(분류) → AI레이어 → 패치 → X → V
```

## 모듈 간 의존성

```
Orchestrator
├── StepQueue
├── R (Rule Engine)
│   ├── E (Extractor)  ← 후보 추출 요청
│   ├── X (Executor)   ← 실행 명령 전달
│   └── F (Fallback Router) ← 실패 시 분류 요청
├── V (Verifier)
│   ├── X ← 실행 후 상태 수신
│   └── F ← 검증 실패 시 분류 요청
├── L (LLM Planner)
│   └── Gemini API
├── F (Fallback Router)
│   ├── L (LLM Tier 1/2)
│   ├── YOLO (Vision Tier 1)
│   └── VLM (Vision Tier 2/3)
└── Memory Manager
    ├── Working Memory (dict)
    ├── Episode Memory (dict → JSON)
    ├── Policy Memory (SQLite)
    └── Artifact Memory (filesystem)
```

## 인터페이스 (Protocol 정의)

각 모듈은 Python Protocol로 정의된 인터페이스로만 통신합니다.

```python
class IExecutor(Protocol):
    async def goto(self, url: str) -> None: ...
    async def click(self, selector: str, options: ClickOptions | None = None) -> None: ...
    async def type_text(self, selector: str, text: str) -> None: ...
    async def screenshot(self, region: tuple | None = None) -> bytes: ...
    async def wait_for(self, condition: WaitCondition) -> None: ...

class IExtractor(Protocol):
    async def extract_inputs(self, page: Page) -> list[ExtractedElement]: ...
    async def extract_clickables(self, page: Page) -> list[ExtractedElement]: ...
    async def extract_products(self, page: Page) -> list[ProductData]: ...
    async def extract_state(self, page: Page) -> PageState: ...

class IRuleEngine(Protocol):
    def match(self, intent: str, context: PageState) -> RuleMatch | None: ...
    def heuristic_select(self, candidates: list[ExtractedElement], intent: str) -> str | None: ...
    def register_rule(self, rule: RuleDefinition) -> None: ...

class IVerifier(Protocol):
    async def verify(self, condition: VerifyCondition, page: Page) -> VerifyResult: ...

class IFallbackRouter(Protocol):
    def classify(self, error: Exception, context: StepContext) -> FailureCode: ...
    def route(self, failure: FailureCode) -> RecoveryPlan: ...

class ILLMPlanner(Protocol):
    async def plan(self, instruction: str) -> list[StepDefinition]: ...
    async def select(self, candidates: list[ExtractedElement], intent: str) -> PatchData: ...
```

## 설정 및 의존성 주입

모든 모듈은 생성자에서 의존성을 주입받습니다 (DI 패턴):

```python
class Orchestrator:
    def __init__(
        self,
        executor: IExecutor,
        extractor: IExtractor,
        rule_engine: IRuleEngine,
        verifier: IVerifier,
        fallback_router: IFallbackRouter,
        planner: ILLMPlanner,
        memory: IMemoryManager,
        config: Settings,
    ): ...
```

## 에러 계층

```python
class AutomationError(Exception): ...
class SelectorNotFoundError(AutomationError): ...
class NotInteractableError(AutomationError): ...
class StateNotChangedError(AutomationError): ...
class VisualAmbiguityError(AutomationError): ...
class NetworkError(AutomationError): ...
class CaptchaDetectedError(AutomationError): ...
class AuthRequiredError(AutomationError): ...
class BudgetExceededError(AutomationError): ...
```

## 비동기 패턴

```python
# 모든 브라우저 상호작용은 async
async def execute_step(self, step: StepDefinition) -> StepResult:
    for attempt in range(step.max_attempts):
        try:
            rule_match = self.rule_engine.match(step.intent, self.current_state)
            if rule_match:
                await self.executor.execute(rule_match.command)
            else:
                candidates = await self.extractor.extract(self.page)
                selected = self.rule_engine.heuristic_select(candidates, step.intent)
                if not selected:
                    # F → AI 에스컬레이션
                    ...

            result = await self.verifier.verify(step.verify_condition, self.page)
            if result.success:
                return StepResult(success=True, ...)
        except AutomationError as e:
            failure = self.fallback_router.classify(e, context)
            recovery = self.fallback_router.route(failure)
            # 복구 시도 ...
```
