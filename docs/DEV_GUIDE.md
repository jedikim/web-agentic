# 개발 가이드 — v4.3 적응형 웹 자동화 엔진

> AI 에이전트가 개발 시 참조하는 문서. 결정된 사항만 기술.
> 상세 설계는 `RECON_CODEGEN_ARCHITECTURE.md` 참조.

---

## 기술 스택

| 용도 | 도구 | 패키지 |
|------|------|--------|
| 워크플로우 | LangGraph | `langgraph` |
| LLM 라우팅 | LiteLLM Router | `litellm` |
| 브라우저 | Playwright (async) | `playwright` |
| DOM 심층 추출 | CDP (Playwright CDPSession) | Playwright 내장 |
| 객체 탐지 | YOLO26 (CPU) / RT-DETRv4 (GPU) | `ultralytics` / GitHub |
| LLM/VLM | Gemini 3 Flash/3.1 Pro 또는 GPT-5 mini/5.3 Codex (벤더 자동 선택) | `litellm` |
| 프롬프트 최적화 | opik-optimizer (단독, 서버 불필요) | `opik-optimizer` |
| 이미지 | Pillow | `Pillow` |
| 언어 | Python 3.11+ | — |
| 테스트 | pytest + pytest-asyncio | — |
| 린팅 | ruff | — |
| 타입 | mypy (strict) | — |

---

## 실행 성숙도 3단계 — Cold / Warm / Hot

| 단계 | KB 상태 | LLM/VLM 호출 | 설명 |
|------|---------|-------------|------|
| **Cold** | 없음 | **최대** (3~10회) | 최초 실행. DOM 풀 트래버스, 스크린샷 다수, VLM 분석, LLM 종합/생성. 사이트당 1회 |
| **Warm** | 일부 | **최소** (0~2회) | KB 번들 존재, 실패 시만 LLM. DSL patch로 복구 |
| **Hot** | 완비 | **거의 0** | 100% 캐시 히트, 규칙 기반 실행. 최적화만 주기적 배치 |

전이 조건: `total_runs ≥ 3 + success_rate ≥ 0.70` → Warm, `success_rate ≥ 0.95 + 연속 10회 성공 + LLM 0회` → Hot

> 핵심: Cold에서 투자한 LLM 비용이 Warm→Hot으로 가면서 제로에 수렴.

---

## 아키텍처 4단계

```
사이트 방문 → Phase 1 정찰 → Phase 2 코드 생성 → Phase 3 실행 → Phase 4 자가 개선
```

### Phase 1: 정찰 (ReconAgent)

3단계 스캔으로 `SiteProfile` 생성:

1. **DOM 스캔** (~3s) — `page.evaluate()` + CDP `DOM.getDocument` + `Accessibility.getFullAXTree`
2. **시각 스캔** (~3s) — YOLO26(CPU)/RT-DETRv4(GPU) 로컬 추론 + Gemini 3 Flash VLM
3. **네비게이션 스캔** (~5페이지 크롤링) — Playwright 탐색

**화이트리스트 기반 콘텐츠 인식** — DOM 스캔 시 동일 부모 아래 태그 구조가 같은 형제 노드가 ≥3개 반복되고 텍스트+링크/이미지가 있으면 핵심 콘텐츠로 확정. 광고를 걸러내는 게 아니라, 진짜 콘텐츠를 취하는 접근. `RepeatingPattern`으로 SiteProfile에 저장.

출력: `sites/{domain}/profile.md` + `profile.json`

### Phase 2: 코드 생성 (CodeGenAgent)

SiteProfile → 전략 결정 → **DSL-first 생성**:

- 5가지 전략: `dom_only`, `dom_with_objdet_backup`, `objdet_dom_hybrid`, `grid_vlm`, `vlm_only`
- 생성 산출물: `GeneratedBundle` = workflow_dsl.json + (선택적) python_macro + (선택적) ts_macro + prompts
- 검증 게이트: DSL 스키마 검사 → 정적 분석 → Replay 세트 → Canary 사이트

출력: `sites/{domain}/url_patterns/{pattern}/workflows/`, `macros/`, `prompts/` (URL 패턴별 독립)

### Phase 3: 실행 (Runtime)

```
태스크 수신 → KB 조회 → 번들 히트 시 코드 실행 → 결과 검증
                      → 번들 미스 시 Phase 2로 생성
```

검증: URL 변화 + DOM assertion + 네트워크 응답 확인

### Phase 4: 자가 개선

**실패 분류** — `FailureAnalyzer` 4단계:
1. Playwright 에러 타입 매핑 (TimeoutError, StrictModeViolationError 등)
2. 검증 실패 코드 매핑 (EXPECT_SELECTOR_MISSING 등)
3. 하위 호환 문자열 규칙
4. LLM 분류 (위 3개 미분류 시만)

**자동 대응** — `SelfImprover`:
- `fix_selector`: DOM 재분석 → DSL patch
- `fix_obstacle`: 장애물 제거 매크로
- `change_strategy`: 전략 변경 (dom→objdet→vlm)
- `full_recon`: 사이트 재정찰 + 번들 재생성
- `add_wait`: 타임아웃 대응
- `human_handoff`: 인증 등 자동화 불가

**사이트 변경 감지** — `ChangeDetector` 3신호 합성:
- Selector 생존율 (가중치 0.5)
- AX Tree diff (가중치 0.3)
- API 스키마 diff (가중치 0.2)
- 임계값: ≥0.45 → 재정찰, ≥0.20 → 셀렉터 패치

