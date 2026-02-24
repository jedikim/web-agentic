> **[English Version](./TESTING-GUIDE.md)**

# 테스트 가이드

## 1. 개요

web-agentic 프로젝트는 **40개 테스트 파일에 걸쳐 총 823개의 테스트**를 유지하고 있으며, 4단계 테스트 피라미드로 구성되어 있습니다.

| 계층 | 테스트 수 | 파일 수 | 목적 |
|------|----------:|--------:|------|
| 단위 테스트 | 685 | 32 | 개별 모듈 로직 검증 |
| 통합 테스트 | 95 | 3 | 모듈 간 연동 및 API 엔드포인트 |
| E2E 파이프라인 | 43 | 7 | 브라우저 자동화 시나리오 |
| UI E2E | 6 | 1 | 전체 스택 UI + API 검증 |

**사용 도구:**
- [pytest](https://docs.pytest.org/) -- 테스트 실행기 및 단언문
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) -- 비동기 테스트 지원 (auto 모드)
- [Playwright for Python](https://playwright.dev/python/) -- E2E 테스트 브라우저 자동화

모든 비동기 테스트는 `pytest-asyncio`의 **auto 모드**(`asyncio_mode = "auto"`)를 사용하므로, `@pytest.mark.asyncio` 데코레이터를 수동으로 붙일 필요가 없습니다.

## 2. 테스트 피라미드

```mermaid
graph TD
    subgraph pyramid["테스트 피라미드 (총 823개)"]
        UI["UI E2E 테스트<br/>1개 파일, 6개 테스트"]
        E2E["E2E 파이프라인 테스트<br/>7개 파일, 43개 테스트"]
        INT["통합 테스트<br/>3개 파일, 95개 테스트"]
        UNIT["단위 테스트<br/>32개 파일, 685개 테스트"]
    end

    UI --> E2E
    E2E --> INT
    INT --> UNIT

    style UNIT fill:#4CAF50,color:#fff,stroke:#388E3C
    style INT fill:#2196F3,color:#fff,stroke:#1565C0
    style E2E fill:#FF9800,color:#fff,stroke:#EF6C00
    style UI fill:#F44336,color:#fff,stroke:#C62828
```

피라미드는 표준 테스트 원칙을 따릅니다: **하단에 많은 단위 테스트, 상단에 적지만 포괄적인 테스트**. 단위 테스트는 빠르게 실행되어 개별 함수를 검증하고, E2E 및 UI 테스트는 전체 시스템을 검증하지만 느리고 리소스를 더 많이 사용합니다.

## 3. 주요 명령어

| 명령어 | 설명 |
|--------|------|
| `pytest tests/` | 전체 테스트 실행 |
| `pytest tests/unit/` | 단위 테스트만 실행 |
| `pytest tests/integration/` | 통합 테스트만 실행 |
| `pytest tests/e2e/` | E2E 테스트만 실행 |
| `pytest tests/unit/test_rule_engine.py` | 단일 파일 실행 |
| `pytest tests/ -k "test_match"` | 테스트 이름 패턴으로 필터링 |
| `pytest tests/ -v` | 상세 출력 |
| `pytest tests/ -x` | 첫 번째 실패 시 중단 |
| `pytest tests/ --tb=short` | 간략한 트레이스백 |
| `pytest tests/ -m "not e2e"` | E2E 테스트 제외 |
| `pytest tests/ -m "not live"` | 라이브 사이트 테스트 제외 |
| `pytest tests/ --co` | 테스트 목록만 출력 (실행하지 않음) |

## 4. 테스트 분류

### 4.1 단위 테스트 (685개, 32개 파일)

단위 테스트는 각 모듈의 로직을 격리하여 검증합니다. 외부 의존성(LLM API, 브라우저, 데이터베이스)은 모두 모킹됩니다.

| 파일 | 테스트 수 | 설명 |
|------|----------:|------|
| `test_verifier.py` | 23 | 검증 조건 (URL, 요소, 텍스트) |
| `test_patch_system.py` | 25 | 패치 생성 및 적용 |
| `test_llm_planner.py` | 41 | LLM 계획 수립 및 요소 선택 |
| `test_coord_mapper.py` | 20 | 스크린샷-페이지 좌표 매핑 |
| `test_executor_pool.py` | 8 | 브라우저 세션 풀 관리 |
| `test_orchestrator.py` | 38 | 메인 오케스트레이션 루프 및 에스컬레이션 |
| `test_rule_promoter.py` | 27 | 패턴-규칙 승격 로직 |
| `test_step_queue.py` | 21 | FIFO 스텝 큐 연산 |
| `test_yolo_detector.py` | 21 | YOLO 객체 탐지 인터페이스 |
| `test_selector_cache.py` | 3 | 셀렉터 캐시 조회/저장 |
| `test_executor.py` | 32 | Playwright 브라우저 액션 |
| `test_image_batcher.py` | 20 | 이미지 배칭 및 리사이징 |
| `test_pattern_db.py` | 32 | 패턴 데이터베이스 CRUD |
| `test_vlm_client.py` | 19 | VLM API 클라이언트 |
| `test_exception_rules.py` | 36 | 예외 처리 규칙 (67개 규칙) |
| `test_prompt_manager.py` | 20 | 프롬프트 템플릿 버전 관리 |
| `test_extractor.py` | 23 | DOM 추출 및 JSON 변환 |
| `test_handoff.py` | 35 | 휴먼 핸드오프 인터페이스 |
| `test_memory_manager.py` | 44 | 4계층 메모리 시스템 |
| `test_fallback_router.py` | 55 | 실패 분류 및 라우팅 |
| `test_dspy_optimizer.py` | 16 | DSPy 최적화 |
| `test_evolution_pipeline.py` | 11 | 진화 파이프라인 상태 머신 |
| `test_dsl_parser.py` | 20 | YAML DSL 파싱 |
| `test_llm_orchestrator.py` | 5 | LLM-First 오케스트레이터 |
| `test_rule_engine.py` | 26 | 규칙 매칭 엔진 |
| `test_evolution_db.py` | 20 | 진화 데이터베이스 연산 |

### 4.2 통합 테스트 (95개, 3개 파일)

통합 테스트는 모듈 간 실제 인터페이스를 통한 연동을 검증합니다. 외부 서비스만 모킹됩니다.

| 파일 | 테스트 수 | 설명 |
|------|----------:|------|
| `test_engine_wiring.py` | 45 | 모듈 연결 및 의존성 주입 검증 |
| `test_api_integration.py` | 26 | API 엔드포인트 통합 (FastAPI TestClient) |
| `test_poc_script.py` | 24 | PoC 스크립트 엔드투엔드 흐름 |

### 4.3 E2E 테스트 (49개, 7+1개 파일)

E2E 테스트는 Playwright를 통해 실제 브라우저 인스턴스를 사용합니다. 브라우저 실행부터 결과 검증까지 완전한 사용자 시나리오를 검증합니다.

| 파일 | 테스트 수 | 설명 |
|------|----------:|------|
| `test_executor_e2e.py` | 8 | 브라우저 자동화 E2E |
| `test_selectors_e2e.py` | 6 | CSS 셀렉터 전략 |
| `test_verifier_e2e.py` | 9 | 실제 페이지를 사용한 검증 |
| `test_chain_e2e.py` | 5 | 다단계 액션 체인 |
| `test_evolution_e2e.py` | 7 | 진화 파이프라인 E2E |
| `test_evolution_ui_e2e.py` | 6 | UI + API E2E (Playwright 브라우저 테스트) |
| `test_extractor_e2e.py` | 8 | 실제 페이지에서 DOM 추출 |
| `test_live_sites.py` | 2 | 라이브 웹사이트 테스트 (인터넷 연결 필요) |

> **참고:** `test_live_sites.py`는 실제 외부 웹사이트에 접속하므로 인터넷 연결이 필요합니다. 이 테스트들은 `@pytest.mark.live`로 마킹되어 있으며, 오프라인 또는 CI 환경에서는 건너뛸 수 있습니다.

## 5. Pytest 마커

| 마커 | 설명 | 사용법 |
|------|------|--------|
| `e2e` | 브라우저가 필요한 엔드투엔드 테스트 | `pytest -m e2e` |
| `live` | 실제 웹사이트에 접속하는 테스트 | `pytest -m live` |

기본적으로 **e2e와 live 테스트는 제외되지 않으며**, `pytest tests/` 실행 시 함께 실행됩니다. 제외하려면 다음과 같이 합니다:

```bash
# E2E 테스트 제외
pytest tests/ -m "not e2e"

# 라이브 사이트 테스트 제외
pytest tests/ -m "not live"

# 둘 다 제외
pytest tests/ -m "not e2e and not live"
```

## 6. 픽스처 및 Conftest

### 공유 설정

프로젝트의 `conftest.py`는 `tests/` 루트에 위치하며, 모든 테스트 계층에서 사용하는 공유 픽스처를 제공합니다.

### 주요 픽스처

- **pytest-asyncio** `asyncio_mode = "auto"` 설정 -- 모든 `async def` 테스트 함수가 자동으로 감지되어 이벤트 루프에서 실행됩니다. `@pytest.mark.asyncio` 불필요.
- **Playwright 픽스처** -- E2E 브라우저 테스트를 위한 `page`, `context`, `browser` 픽스처 제공.
- **임시 데이터베이스 픽스처** -- DB 테스트용 인메모리 또는 임시 파일 SQLite 데이터베이스. 각 테스트 후 자동 정리.
- **모킹 픽스처** -- LLM 클라이언트, Vision 모듈 등 외부 서비스에 대한 사전 구성된 목 객체.

### 픽스처 스코프

| 픽스처 유형 | 스코프 | 비고 |
|------------|--------|------|
| Browser | session | E2E 테스트 전체에서 공유되는 브라우저 인스턴스 |
| Context | function | 테스트마다 새 브라우저 컨텍스트 |
| Page | function | 테스트마다 새 페이지 |
| Database | function | 테스트마다 깨끗한 데이터베이스 |
| Mocks | function | 테스트마다 초기화 |

## 7. 새 테스트 작성 가이드

### 파일 및 함수 네이밍

- **파일명:** `test_<모듈명>.py`
- **테스트 함수명:** `test_<동작>` 또는 `test_<모듈>_<시나리오>`
- 단위 테스트는 `tests/unit/`, 통합 테스트는 `tests/integration/`, E2E 테스트는 `tests/e2e/`에 배치합니다.

### 가이드라인

1. Playwright 또는 aiosqlite를 사용하는 테스트는 `async def`로 작성합니다.
2. E2E 테스트에는 `@pytest.mark.e2e`를 붙입니다.
3. 라이브 사이트 테스트에는 `@pytest.mark.live`를 붙입니다.
4. 새 픽스처를 만들기보다 `conftest.py`의 기존 픽스처를 활용합니다.
5. 단위 테스트는 빠르게 유지합니다 -- 모든 외부 의존성을 모킹합니다.
6. 각 테스트는 독립적이어야 하며, 실행 순서에 의존해서는 안 됩니다.

### 예제: 비동기 E2E 테스트

```python
import pytest


@pytest.mark.e2e
async def test_executor_clicks_button(page):
    await page.goto("https://example.com")
    await page.click("button#submit")
    assert await page.title() == "Success"
```

### 예제: 모킹을 사용한 단위 테스트

```python
from unittest.mock import AsyncMock


async def test_planner_returns_steps():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"steps": [{"action": "click", "selector": "#btn"}]}'

    planner = LLMPlanner(llm_client=mock_llm)
    result = await planner.plan("Click the submit button")

    assert len(result.steps) == 1
    assert result.steps[0].action == "click"
```

### 예제: 데이터베이스 테스트

```python
async def test_pattern_db_insert(tmp_path):
    db = PatternDB(db_path=str(tmp_path / "test.db"))
    await db.initialize()

    await db.save_pattern(site="example.com", intent="login", selector="#login-btn")
    pattern = await db.lookup(site="example.com", intent="login")

    assert pattern is not None
    assert pattern.selector == "#login-btn"
```

## 8. CI/CD 테스트

일반적인 CI 파이프라인은 다음 단계를 순서대로 실행해야 합니다:

### 1단계: 정적 분석

```bash
# 린트 (자동 수정)
ruff check --fix

# 타입 검사
mypy --strict
```

### 2단계: 단위 및 통합 테스트

```bash
pytest tests/unit tests/integration
```

이 테스트들은 빠르고, 브라우저가 불필요하며, 대부분의 회귀 버그를 잡아냅니다.

### 3단계: 전체 테스트 스위트

```bash
pytest tests/
```

E2E 테스트가 포함되므로 Playwright 브라우저가 설치되어 있어야 합니다:

```bash
playwright install chromium
```

### 권장 CI 설정

```yaml
# 예시: GitHub Actions
steps:
  - name: 린트
    run: ruff check --fix

  - name: 타입 검사
    run: mypy --strict

  - name: Playwright 설치
    run: playwright install chromium

  - name: 단위 및 통합 테스트
    run: pytest tests/unit tests/integration -v

  - name: E2E 테스트
    run: pytest tests/e2e -v -m "not live"

  - name: 전체 스위트 (선택)
    run: pytest tests/ -v
```

> **팁:** CI 환경에서는 `-m "not live"` 옵션으로 외부 웹사이트에 의존하는 테스트를 건너뛰는 것을 권장합니다. 네트워크 상태나 사이트 변경으로 인한 불안정한 실패를 방지할 수 있습니다.
