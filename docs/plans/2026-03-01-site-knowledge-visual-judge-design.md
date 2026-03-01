# Design: Site Knowledge + Visual Judge + Planner 프롬프트 체계 개선

**Date:** 2026-03-01
**Status:** Implemented

## Problem

### Phase 1 — 사이트 지식 + 시각 판별 부재
1. **사이트 재방문 시 학습 없음**: 같은 사이트를 반복 방문해도 매번 VLM이 처음부터 탐색. 메뉴 구조, 필터 위치 등 학습된 정보 미활용.
2. **시각적 판별 부재**: "빨간색 등산복" 같은 시각적 속성 요청 시 사이트 UI 필터에만 의존. 문양/소매길이 등 복잡한 시각 속성 판별 불가.

### Phase 2 — Danawa 라이브 테스트 문제 (Phase 1 구현 후 발견)
3. **가격 입력이 메인 검색창에 들어감**: keyword_weights가 가격 필터 영역을 구분하지 못함.
4. **"레드"가 화면에 보이는데 "더보기" 클릭**: 불필요한 스텝 낭비.
5. **7스텝 후 타임아웃(428s > 420s)**: visual_filter까지 도달 못함.
6. **visual_filter 미실행**: 사이트 지식 팁 "체크박스가 시각적 판별보다 정확" → Planner가 사이트 필터 UI 사용 → 스텝 증가 → 타임아웃.
7. **프롬프트 버전닝 없음**: v3 Planner/Actor 프롬프트가 인라인 하드코딩. A/B 테스트 불가.
8. **구조화 출력 미사용**: VLM이 자유 텍스트 출력 → regex 파싱 → 실패 가능성.

## Solution

### A. Site Knowledge Cache — 도메인별 JSON 파일

**저장 구조:**
```
data/site_knowledge/
  danawa.com.json
  shopping.naver.com.json
```

**JSON 스키마:**
```json
{
  "domain": "danawa.com",
  "version": 1,
  "successful_paths": [
    {"task": "태스크명", "steps": ["[click] 메뉴", "[hover] 카테고리"], "last_success": "ISO"}
  ],
  "failed_approaches": [
    {"step": "[click] 카테고리 메뉴", "reason": "메뉴 닫힘", "alternative": "hover로 열기", "failed_at": "ISO"}
  ],
  "tips": ["카테고리 메뉴는 hover로 열어야 함"]
}
```

**생성/업데이트**: 태스크 완료 후 LLM이 기존 JSON과 실행 이력을 병합 (deterministic fallback 포함).
**활용**: Planner `plan()` 호출 시 `render_knowledge()` 결과를 프롬프트에 주입.
**안전장치**: 병합 규칙 #6 — "visual_filter보다 사이트 필터가 좋다" 류의 팁 생성 금지.

### B. Visual Attribute Judgment — RF-DETR/YOLO → VLM 에스컬레이션

**핵심**: 사이트 UI 필터에 의존하지 않고, 상품 이미지를 직접 보고 시각적 속성 판별.

**2단계 체인:**
- **Stage 1**: RF-DETR/YOLO로 상품 카드 영역 탐지 ($0)
- **Stage 2**: 카드 이미지 crop → 그리드 생성 → VLM 분류 ($0.003)

**복잡도:**
- `simple` (색상, 기본 형태): RF-DETR 탐지 후 VLM 분류
- `complex` (문양, 소재, 디자인): 항상 VLM 분류

**StepPlan 확장:**
```python
@dataclass
class StepPlan:
    # 기존 필드...
    visual_filter_query: str | None = None   # "빨간색", "긴 소매"
    visual_complexity: str | None = None      # "simple" | "complex"
```

### C. Planner 프롬프트 강화

**visual_filter 우선순위:**
```
시각적 판별 (visual_filter) — 시각 속성 필터링의 기본 수단:
- 색상, 문양, 소재 등 시각적 속성 → 반드시 visual_filter.
- 사이트 색상 필터 UI가 있어도 사용하지 마세요.
  visual_filter 1개 스텝이 사이트 필터 여러 스텝보다 정확하고 빠릅니다.
- 전형적 흐름: 카테고리 → 비시각 필터(가격) → scroll → visual_filter
```

**입력 필드 구별:**
```
- type 액션에서 입력 필드 구별 (매우 중요):
  - 상단 메인 검색창: "검색", "통합검색" — target_viewport_xy 상단 중앙
  - 필터/상세검색: "가격", "최소", "최대" — target_viewport_xy 좌측/하단
```

**더보기 스킵:** 대상 항목이 이미 화면에 보이면 '더보기/펼치기' 건너뛰기.

