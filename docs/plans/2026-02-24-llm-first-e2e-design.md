# LLM-First Orchestrator + 네이버 쇼핑 E2E 설계

## 목표

LLM이 주체인 웹 자동화 엔진을 구현하고, 네이버 쇼핑에서 실제 E2E 테스트를 headful 브라우저로 실행한다.

## 플로우

```
사용자 의도: "네이버 쇼핑에서 노트북 검색해서 인기순 정렬"
    ↓
[1] LLM Plan — 의도를 atomic 스텝으로 분해
    → step1: goto https://shopping.naver.com
    → step2: 검색창에 "노트북" 입력
    → step3: 검색 버튼 클릭
    → step4: 인기순 정렬 클릭
    ↓
[2] 각 스텝 실행:
    ├─ 캐시 히트? → 저장된 셀렉터로 바로 실행 (LLM 호출 $0)
    ├─ 캐시 미스 → DOM 추출 → LLM이 후보 중 선택 → 실행
    ↓
[3] 실행 후:
    ├─ 스크린샷 캡처 (매 스텝, data/screenshots/)
    ├─ 검증 (URL/텍스트/요소)
    ├─ 성공 → 셀렉터 캐시 저장 → 다음 스텝
    └─ 실패 → LLM 신뢰도 < 0.7이면 Vision → 재시도 (최대 3회)
```

## 신규/변경 파일

| 파일 | 유형 | 역할 |
|------|------|------|
| `src/core/llm_orchestrator.py` | 신규 | LLM-First 오케스트레이터 |
| `src/core/selector_cache.py` | 신규 | PatternDB 래핑, TTL 기반 캐시 |
| `src/ai/llm_planner.py` | 수정 | plan() 프롬프트 개선, 페이지 컨텍스트 추가 |
| `scripts/run_live.py` | 신규 | Headful 실행 + 스크린샷 저장 러너 |

## 기존 모듈 재사용 (변경 없음)

- Executor (X) — Playwright 래퍼
- Extractor (E) — DOM 추출
- Verifier (V) — 상태 검증
- VLMClient — Vision 폴백 (선택적)

## LLMFirstOrchestrator 설계

```python
class LLMFirstOrchestrator:
    async def run(intent: str) -> RunResult:
        # 1. LLM으로 스텝 분해
        steps = await planner.plan(intent)

        for step in steps:
            result = await self.execute_step(step)
            # 매 스텝 스크린샷
            await self._capture_screenshot(step)
            if not result.success:
                return RunResult(success=False, failed_step=step)

        return RunResult(success=True)

    async def execute_step(step) -> StepResult:
        # 1. 캐시 조회
        cached = await cache.lookup(step.intent, site)
        if cached:
            return await self._execute_cached(cached, step)

        # 2. DOM 추출 + LLM 선택
        candidates = await extractor.extract_clickables(page)
        patch = await planner.select(candidates, step.intent)

        # 3. 실행
        await executor.execute(patch.target, step.action, step.arguments)

        # 4. 검증
        verify = await verifier.verify(page, step.verify_condition)

        # 5. 성공 시 캐시 저장
        if verify.success:
            await cache.save(step.intent, site, patch.target)

        return StepResult(success=verify.success)
```

## SelectorCache 설계

```python
class SelectorCache:
    """PatternDB를 래핑한 셀렉터 캐시. TTL 기반 유효성 관리."""

    async def lookup(intent, site) -> CacheHit | None
    async def save(intent, site, selector, method) -> None
    async def invalidate(intent, site) -> None  # 실패 시
```

## E2E 테스트 시나리오 (네이버 쇼핑)

```
의도: "네이버 쇼핑에서 노트북 검색해서 인기순 정렬"

검증 포인트:
1. shopping.naver.com 로딩 확인
2. 검색창 발견 + "노트북" 입력 확인
3. 검색 실행 후 URL에 "query=노트북" 포함 확인
4. 인기순 정렬 버튼 클릭 확인
5. 매 스텝 스크린샷 data/screenshots/에 저장
6. 2회차 실행 시 LLM 호출 0회 (캐시 히트) 확인
```

## 비용 예상

- 스텝 분해: ~$0.01 (Gemini Flash, 1회)
- 요소 선택: ~$0.002/스텝 × 4스텝 = $0.008
- 첫 실행 총: ~$0.018
- 2회차 (캐시): $0

## 실행 방법

```bash
GEMINI_API_KEY=xxx python scripts/run_live.py \
    --intent "네이버 쇼핑에서 노트북 검색해서 인기순 정렬" \
    --headful
```