**프롬프트 최적화** — opik-optimizer 단독형 (`pip install opik-optimizer`, 서버 불필요):
- 알고리즘 3종: `MetaPromptOptimizer` (기본), `EvolutionaryOptimizer` (다양성), `FewShotBayesianOptimizer` (토큰 절감)
- 자동 선택: 토큰 과다 → few-shot / 성공률 정체 → evolutionary / 기본 → meta-prompt
- 최소 데이터: 25회 실행 이력

**운영 모드**:
- **개발**: Opik 서버(Docker Compose) + `OPIK_ENABLED=true` → LiteLLM/LangGraph 트레이스 자동 수집, 대시보드로 디버깅
- **개인형 배포**: 서버 없이 opik-optimizer만 사용 → `OPIK_ENABLED=false`, 실행 이력은 KB `runs.jsonl`
- 코드 변경 없이 환경변수 하나로 전환

---

## Knowledge Base 구조

**도메인 → URL 패턴** 2계층 캐싱. 프로파일/코드/프롬프트 각각 독립 버전 관리.

```
sites/{domain}/
├── profile.md / profile.json       # SiteProfile (도메인 레벨)
├── profile_history/v{n}.json       # 프로파일 버전 이력
├── url_patterns/                   # ── URL 패턴별 산출물 ──
│   ├── search/                     # /search?query=* 패턴
│   │   ├── pattern.json            # URL 패턴 메타
│   │   ├── workflows/              # DSL 독립 버전 (v1, v2, ... current)
│   │   ├── macros/                 # 매크로 독립 버전
│   │   └── prompts/                # ★ 프롬프트 독립 버전 (Opik 최적화 대상)
│   │       ├── v1/
│   │       │   ├── extract.yaml    # 데이터 추출 프롬프트
│   │       │   ├── navigate.yaml
│   │       │   ├── verify.yaml
│   │       │   └── metadata.json   # {version, trigger, score}
│   │       └── current -> v2/
│   ├── catalog/                    # /catalog/* 패턴
│   └── category/                   # /category/* 패턴
├── screenshots/                    # 정찰 시 수집
└── history/
    └── runs.jsonl                  # 실행 이력 (URL패턴 + 코드버전 + 프롬프트버전 추적)
```

**프롬프트 3계층:**

| 계층 | 위치 | 버전 관리 | 최적화 |
|------|------|---------|--------|
| **Layer 1** 공통 기본 | `shared/base_prompts/*.yaml` | Git | Opik 글로벌 |
| **Layer 2** 사이트별 생성 | `url_patterns/{p}/prompts/v{n}/` | KB 독립 | Opik 사이트별 |
| **Layer 3** 코드 인라인 | `macros/v{n}/macro.py` 내 | 매크로 종속 | 매크로 재생성 |

> Layer 2 분리 원칙: 프롬프트는 코드에 하드코딩하지 않고 YAML로 분리. 코드 안건드리고 프롬프트만 최적화 가능.

---

## LiteLLM 모델 라우팅

API 키 하나로 벤더 자동 감지. `GEMINI_API_KEY` 또는 `OPENAI_API_KEY` 중 있는 쪽으로 전체 매핑.

| 키 | 용도 | Gemini (기본) | OpenAI |
|----|------|--------------|--------|
| `fast` | 정찰, 경량 작업 | `gemini-3-flash-preview` | `gpt-5-mini` |
| `strong` | 복잡 추론, 실패 분석 | `gemini-3.1-pro-preview` | `gpt-5.3-codex` |
| `codegen` | 코드/DSL 생성 | `gemini-3.1-pro-preview` | `gpt-5.3-codex` |
| `vision` | VLM 이미지 입력 | `gemini-3-flash-preview` | `gpt-5-mini` |

---

## 구현 순서

```
Phase 1 → SiteProfile 스키마 + 수집기 + 저장 파이프라인
Phase 2 → workflow_dsl 생성 + selector patch + 선택적 macro
Phase 3 → LangGraph 실행 루프 + URL/DOM/Network 검증
Phase 4 → 실패 분류 + DSL patch + 재시도/롤백
Phase 5 → Opik 배치 최적화 + Replay/Canary 승격 게이트
Phase 6 → 다중 사이트 운영 + 변경 감지 재정찰
```

---

## 핵심 원칙

1. **DSL-first**: 자유 코드 대신 검증 가능한 DSL 우선. 매크로는 DSL 불가 시만.
2. **토큰 제로 우선**: 룰/DSL로 처리 가능하면 LLM 호출 안 함.
3. **선택 문제 변환**: LLM에게 자유 행동이 아닌 후보 중 선택만 요청.
4. **Verify-After-Act**: 모든 핵심 액션 후 검증 필수.
5. **Patch-Only**: LLM 출력은 패치 데이터만 허용. 임의 코드 생성 금지.
6. **승격 게이트**: Replay 세트 + Canary 사이트 통과 전 운영 반영 불가.
7. **Multi-Turn 필수**: 챗/UI 기반 자동화 완성은 무조건 multi-turn. 의도 확인 → 전략 제안 → 중간 결과 → 최종 확인 단계를 거치며, 사용자 승인 없이 다음 단계로 넘어가지 않는다.
8. **프롬프트 분리**: LLM 프롬프트는 코드에 하드코딩하지 않고 YAML로 분리 저장. 코드 버전과 프롬프트 버전은 독립적으로 관리. 코드를 건드리지 않고 프롬프트만 Opik으로 최적화할 수 있어야 한다.
