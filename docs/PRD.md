# PRD — 적응형 웹 자동화 엔진

> Claude Code가 참조하는 제품 요구사항 정의서.
> 전체 기술 기획서는 `docs/web-automation-technical-spec-v2.md` 참조.

---

## 1. 제품 비전

"반복 실행할수록 LLM 호출이 줄어드는 웹 자동화 시스템"

사용자의 자연어 지시 → 웹 브라우저 자율 조작 → 비용/정확도 최적화를 위해 "룰 → 경량LLM → 고급LLM → Vision" 순서로 에스컬레이션하는 엔진.

## 2. 핵심 설계 원칙 (코드에 반드시 반영)

| 원칙 | 코드 적용 |
|------|----------|
| **P1 토큰 제로 우선** | R(Rule Engine)에서 처리 가능하면 L(LLM) 호출하지 않음 |
| **P2 선택 문제 변환** | LLM/VLM 프롬프트는 항상 "후보 중 선택" 형태 |
| **P3 Patch-Only** | `L`의 출력은 `PatchData` 타입만 허용. 코드 생성 금지 |
| **P4 Verify-After-Act** | `X.execute()` 후 반드시 `V.verify()` 호출 |
| **P5 실패에서 학습** | 성공 패턴 3회 → `R`에 규칙 승격 |
| **P6 Human Handoff** | CAPTCHA/2FA/결제는 `Handoff` 이벤트 발생 |
| **P7 비용 계단식** | `F(Fallback Router)`가 저비용→고비용 순서 보장 |

## 3. 핵심 모듈 (6개)

### 3.1 X — Executor (`src/core/executor.py`)
- Playwright async 래퍼
- 메서드: goto, click, type, press, scroll, waitFor, screenshot, drag, hover, upload, interceptResponse
- 토큰 소비: 0
- 모든 실행에 timeout 적용
- 실패 시 예외를 V에게 전달

### 3.2 E — Extractor (`src/core/extractor.py`)
- DOM→요약 JSON 변환 (토큰 0)
- 4종: E_inputs, E_clickables, E_products, E_state
- 출력: eid(element ID) + bbox + 메타데이터
- 범위: 일반DOM + iframe + Shadow DOM + Portal

### 3.3 R — Rule Engine (`src/core/rule_engine.py`)
- YAML DSL 기반 규칙 매칭
- 동의어 사전으로 텍스트 매칭
- 규칙 카테고리: 팝업, 검색, 정렬, 필터, 페이지네이션, 로그인감지, 에러감지
- 규칙 학습 루프: LLM 성공 → 패턴DB → 3회 이상 성공 → 규칙 승격

### 3.4 L — LLM Planner (`src/ai/llm_planner.py`)
- 2가지 모드: Plan(스텝 분해), Select(후보 선택)
- Tier 1: Gemini 3.0 Flash, Tier 2: Gemini 3.1 Pro Preview
- **출력 제약**: PatchData 타입만 허용
- 신뢰도 기반 에스컬레이션 (< 0.7 → Tier 2)

### 3.5 V — Verifier (`src/core/verifier.py`)
- URL/DOM/네트워크/시각/데이터 검증
- 대부분 토큰 0 (룰 기반)
- 실패 시 F에게 분류 요청

### 3.6 F — Fallback Router (`src/core/fallback_router.py`)
- 실패 유형 분류: SelectorNotFound, NotInteractable, StateNotChanged, VisualAmbiguity, NetworkError, QueueDetected, CaptchaDetected, AuthRequired, DynamicLayout
- 유형별 최적 복구 경로 결정
- 비용 계단식 상승 보장

## 4. 데이터 타입 (Python Protocol/dataclass)

```python
# 핵심 타입 정의 — 모든 모듈이 이 타입으로 통신

@dataclass
class ExtractedElement:
    eid: str
    type: str  # input|button|link|tab|option|card|icon|image
    text: str | None
    role: str | None
    bbox: tuple[int, int, int, int]
    visible: bool
    parent_context: str | None

@dataclass
class PatchData:
    patch_type: str  # selector_fix|param_change|rule_add|strategy_switch
    target: str
    data: dict
    confidence: float

@dataclass
class StepResult:
    step_id: str
    success: bool
    method: str  # R|L1|L2|YOLO|VLM1|VLM2|H
    tokens_used: int
    latency_ms: float
    cost_usd: float
    failure_code: str | None

class FailureCode(str, Enum):
    SELECTOR_NOT_FOUND = "SelectorNotFound"
    NOT_INTERACTABLE = "NotInteractable"
    STATE_NOT_CHANGED = "StateNotChanged"
    VISUAL_AMBIGUITY = "VisualAmbiguity"
    NETWORK_ERROR = "NetworkError"
    QUEUE_DETECTED = "QueueDetected"
    CAPTCHA_DETECTED = "CaptchaDetected"
    AUTH_REQUIRED = "AuthRequired"
    DYNAMIC_LAYOUT = "DynamicLayout"
```

## 5. 에스컬레이션 흐름 (구현 필수)

```
R(규칙매칭) → 성공 → X(실행) → V(검증) → 성공 → 다음스텝
         ↓ 실패
    E(후보추출) → R(휴리스틱) → 성공 → X → V
                           ↓ 실패
                      F(실패분류) → 최적경로 선택:
                        ├─ SelectorNotFound → L1(Flash) → 실패 → L2(Pro)
                        ├─ VisualAmbiguity → YOLO → VLM(Flash) → VLM(Pro)
                        ├─ CaptchaDetected → Human Handoff
                        └─ ...
```

## 6. Workflow/DSL (YAML 파서 구현)

9종 노드: action, extract, decide, verify, branch, loop, wait, recover, handoff

각 노드에 guardrail 필수 (max_retries, timeout_ms, exit_on_no_change)

## 7. 메모리 4계층

| 계층 | 구현 위치 | 수명 |
|------|----------|------|
| Working | 변수/컨텍스트 | 1 스텝 |
| Episode | 태스크 메타 | 1 태스크 |
| Policy | DB (규칙/패턴) | 영구 |
| Artifact | 파일시스템 | TTL 기반 |

## 8. PoC 성공 기준

- 타깃: 네이버 쇼핑 검색/정렬/필터/추출
- E2E 성공률: 20회 중 16회+ (≥80%)
- 10회차 이후 LLM 호출 감소 추세
- 태스크당 비용 $0.01 이하
- 실행 시간 90초 이내

## 9. 참고 문서 경로

| 문서 | 경로 | 용도 |
|------|------|------|
| 전체 기술 기획서 | `docs/web-automation-technical-spec-v2.md` | 상세 설계 참조 |
| 동의어 사전 | `config/synonyms.yaml` | R(Rule Engine) 사용 |
| 규칙 파일 | `config/rules/*.yaml` | R(Rule Engine) 로드 |
| 에이전트 정의 | `agents/AGENTS.md` | 멀티에이전트 역할 |
