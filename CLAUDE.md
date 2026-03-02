# CLAUDE.md — v4.3 정찰 → 코드 생성 → 자가 개선 웹 자동화 엔진

> 상세 설계: `docs/RECON_CODEGEN_ARCHITECTURE.md`
> 개발 가이드: `docs/DEV_GUIDE.md`

## 핵심 아이디어

사이트를 **먼저 정찰**하여 SiteProfile 생성 → 자동화 코드(DSL/매크로/프롬프트) 생성 → 실행 → 자가 개선.
반복할수록 LLM 호출이 **0에 수렴** (Cold → Warm → Hot 3단계 성숙도).

## 아키텍처 4단계

```
Phase 1: 정찰 (ReconAgent) → SiteProfile (DOM + 시각 + 네비게이션 스캔)
Phase 2: 코드 생성 (CodeGenAgent) → GeneratedBundle (DSL + macro + prompts)
Phase 3: 실행 (Runtime) → KB 조회 → 번들 실행 → 결과 검증
Phase 4: 자가 개선 → 실패 분류 + DSL 패치 + 프롬프트 최적화
```

## 기술 스택

| 용도 | 도구 |
|------|------|
| 워크플로우 | LangGraph |
| LLM 라우팅 | LiteLLM Router |
| 브라우저 | Playwright (async) |
| DOM 추출 | CDP (DOMSnapshot + AXTree) |
| 객체 탐지 | YOLO26 (CPU) / RT-DETRv4 (GPU) |
| LLM/VLM | Gemini 3 Flash / 3.1 Pro 또는 GPT-5 mini / 5.3 Codex |
| 프롬프트 최적화 | opik-optimizer (단독, 서버 불필요) |
| 언어 | Python 3.11+ |
| 테스트 | pytest + pytest-asyncio |
| 린팅 | ruff, mypy --strict |

## 프로젝트 구조 (v4)

```
src/
├── recon/                    # Phase 1: 사이트 정찰
│   ├── agent.py              # ReconAgent (LangGraph 상태머신)
│   ├── dom_scanner.py        # DOM 정찰 (CDP snapshot + evaluate)
│   ├── visual_scanner.py     # 시각 정찰 (YOLO/RT-DETR + VLM)
│   ├── nav_scanner.py        # 네비게이션 정찰 (메뉴/검색/카테고리)
│   └── profile_synthesizer.py # 정찰 결과 → SiteProfile 종합
├── codegen/                  # Phase 2: 코드 생성
│   ├── agent.py              # CodeGenAgent (LangGraph)
│   ├── strategy_decider.py   # 5전략 결정 (dom_only ~ vlm_only)
│   ├── dsl_generator.py      # DSL 워크플로우 생성
│   ├── macro_generator.py    # Python/TS 매크로 생성
│   ├── prompt_generator.py   # 태스크별 프롬프트 생성
│   └── validator.py          # 5단계 검증 게이트
├── runtime/                  # Phase 3: 실행
│   ├── executor.py           # 번들 실행기 (DSL + macro)
│   ├── verifier.py           # 결과 검증 (URL/DOM/Network)
│   └── workflow.py           # LangGraph 메인 워크플로우
├── improve/                  # Phase 4: 자가 개선
│   ├── failure_analyzer.py   # 실패 4단계 분류
│   ├── self_improver.py      # 자동 대응 (fix_selector, change_strategy 등)
│   ├── change_detector.py    # 사이트 변경 감지 (3신호 합성)
│   └── prompt_optimizer.py   # opik-optimizer 배치 최적화
├── kb/                       # Knowledge Base
│   ├── manager.py            # KB 읽기/쓰기/버전 관리
│   ├── cache_key.py          # CacheKey (domain + url_pattern + artifact)
│   └── maturity.py           # Cold/Warm/Hot 성숙도 판정
├── models/                   # 공유 타입
│   ├── site_profile.py       # SiteProfile + 하위 dataclass
│   ├── bundle.py             # GeneratedBundle + DSL 스키마
│   ├── failure.py            # FailureEvidence + FailureType
│   └── maturity.py           # MaturityState
├── llm/                      # LLM 라우팅
│   ├── router.py             # LiteLLM Router 래퍼
│   ├── routing_policy.py     # 태스크별 모델 매핑
│   └── cost_monitor.py       # 예산 관리
└── core/                     # 기존 v3 (유지, Phase 3에서 재활용)
    └── ...
```

## Knowledge Base 구조

```
sites/{domain}/
├── profile.md / profile.json     # SiteProfile
├── profile_history/v{n}.json     # 버전 이력
├── url_patterns/
│   ├── search/                   # URL 패턴별 산출물
│   │   ├── pattern.json
│   │   ├── workflows/v{n}.dsl.json
│   │   ├── macros/v{n}/macro.py
│   │   └── prompts/v{n}/*.yaml
│   └── catalog/
├── screenshots/
└── history/runs.jsonl
```

## 구현 순서

1. **Phase 1**: SiteProfile 스키마 + DOM/시각/네비 수집기 + KB 저장
2. **Phase 2**: DSL 생성 + 전략 결정 + 검증 게이트
3. **Phase 3**: LangGraph 실행 루프 + 검증
4. **Phase 4**: 실패 분류 + DSL 패치 + 프롬프트 최적화

## 핵심 원칙

1. **DSL-first**: 자유 코드 대신 검증 가능한 DSL 우선
2. **토큰 제로 우선**: 캐시/규칙으로 처리 가능하면 LLM 호출 안 함
3. **선택 문제 변환**: LLM에게 자유 행동이 아닌 후보 중 선택만 요청
4. **Verify-After-Act**: 모든 핵심 액션 후 검증 필수
5. **승격 게이트**: Replay + Canary 통과 전 운영 반영 불가
6. **프롬프트 분리**: YAML로 분리, 코드와 독립 버전 관리

## 코딩 컨벤션

- Python 3.11+, async/await 기본
- ruff 린팅, mypy --strict
- Google 스타일 docstring
- dataclass / Pydantic BaseModel
- 테스트: pytest + pytest-asyncio

## 검증

```bash
python -m pytest tests/unit/ tests/integration/ -x -q
ruff check src/ tests/ --fix
mypy src/ --strict
```