### D. 프롬프트 버전닝 분리

**기존 문제**: v3 Planner 프롬프트가 `planner.py`에 인라인 하드코딩.
**해결**: `config/prompts/` 디렉토리에 버전별 `.txt` 파일로 분리.

```
config/prompts/
  v3_check_screen/v1.txt   # 장애물 감지 프롬프트
  v3_plan/v1.txt            # 태스크 분해 프롬프트
```

**로드 흐름:**
1. `PromptManager`가 `config/prompts/` 에서 모든 프롬프트 로드
2. `Planner(vlm=..., prompt_manager=pm)` — 선택적 DI
3. PM 있으면 PM에서 로드, 없으면 인라인 폴백 (하위 호환)

**프롬프트 변수:**
- PromptManager: `$task` (string.Template)
- 인라인 폴백: `{task}` (str.format)

### E. 구조화 출력 (Gemini JSON mode)

**기존**: `generate_with_image()` → 자유 텍스트 → regex로 JSON 추출
**개선**: `GeminiVisionAdapter(json_mode=True)` → Gemini에 `response_mime_type="application/json"` 전달 → 항상 유효한 JSON 반환

**파싱 안전장치 유지**: JSON mode에서도 `_extract_json_array/object()` 폴백 파서 유지 (방어적).

### F. 타임아웃 증가

`DEFAULT_TIMEOUT_S: 420.0 → 600.0` (7분 → 10분)
VLM 호출 1회당 10-70초, 7+ 스텝 + replan 시 420초 부족.

### G. Post-completion 프롬프트 — visual_filter 안내

태스크 완료 후 추가 스텝 확인 시:
```
시각적 속성(색상, 문양 등)으로 상품을 찾아야 하면
visual_filter 스텝을 사용하세요.
사이트 필터 UI 대신 visual_filter가 우선입니다.
```

## Implementation — Modified Files

| 파일 | 변경 | Phase |
|---|---|---|
| `src/learning/site_knowledge.py` | SiteKnowledgeStore (JSON), LLM merge, render_knowledge() | 1 |
| `src/core/types.py` | StepPlan에 visual_filter_query, visual_complexity 추가 | 1 |
| `src/vision/visual_judge.py` | RF-DETR/YOLO → VLM 2단계 판별기 | 1 |
| `src/vision/rfdetr_detector.py` | RF-DETR async detector (IDetector protocol) | 1 |
| `src/core/v3_orchestrator.py` | visual_filter 핸들러, site_knowledge 통합, timeout 600s, post-completion visual_filter 안내 | 1+2 |
| `src/core/v3_factory.py` | VisualJudge + SiteKnowledgeStore + PromptManager 배선, json_mode=True | 1+2 |
| `src/core/v3_adapters.py` | GeminiVisionAdapter json_mode 지원 | 2 |
| `src/core/planner.py` | PromptManager DI, visual_filter 프롬프트 강화, 입력 필드 구별, 더보기 스킵 | 2 |
| `config/prompts/v3_check_screen/v1.txt` | check_screen 프롬프트 v1 | 2 |
| `config/prompts/v3_plan/v1.txt` | plan 프롬프트 v1 | 2 |

## Testing

```bash
# Phase 1 테스트
tests/unit/test_site_knowledge.py         # JSON load/save/merge/render
tests/unit/test_visual_judge.py           # RF-DETR→VLM 에스컬레이션
tests/unit/test_types_visual.py           # StepPlan 필드 확인

# Phase 2 테스트
tests/unit/test_planner.py               # PromptManager 통합 (4개 신규)
tests/unit/test_v3_orchestrator.py        # visual_filter + site_knowledge

# 전체 검증
python -m pytest tests/unit/ tests/integration/ -x -q          # 1708 passed
python -m pytest tests/e2e/ -x -q -m "not live"
ruff check src/ tests/ --fix
```

## Live Test Results

### Danawa 8-step flow (Phase 1 이후)
- **결과**: SUCCESS 8/8, $0.0079, 288s
- **흐름**: hover 스포츠·골프 → 여성스포츠의류 → 등산복 → scroll → type 가격 → click 검색 → 색상 더보기 → click 레드 → scroll

### Wikipedia Python 검색
- **결과**: SUCCESS 2/2, $0.0019, 37s

### Phase 2 개선 (올바른 흐름)
- **기대**: 카테고리 이동 → 가격 필터 → scroll → **visual_filter**(빨간색)
- **스텝 수**: 8 → 5~6 (사이트 필터 UI 대신 visual_filter 사용)
- **타임아웃**: 600s로 여유 확보
