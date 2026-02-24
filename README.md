# Web-Agentic — 적응형 웹 자동화 엔진

> "반복 실행할수록 LLM 호출이 줄어드는" 웹 자동화 시스템

규칙 기반 결정론적 실행을 우선하고, 실패 시에만 LLM/VLM으로 에스컬레이션하는 적응형 웹 자동화 엔진입니다.
성공한 패턴은 자동으로 규칙으로 승격되어, 반복 실행할수록 비용이 줄어듭니다.

```
비용 에스컬레이션: R(규칙) → E+R(휴리스틱) → L1(Flash) → L2(Pro) → YOLO → VLM → Human Handoff
                   $0        $0              ~$0.001      ~$0.01     로컬     ~$0.02
```

## 목차

- [빠른 시작](#빠른-시작)
- [아키텍처](#아키텍처)
- [프로젝트 구조](#프로젝트-구조)
- [워크플로우 DSL](#워크플로우-dsl)
- [설정](#설정)
- [사용법](#사용법)
- [테스트](#테스트)
- [커스텀 워크플로우 작성](#커스텀-워크플로우-작성)
- [커스텀 규칙 추가](#커스텀-규칙-추가)

---

## 빠른 시작

### 요구사항

- Python 3.11+
- Chromium (Playwright가 자동 설치)

### 설치

```bash
# 저장소 클론
git clone https://github.com/jedikim/web-agentic.git
cd web-agentic

# 자동 설치 (의존성 + 브라우저 + 테스트)
chmod +x scripts/setup.sh
./scripts/setup.sh
```

또는 수동 설치:

```bash
# 패키지 설치 (개발 도구 포함)
pip install -e ".[dev]"

# Playwright 브라우저 설치
python -m playwright install chromium

# 데이터 디렉토리 생성
mkdir -p data/episodes data/artifacts

# 테스트 실행으로 검증
python -m pytest tests/ -q
```

### 선택적 의존성

```bash
# Vision 기능 (YOLO 로컬 탐지)
pip install -e ".[vision]"   # ultralytics + opencv-python

# 자기학습 기능 (DSPy 최적화)
pip install -e ".[learning]"  # dspy
```

### LLM 설정 (선택)

LLM 기능을 사용하려면 Google Gemini API 키가 필요합니다.
규칙 기반 실행만 사용할 경우 API 키 없이도 동작합니다.

```bash
export GEMINI_API_KEY="your-api-key-here"
```

---

## 아키텍처

6개 핵심 모듈이 Protocol 기반 인터페이스로 통신합니다:

```
사용자 자연어 지시
    ↓
┌─────────────────────────────────────────────┐
│  Orchestrator (오케스트레이터)                 │
│                                             │
│  StepQueue에서 스텝을 하나씩 꺼내 실행:         │
│                                             │
│  1. R(Rule Engine) — 규칙 매칭 시도 [토큰 $0]  │
│     ├─ 성공 → X(Executor) 실행 → V(Verifier) │
│     └─ 실패 ↓                                │
│  2. E(Extractor) + R(Heuristic) [토큰 $0]    │
│     ├─ 성공 → X 실행 → V                     │
│     └─ 실패 ↓                                │
│  3. F(Fallback Router) — 실패 분류            │
│     → 최적 복구 경로 결정:                      │
│       ├ L1(Flash) → L2(Pro) — LLM 선택       │
│       ├ YOLO → VLM — Vision 기반             │
│       └ Human Handoff — 사람에게 위임          │
│                                             │
│  V(검증) 성공 → Memory에 패턴 기록             │
│  3회 성공 → R에 규칙 자동 승격                  │
└─────────────────────────────────────────────┘
```

### 7대 설계 원칙

| 원칙 | 설명 |
|------|------|
| **Token Zero First** | 규칙 매칭으로 해결 가능하면 LLM을 호출하지 않음 |
| **Select-Only Problem** | LLM 프롬프트는 항상 "후보 중 선택" 형태로 제한 |
| **Patch-Only Output** | LLM 출력은 `PatchData` 구조체만 허용, 코드 생성 금지 |
| **Verify-After-Act** | 모든 액션 후 반드시 검증 수행 |
| **Learn From Failure** | 성공 패턴 3회 반복 → 규칙으로 자동 승격 |
| **Human Handoff** | CAPTCHA/2FA/결제는 사람에게 위임 |
| **Cost Cascading** | 저비용 → 고비용 순서로 에스컬레이션 보장 |

### 핵심 모듈

| 모듈 | 파일 | 역할 | 토큰 비용 |
|------|------|------|----------|
| **X** (Executor) | `src/core/executor.py` | Playwright 브라우저 제어 | 0 |
| **E** (Extractor) | `src/core/extractor.py` | DOM → 구조화 JSON 추출 | 0 |
| **R** (Rule Engine) | `src/core/rule_engine.py` | YAML 규칙 매칭 + 동의어 사전 | 0 |
| **V** (Verifier) | `src/core/verifier.py` | 액션 후 상태 검증 | 0 |
| **F** (Fallback Router) | `src/core/fallback_router.py` | 실패 분류 + 복구 경로 결정 | 0 |
| **L** (LLM Planner) | `src/ai/llm_planner.py` | Gemini 기반 계획/선택 | 유료 |

### 보조 모듈

| 모듈 | 파일 | 역할 |
|------|------|------|
| Orchestrator | `src/core/orchestrator.py` | 전체 실행 루프 + 에스컬레이션 |
| StepQueue | `src/workflow/step_queue.py` | FIFO 스텝 큐 관리 |
| DSL Parser | `src/workflow/dsl_parser.py` | YAML 워크플로우 파싱 |
| Memory Manager | `src/learning/memory_manager.py` | 4계층 메모리 (Working/Episode/Policy/Artifact) |
| Pattern DB | `src/learning/pattern_db.py` | SQLite 패턴 기록 |
| Rule Promoter | `src/learning/rule_promoter.py` | 패턴 → 규칙 자동 승격 |
| Prompt Manager | `src/ai/prompt_manager.py` | 프롬프트 템플릿 버전 관리 |
| Patch System | `src/ai/patch_system.py` | 구조화된 패치 적용 |
| YOLO Detector | `src/vision/yolo_detector.py` | 로컬 객체 탐지 |
| VLM Client | `src/vision/vlm_client.py` | Gemini 멀티모달 비전 |
| Image Batcher | `src/vision/image_batcher.py` | 스크린샷 배칭/리사이즈 |
| Coord Mapper | `src/vision/coord_mapper.py` | 스크린샷↔페이지 좌표 변환 |
| Handoff | `src/core/handoff.py` | 사람 위임 인터페이스 |

---

## 프로젝트 구조

```
web-agentic/
├── src/
│   ├── core/                    # 핵심 모듈 (X, E, R, V, F)
│   │   ├── types.py             # 공유 타입/인터페이스 정의
│   │   ├── executor.py          # X — Playwright 래퍼
│   │   ├── extractor.py         # E — DOM 추출기
│   │   ├── rule_engine.py       # R — 규칙 엔진
│   │   ├── verifier.py          # V — 검증기
│   │   ├── fallback_router.py   # F — 장애 라우터
│   │   ├── orchestrator.py      # 오케스트레이터
│   │   └── handoff.py           # 사람 위임
│   ├── ai/                      # LLM 모듈
│   │   ├── llm_planner.py       # L — Gemini 플래너
│   │   ├── prompt_manager.py    # 프롬프트 관리
│   │   └── patch_system.py      # 패치 시스템
│   ├── vision/                  # 비전 모듈
│   │   ├── yolo_detector.py     # YOLO 탐지
│   │   ├── vlm_client.py        # VLM 클라이언트
│   │   ├── image_batcher.py     # 이미지 배칭
│   │   └── coord_mapper.py      # 좌표 매핑
│   ├── learning/                # 자기학습 모듈
│   │   ├── memory_manager.py    # 4계층 메모리
│   │   ├── pattern_db.py        # 패턴 DB
│   │   ├── rule_promoter.py     # 규칙 승격
│   │   └── dspy_optimizer.py    # DSPy 최적화 (선택)
│   └── workflow/                # 워크플로우
│       ├── dsl_parser.py        # YAML 파서
│       └── step_queue.py        # 스텝 큐
├── config/
│   ├── settings.yaml            # 엔진 설정
│   ├── synonyms.yaml            # 동의어 사전 (한/영)
│   ├── rules/                   # 67개 사전 정의 규칙
│   │   ├── popup_common.yaml    # 팝업/모달 처리 (17개)
│   │   ├── error_detection.yaml # 에러 페이지 감지 (12개)
│   │   ├── login_detection.yaml # 로그인/인증 감지 (12개)
│   │   ├── pagination.yaml      # 페이지네이션 (12개)
│   │   └── filter_sort.yaml     # 필터/정렬 (14개)
│   └── workflows/               # 워크플로우 정의
│       └── naver_shopping.yaml  # 네이버 쇼핑 PoC
├── scripts/
│   ├── setup.sh                 # 원클릭 설치
│   ├── run_poc.py               # PoC 실행기
│   └── benchmark.py             # 성능 벤치마크
├── tests/
│   ├── unit/                    # 단위 테스트 (20개 파일)
│   └── integration/             # 통합 테스트 (2개 파일)
├── data/                        # 런타임 데이터 (gitignored)
│   ├── episodes/                # Episode 메모리
│   ├── artifacts/               # Artifact 메모리
│   └── patterns.db              # Policy 메모리 (SQLite)
├── docs/
│   ├── PRD.md                   # 제품 요구사항
│   └── ARCHITECTURE.md          # 아키텍처 상세
└── pyproject.toml               # 프로젝트 설정
```

---

## 워크플로우 DSL

워크플로우는 YAML 파일로 정의합니다. 9종류의 노드 타입을 지원합니다.

### 노드 타입

| 노드 | 설명 | 예시 |
|------|------|------|
| `action` | 브라우저 액션 (클릭, 타이핑, 이동 등) | 버튼 클릭, 텍스트 입력 |
| `extract` | DOM에서 데이터 추출 | 상품 목록, 가격 정보 |
| `decide` | 조건 판단 | 결과가 관련 있는지 확인 |
| `verify` | 상태 검증 | 정렬 순서 변경 확인 |
| `branch` | 조건 분기 | if/else 로직 |
| `loop` | 반복 실행 | 페이지네이션 순회 |
| `wait` | 대기 | 네트워크 idle, 요소 출현 |
| `recover` | 에러 복구 | 재시도 로직 |
| `handoff` | 사람에게 위임 | CAPTCHA 처리 |

### 워크플로우 예시

```yaml
workflow:
  name: "naver_shopping_search"
  description: "네이버 쇼핑에서 상품 검색 후 정렬"

  steps:
    - id: "open_page"
      intent: "Go to Naver Shopping"
      node_type: "action"
      arguments: ["https://shopping.naver.com"]
      max_retries: 2
      timeout_ms: 15000

    - id: "search_product"
      intent: "Search for wireless earbuds"
      node_type: "action"
      arguments: ["무선 이어폰"]
      verify:
        type: "url_contains"
        value: "query="
        timeout_ms: 5000

    - id: "sort_popular"
      intent: "Sort by popularity"
      node_type: "action"
      verify:
        type: "url_contains"
        value: "sort=rel"

    - id: "extract_products"
      intent: "Extract product list"
      node_type: "extract"
      max_retries: 3

    - id: "loop_pages"
      intent: "Loop through next 3 pages"
      node_type: "loop"
      arguments: ["next_page", "3"]
      verify:
        type: "url_changed"
```

### 스텝 필드 설명

| 필드 | 필수 | 타입 | 설명 |
|------|------|------|------|
| `id` | O | string | 고유 식별자 |
| `intent` | O | string | 자연어 의도 (한/영 모두 가능) |
| `node_type` | - | string | 노드 타입 (기본: `action`) |
| `selector` | - | string | CSS 셀렉터 (없으면 R/E가 자동 탐색) |
| `arguments` | - | list | 추가 인수 (URL, 검색어 등) |
| `max_retries` | - | int | 최대 재시도 횟수 (1~20, 기본: 3) |
| `timeout_ms` | - | int | 타임아웃 밀리초 (500~300000, 기본: 10000) |
| `verify` | - | object | 액션 후 검증 조건 |

### 검증 조건 타입

| 타입 | 설명 |
|------|------|
| `url_changed` | URL이 변경되었는지 확인 |
| `url_contains` | URL에 특정 문자열 포함 여부 |
| `element_visible` | 특정 요소가 화면에 보이는지 |
| `element_gone` | 특정 요소가 사라졌는지 |
| `text_present` | 페이지에 특정 텍스트 존재 여부 |
| `network_idle` | 네트워크 요청 완료 대기 |

---

## 설정

`config/settings.yaml`에서 엔진의 모든 설정을 관리합니다.

### 주요 설정 항목

```yaml
# 엔진 기본 설정
engine:
  max_retries: 3           # 스텝당 기본 재시도
  step_timeout_ms: 30000   # 스텝당 기본 타임아웃
  budget_limit_usd: 0.05   # 태스크당 예산 한도

# 브라우저
browser:
  headless: true
  viewport_width: 1920
  viewport_height: 1080
  default_timeout_ms: 30000

# LLM (Gemini)
llm:
  tier1:
    model: "gemini-2.0-flash"   # 저비용 빠른 모델
    temperature: 0.1
  tier2:
    model: "gemini-2.5-pro-preview-06-05"  # 고성능 모델
    temperature: 0.2
  confidence_threshold: 0.7  # 이 미만이면 tier2로 에스컬레이션

# 자기학습
learning:
  pattern_min_success: 3    # 규칙 승격에 필요한 최소 성공 횟수
  pattern_min_ratio: 0.8    # 최소 성공률

# 비용 예산
budget:
  per_task_usd: 0.05
  per_step_usd: 0.01
```

### 동의어 사전 (`config/synonyms.yaml`)

한국어/영어 동의어를 정의하여 규칙 매칭의 범위를 확장합니다:

```yaml
sort:
  인기순: ["popularity", "인기", "popular", "인기순정렬"]
  최신순: ["latest", "newest", "최신", "날짜순"]
  낮은가격순: ["price_low", "lowest_price", "가격낮은순"]

popup_close:
  닫기: ["close", "dismiss", "x", "cancel", "아니요"]
  확인: ["ok", "confirm", "accept", "동의"]
```

---

## 사용법

### 1. PoC 실행

네이버 쇼핑 워크플로우를 실행합니다:

```bash
# 기본 실행 (headless)
python scripts/run_poc.py

# 브라우저 화면 보면서 실행
python scripts/run_poc.py --no-headless

# 5회 반복 (학습 효과 확인)
python scripts/run_poc.py --iterations 5

# 커스텀 워크플로우
python scripts/run_poc.py --workflow config/workflows/my_workflow.yaml

# 디버그 로그 출력
python scripts/run_poc.py --log-level DEBUG
```

결과는 `data/poc_results.json`에 저장됩니다.

### 2. 벤치마크

PRD 성공 기준 대비 성능을 측정합니다:

```bash
# 5회 반복 벤치마크 (기본)
python scripts/benchmark.py

# 20회 반복 (학습 효과 추세 분석)
python scripts/benchmark.py --iterations 20

# 브라우저 보면서 실행
python scripts/benchmark.py --no-headless --iterations 10
```

**PRD 성공 기준:**

| 기준 | 목표 |
|------|------|
| E2E 성공률 | >= 80% (20회 중 16회) |
| 태스크당 비용 | <= $0.01 |
| 실행 시간 | <= 90초 |
| LLM 호출 추세 | 반복할수록 감소 |

결과는 `data/benchmark_results.json`에 저장됩니다.

### 3. Python에서 직접 사용

```python
import asyncio
from src.core.executor import create_executor
from src.core.extractor import DOMExtractor
from src.core.rule_engine import RuleEngine
from src.core.verifier import Verifier
from src.core.fallback_router import create_fallback_router
from src.core.orchestrator import Orchestrator
from src.learning.memory_manager import create_memory_manager
from src.workflow.dsl_parser import parse_workflow

async def main():
    # 모듈 초기화
    executor = await create_executor(headless=True)
    extractor = DOMExtractor()
    rule_engine = RuleEngine()
    verifier = Verifier()
    fallback_router = create_fallback_router()
    memory = await create_memory_manager("data")

    # 오케스트레이터 조립 (DI)
    orchestrator = Orchestrator(
        executor=executor,
        extractor=extractor,
        rule_engine=rule_engine,
        verifier=verifier,
        fallback_router=fallback_router,
        planner=None,  # LLM 없이 규칙만 사용
        memory=memory,
    )

    # 워크플로우 파싱 & 실행
    steps = parse_workflow("config/workflows/naver_shopping.yaml")
    results = await orchestrator.run(steps)

    # 결과 확인
    for r in results:
        print(f"  {r.step_id}: {'OK' if r.success else 'FAIL'} "
              f"(method={r.method}, tokens={r.tokens_used})")

    await executor.close()

asyncio.run(main())
```

### 4. 개별 모듈 사용

```python
# 규칙 매칭만 사용
from src.core.rule_engine import RuleEngine
from src.core.types import PageState

engine = RuleEngine()
state = PageState(url="https://shopping.naver.com", title="네이버쇼핑")
match = engine.match("인기순 정렬", state)
if match:
    print(f"규칙 매칭: {match.rule_id} → {match.selector}")

# DOM 추출만 사용
from src.core.extractor import DOMExtractor
extractor = DOMExtractor()
# page = playwright page 객체
elements = await extractor.extract_clickables(page)
products = await extractor.extract_products(page)

# 검증만 사용
from src.core.verifier import Verifier
from src.core.types import VerifyCondition
verifier = Verifier()
cond = VerifyCondition(type="url_contains", value="sort=", timeout_ms=5000)
result = await verifier.verify(cond, page)
```

---

## 테스트

```bash
# 전체 테스트 (675개)
python -m pytest tests/ -q

# 단위 테스트만
python -m pytest tests/unit/ -q

# 통합 테스트만
python -m pytest tests/integration/ -q

# 특정 모듈 테스트
python -m pytest tests/unit/test_rule_engine.py -v
python -m pytest tests/unit/test_orchestrator.py -v

# 커버리지 (pytest-cov 필요)
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### 테스트 구성

| 카테고리 | 파일 수 | 테스트 수 | 범위 |
|---------|---------|----------|------|
| **Phase 1** — Deterministic Core | 5 | ~132 | X, E, R, V, DSL Parser |
| **Phase 2** — Adaptive Fallback | 7 | ~220 | Orchestrator, StepQueue, F, L, Prompt, Patch, Memory |
| **Phase 3** — Vision | 4 | ~80 | YOLO, VLM, ImageBatcher, CoordMapper |
| **Phase 4** — Self-Improving | 3 | ~75 | PatternDB, RulePromoter, DSPy |
| **Phase 5** — Exception Hardening | 2 | ~99 | 67개 규칙, Handoff |
| **Phase 6** — Integration | 2 | ~69 | 엔진 와이어링, PoC 스크립트 |
| **합계** | **22** | **675** | |

---

## 커스텀 워크플로우 작성

`config/workflows/` 에 새 YAML 파일을 만들면 됩니다:

```yaml
workflow:
  name: "my_custom_workflow"
  description: "내 커스텀 워크플로우"

  steps:
    # 1. 페이지 이동
    - id: "goto_site"
      intent: "Go to example.com"
      node_type: "action"
      arguments: ["https://example.com"]
      timeout_ms: 15000

    # 2. 검색
    - id: "search"
      intent: "Search for Python books"
      node_type: "action"
      arguments: ["Python"]
      verify:
        type: "url_contains"
        value: "search"

    # 3. 데이터 추출
    - id: "extract_results"
      intent: "Extract search results"
      node_type: "extract"

    # 4. 조건 분기
    - id: "check_results"
      intent: "Check if results exist"
      node_type: "decide"
      arguments: ["has_results"]

    # 5. 페이지네이션
    - id: "next_pages"
      intent: "Loop through next 5 pages"
      node_type: "loop"
      arguments: ["next_page", "5"]
      verify:
        type: "url_changed"
```

실행:

```bash
python scripts/run_poc.py --workflow config/workflows/my_custom_workflow.yaml
```

---

## 커스텀 규칙 추가

`config/rules/` 에 YAML 파일로 규칙을 추가합니다:

```yaml
# config/rules/my_site_rules.yaml
rules:
  - name: "my_site_close_popup"
    category: "popup"
    trigger:
      intent: "팝업 닫기"
      site_pattern: "*.example.com"
    selector: ".modal-close-btn"
    method: "click"
    priority: 10

  - name: "my_site_search"
    category: "search"
    trigger:
      intent: "검색"
      site_pattern: "*.example.com"
    selector: "#search-input"
    method: "type"
    priority: 5
```

엔진이 시작될 때 `config/rules/*.yaml` 를 자동으로 로드합니다.

동의어도 `config/synonyms.yaml`에 추가할 수 있습니다:

```yaml
# 기존 그룹에 추가하거나 새 그룹 생성
my_actions:
  장바구니: ["cart", "add to cart", "담기", "장바구니 담기"]
  구매: ["buy", "purchase", "구입", "주문"]
```

---

## 메모리 시스템

4계층 메모리가 학습과 최적화를 지원합니다:

| 계층 | 저장소 | 수명 | 용도 |
|------|--------|------|------|
| **Working** | 메모리 (dict) | 1 스텝 | 현재 스텝 컨텍스트 |
| **Episode** | JSON 파일 | 1 태스크 | 태스크 실행 기록 |
| **Policy** | SQLite DB | 영구 | 성공 패턴, 규칙 |
| **Artifact** | 파일시스템 | TTL 기반 | 스크린샷, 추출 데이터 |

데이터 위치:
- Episode: `data/episodes/{task_id}.json`
- Policy: `data/patterns.db`
- Artifact: `data/artifacts/`

---

## License

MIT
