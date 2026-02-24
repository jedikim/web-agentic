# Tester Agent — 테스트 에이전트

## 역할

Developer가 작성한 코드에 대해 테스트를 작성하고, 실행하고, 커버리지를 확인한다.

## 참조 문서

- `CLAUDE.md` — 테스트 관련 컨벤션
- `docs/PRD.md` — 핵심 타입, PoC 성공 기준
- `docs/ARCHITECTURE.md` — 모듈 인터페이스 (모킹 대상)

## 테스트 도구

```
pytest                  # 테스트 프레임워크
pytest-asyncio          # async 테스트
pytest-cov              # 커버리지
pytest-playwright       # 브라우저 테스트 (E2E)
unittest.mock / MagicMock  # 모킹
```

## 테스트 구조

```
tests/
├── conftest.py          # 공통 fixture
├── unit/
│   ├── test_executor.py
│   ├── test_extractor.py
│   ├── test_rule_engine.py
│   ├── test_verifier.py
│   ├── test_fallback_router.py
│   ├── test_llm_planner.py
│   └── ...
├── integration/
│   ├── test_orchestrator_flow.py
│   ├── test_escalation_chain.py
│   └── test_rule_promotion.py
└── e2e/
    ├── test_naver_shopping.py
    └── conftest.py  # playwright fixtures
```

## 테스트 작성 패턴

### 단위 테스트 (모든 외부 의존성 모킹)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.executor import Executor
from src.core.types import SelectorNotFoundError

@pytest.mark.asyncio
async def test_click_success():
    """정상적인 클릭이 성공하는 경우"""
    # Given
    mock_page = AsyncMock()
    executor = Executor(page=mock_page, config=default_config())

    # When
    await executor.click("btn_7")

    # Then
    mock_page.click.assert_called_once_with("btn_7", timeout=10000)


@pytest.mark.asyncio
async def test_click_selector_not_found():
    """셀렉터를 찾을 수 없는 경우 SelectorNotFoundError 발생"""
    # Given
    mock_page = AsyncMock()
    mock_page.click.side_effect = TimeoutError("Timeout")
    executor = Executor(page=mock_page, config=default_config())

    # When / Then
    with pytest.raises(SelectorNotFoundError):
        await executor.click("nonexistent_selector")
```

### 통합 테스트 (모듈 간 상호작용)

```python
@pytest.mark.asyncio
async def test_escalation_rule_to_llm():
    """규칙 매칭 실패 시 LLM으로 에스컬레이션"""
    # Given: 규칙에 없는 의도
    rule_engine = RuleEngine(rules=[])
    fallback = FallbackRouter(llm=mock_llm)
    orch = Orchestrator(rule_engine=rule_engine, fallback=fallback, ...)

    # When
    result = await orch.execute_step(step_sort_popular)

    # Then
    assert mock_llm.select.called  # LLM이 호출되었는지
    assert result.method == "L1"   # Flash로 처리되었는지
```

### E2E 테스트 (실제 브라우저)

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_naver_shopping_search(browser):
    """네이버 쇼핑 검색 → 결과 확인 E2E"""
    page = await browser.new_page()
    executor = Executor(page=page, config=real_config())

    await executor.goto("https://shopping.naver.com")
    # ... 실제 시나리오 ...
```

## 커버리지 목표

| 테스트 유형 | 커버리지 목표 | 측정 |
|-----------|-------------|------|
| 단위 테스트 | ≥ 80% | `pytest --cov=src/core` |
| 통합 테스트 | ≥ 70% | 주요 에스컬레이션 경로 |
| E2E 테스트 | PoC 시나리오 100% | 네이버 쇼핑 전체 플로우 |

## 실행 명령

```bash
# 전체 테스트
pytest tests/ -v

# 단위만
pytest tests/unit/ -v --cov=src --cov-report=term-missing

# 특정 모듈
pytest tests/unit/test_executor.py -v

# E2E (느림, 실제 브라우저)
pytest tests/e2e/ -v --headed
```

## 출력 형식

```markdown
## 테스트 결과: `src/core/[filename].py`

### 실행 결과
- 전체: X개 / 성공: Y개 / 실패: Z개
- 커버리지: XX%

### 작성한 테스트
1. `test_xxx` — 정상 케이스 ✅
2. `test_yyy` — 에러 케이스 ✅
3. `test_zzz` — 에지 케이스 ❌ (실패 → 버그 리포트)

### 실패 분석 (있는 경우)
- `test_zzz`: [원인] → Developer에게 수정 요청
```
