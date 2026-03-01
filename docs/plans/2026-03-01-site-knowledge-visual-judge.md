# Site Knowledge + Visual Judge + Planner 체계 개선 — Implementation Record

**Date:** 2026-03-01
**Status:** Implemented (Phase 1 + Phase 2)

**Design Doc:** `docs/plans/2026-03-01-site-knowledge-visual-judge-design.md`

---

## Phase 1: Site Knowledge Cache + Visual Attribute Judgment

### Task 1: SiteKnowledgeStore — JSON-based per-domain knowledge (DONE)

**Files:**
- `src/learning/site_knowledge.py` — SiteKnowledgeStore, merge_knowledge(), render_knowledge()
- `tests/unit/test_site_knowledge.py`

**구현 내용:**
- 도메인별 JSON 파일 (`data/site_knowledge/{domain}.json`)
- LLM 병합: 기존 지식 + 새 실행 이력 → Flash LLM이 병합 (deterministic fallback)
- render_knowledge(): JSON → compact markdown (실패 > 성공 > 팁 우선순위)
- 최대 5개 항목/카테고리, 800자 렌더링 제한
- 카테고리 메뉴 클릭 실패 → 자동 "hover로 열기" 대안 제안

### Task 2: StepPlan 확장 (DONE)

**Files:**
- `src/core/types.py` — StepPlan에 `visual_filter_query`, `visual_complexity` 필드 추가
- `tests/unit/test_types_visual.py`

### Task 3: Planner — site_knowledge 주입 + visual_filter 프롬프트 (DONE)

**Files:**
- `src/core/planner.py` — plan()에 site_knowledge 파라미터, visual_filter 프롬프트 추가
- `tests/unit/test_planner.py`

### Task 4: VisualJudge — RF-DETR → VLM 에스컬레이션 (DONE)

**Files:**
- `src/vision/visual_judge.py` — VisualJudge, JudgedItem
- `src/vision/rfdetr_detector.py` — RFDETRDetector (IDetector protocol)
- `tests/unit/test_visual_judge.py`

**구현 내용:**
- IDetector protocol: `async detect(screenshot) -> list[Detection]`
- RF-DETR 우선, 실패 시 YOLO 폴백
- 탐지 → crop → 그리드 생성 → VLM 분류 → JudgedItem 리스트

### Task 5: V3Orchestrator — visual_filter + site_knowledge 통합 (DONE)

**Files:**
- `src/core/v3_orchestrator.py` — _execute_visual_filter(), site_knowledge 주입, save_run()
- `tests/unit/test_v3_orchestrator.py`

**구현 내용:**
- `visual_filter` 스텝 → VisualJudge 호출 → 매칭 아이템 클릭
- 모든 plan() 호출에 site_knowledge 전달
- 성공/실패 후 site_knowledge 자동 저장 (LLM merge)

### Task 6: V3Factory 배선 (DONE)

**Files:**
- `src/core/v3_factory.py` — VisualJudge, SiteKnowledgeStore 인스턴스 생성 + 오케스트레이터 주입

---

## Phase 2: Planner 프롬프트 강화 + 프롬프트 버전닝 + 구조화 출력

### 근본 원인 분석

Danawa 라이브 테스트에서 4가지 문제 발견:
1. 가격 입력이 메인 검색창에 들어감 — keyword_weights가 가격 필터 영역 미구분
2. "레드"가 보이는데 "더보기" 클릭 — 불필요한 스텝
3. 7스텝 후 타임아웃 (428s > 420s) — visual_filter까지 미도달
4. visual_filter 미실행 — 사이트 지식 "체크박스가 더 정확" 팁이 잘못 유도

**근본 원인**: 잘못된 사이트 지식 팁 → Planner가 사이트 필터 UI 선호 → 스텝 증가 → 타임아웃

### Task 7: Planner 프롬프트 강화 (DONE)

**File:** `src/core/planner.py`

**변경:**
- visual_filter 우선순위 강화: "사이트 색상 필터 UI가 있어도 사용하지 마세요"
- type 액션 입력 필드 구별: 상단 검색창 vs 필터 입력 (target_viewport_xy 기반)
- 더보기 스킵: "대상이 화면에 보이면 더보기 건너뛰세요"

