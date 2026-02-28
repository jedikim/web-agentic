# Danawa E2E Iterative Fix Design

**Date:** 2026-02-26
**Goal:** danawa.com에서 스포츠/골프 → 여성스포츠의류 → 등산복 → 10만원 이하 → 붉은색 옷 찾기

## Run 1 Analysis (FAILED, 28 steps, $0.19)

### Problem 1: Selector newlines crash Playwright
- LLM returns `a:has-text("건강/취미/스포츠\n\t\t\t")` → BADSTRING error
- All hover/click attempts on such selectors fail silently
- **Root cause:** Element text has whitespace/newlines that LLM includes verbatim

### Problem 2: Price "100000" typed into search bar
- Step 7: Only 1 input extracted (`#AKCSearch` = search bar), confidence 0.05
- Typed "100000" → triggered full-text search → left category page entirely
- **Root cause:** Category dropdown overlay still visible, price filter not yet on page

### Problem 3: visual_evaluate always fails
- `ultralytics` package not installed → YOLO detection unavailable
- 3 retries → replan loop → cost explosion
- **Root cause:** Missing pip dependency

### Problem 4: Replan loops restart from scratch
- visual_evaluate fails → replan → navigates back to home → drills down again
- 3 full replan cycles before cost limit hit

### Problem 5: Color filter clicked wrong element
- Selected `"P431T7KM 빨강"` (toner color option on wrong page)
- Not on hiking clothes category at all

## Fixes

### Fix 1: Selector Sanitization (`llm_orchestrator.py`)
Normalize LLM-returned selectors before passing to Playwright:
- Replace `\n`, `\t`, `\r` with single space
- Collapse multiple spaces
- Apply to all `wait_for_selector()`, `click()`, `hover()` calls

### Fix 2: Install ultralytics (`pip install -e '.[vision]'`)
Enable YOLO26 → batch_vision_pipeline → visual_evaluate works

### Fix 3: Prompt Improvement (`plan_steps_with_context`)
- "가격 필터는 상품 목록 페이지에 도착한 후에만 사용"
- "카테고리 드릴다운이 완료되어 상품이 보이는 상태에서만 필터 조작"
- "검색바와 가격 필터 입력란을 혼동하지 말 것"

### Fix 4: Replan preserves progress
- On visual_evaluate failure, don't replan from scratch
- Skip failed visual_evaluate and continue with remaining steps

### Fix 5: Input field disambiguation
- Structural filter should not aggressively filter input fields when step is "type"
- Parent context (e.g. "가격", "검색") helps LLM distinguish

## Additional Fixes (Run 2-5)

### Fix 6: crop_regions bbox clipping (`image_batcher.py`)
- YOLO detections can produce bboxes outside screenshot bounds
- After clamping, zero-size crops crashed PIL with "tile cannot extend outside image"
- Added minimum 2px check + placeholder image for degenerate crops

### Fix 7: Bbox pre-filtering (`llm_orchestrator.py`)
- Filter out YOLO bboxes that don't overlap with the screenshot area before grid creation

### Fix 8: Duplicate-click guard (`llm_orchestrator.py`)
- Track all selectors used in hover/click steps
- If LLM selects an already-used selector, fail the step immediately
- Prevents wasting LLM calls on re-selection of the same element

### Fix 9: Search fallback on navigation failure (`llm_orchestrator.py`)
- Lowered click failure threshold from 6 to 2 for search strategy redirect
- Replan instruction now says "SWITCH STRATEGY: Use the SEARCH box"
- On danawa.com, category navigation through sidebar is unreliable (subcategories not directly accessible)

### Fix 10: Subcategory page navigation prompt (`plan_steps_with_context`)
- Added guidance for navigating subcategory pages
- Explicit instruction to use search as backup when subcategory links can't be found

## Run Results

| Metric | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|---|---|---|---|---|---|
| Steps | 28 | 15 | 13 | 10 | 18 |
| Cost | $0.19 | $0.13 | $0.07 | $0.17 | $0.11 |
| Result | FAIL | FAIL | FAIL | FAIL | **SUCCESS** |
| BADSTRING | Many | 0 | 0 | 0 | 0 |
| Price filter | Search bar | Search bar | Search bar | N/A | **#priceRangeMaxPrice** |
| visual_evaluate | Crash | Crash→Skip | Runs (no match) | N/A | **Found match** |
| Product selected | No | No | No | No | **Yes (23,990원)** |

### Run 5 Flow (SUCCESS)
1. Hover "전체 카테고리" → hover "스포츠·골프" → subcategory click fails (duplicate guard) → replan
2. Replan → search "여성 등산복" → search results page with hiking clothes
3. Scroll → type "100000" into #priceRangeMaxPrice → click #priceRangeSearchButton
4. Scroll → click "상품 색상" (color filter section)
5. visual_evaluate: VLM found "reddish/pink women's fleece jacket" → clicked
6. Final: selected product at 23,990원

## Key Learnings

1. **Complex dropdown menus are unreliable for LLM-based automation** — subcategories may not appear in extracted candidates. Search fallback is essential.
2. **Duplicate-click detection saves cost** — failing immediately on duplicate is cheaper than re-selecting random alternatives.
3. **YOLO detections can exceed image bounds** — always clamp and validate before cropping.
4. **Selector sanitization is critical** — LLM often includes raw whitespace from DOM text in `:has-text()` selectors.
5. **visual_evaluate with VLM fallback works** — even when YOLO detection is generic (COCO model), the LLM multimodal analysis can identify visual attributes (color).

## Verification

```bash
python scripts/run_live.py \
  --intent "스포츠/골프 메뉴에서 여성스포츠의류 카테고리의 등산복을 찾아서 10만원 이하 가격 필터를 설정하고 붉은색 등산복을 찾아줘" \
  --url "https://www.danawa.com" \
  --headless
```

Check Langfuse traces at https://langfuse.jedi.team for:
- Step count reduction
- Cost reduction
- Selector success rate
- visual_evaluate execution