### Task 8: 프롬프트 버전닝 분리 (DONE)

**Files:**
- `config/prompts/v3_check_screen/v1.txt` — check_screen 프롬프트 v1
- `config/prompts/v3_plan/v1.txt` — plan 프롬프트 v1
- `src/core/planner.py` — PromptManager 옵셔널 DI

**구현 내용:**
- `Planner(vlm=..., prompt_manager=pm)` — PM 있으면 PM에서 로드, 없으면 인라인 폴백
- PromptManager는 `$task` (string.Template), 인라인은 `{task}` (str.format)
- 새 버전: `config/prompts/v3_plan/v2.txt` 만들면 자동 latest

**테스트 (4개 신규):**
- `test_plan_uses_prompt_manager` — PM에서 프롬프트 로드 확인
- `test_check_screen_uses_prompt_manager` — check_screen도 PM 사용
- `test_fallback_when_no_prompt_manager` — PM 없을 때 인라인 사용
- `test_fallback_when_prompt_not_registered` — PM에 프롬프트 없을 때 인라인 폴백

### Task 9: 구조화 출력 (Gemini JSON mode) (DONE)

**Files:**
- `src/core/v3_adapters.py` — GeminiVisionAdapter에 `json_mode: bool` 추가
- `src/core/v3_factory.py` — `GeminiVisionAdapter(json_mode=True)` 전달

**구현 내용:**
- `json_mode=True` → Gemini API에 `response_mime_type="application/json"` 전달
- LLM이 항상 유효한 JSON 반환 (markdown fencing 없음)
- 기존 `_extract_json_array/object()` 파서 유지 (방어적 폴백)

### Task 10: 타임아웃 + Post-completion (DONE)

**File:** `src/core/v3_orchestrator.py`

**변경:**
- `DEFAULT_TIMEOUT_S: 420.0 → 600.0` (10분)
- Post-completion 프롬프트에 visual_filter 안내 추가

### Task 11: 사이트 지식 안전장치 (DONE)

**File:** `src/learning/site_knowledge.py`

**변경:**
- LLM 병합 규칙 #6: "visual_filter보다 사이트 필터가 좋다" 류 팁 생성 금지
- `data/site_knowledge/prod.danawa.com.json` 삭제 (잘못된 팁 제거)

---

## Verification Results

```
# Unit + Integration
1708 passed, 6 skipped (77s)

# Ruff
All checks passed (pre-existing SIM105 1건 제외)

# Planner tests (36)
36 passed (1s) — PromptManager 통합 4개 포함

# V3 Orchestrator tests (76)
76 passed (44s) — visual_filter + site_knowledge 통합 포함
```

## File Change Summary

| 파일 | 상태 | 설명 |
|---|---|---|
| `src/learning/site_knowledge.py` | Modified | JSON merge, anti-visual_filter 규칙 |
| `src/core/types.py` | Modified | visual_filter_query, visual_complexity |
| `src/core/planner.py` | Modified | PromptManager DI, 프롬프트 강화 |
| `src/core/v3_orchestrator.py` | Modified | timeout 600s, visual_filter, site_knowledge, post-completion |
| `src/core/v3_adapters.py` | Modified | json_mode support |
| `src/core/v3_factory.py` | Modified | PromptManager + json_mode + VisualJudge + SiteKnowledgeStore |
| `src/vision/visual_judge.py` | New | RF-DETR → VLM 판별기 |
| `src/vision/rfdetr_detector.py` | New | RF-DETR async detector |
| `config/prompts/v3_check_screen/v1.txt` | New | check_screen 프롬프트 v1 |
| `config/prompts/v3_plan/v1.txt` | New | plan 프롬프트 v1 |
| `data/site_knowledge/prod.danawa.com.json` | Deleted | 잘못된 팁 제거 |
| `tests/unit/test_planner.py` | Modified | PromptManager 테스트 4개 추가 |
| `tests/unit/test_site_knowledge.py` | New | JSON merge/render 테스트 |
| `tests/unit/test_visual_judge.py` | New | 판별기 테스트 |
| `tests/unit/test_types_visual.py` | New | StepPlan 필드 테스트 |
