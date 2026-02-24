# CLAUDE.md — 적응형 웹 자동화 엔진 프로젝트

## 프로젝트 개요

**LLM이 명령의 주체**인 적응형 웹 자동화 엔진.
LLM이 사용자 의도를 분석하고, 실행 계획을 수립하며, 요소를 선택한다.
성공한 셀렉터는 캐시되어 반복 실행 시 비용이 줄어든다 (LLM-First with Smart Caching).

## 아키텍처 원칙 (v3 — LLM-First)

### 에스컬레이션 플로우

```
사용자 의도 입력
    ↓
[L0] LLM 의미 분석 — 의도를 atomic 스텝으로 분해
    ↓
[L1] 캐시 조회 — {사이트, 의도} → 저장된 셀렉터가 있으면 사용
    ↓
[L2] LLM 요소 선택 — DOM 후보 추출 후 LLM이 최적 요소 선택
    ↓
[L3] 실행 — Playwright로 액션 수행
    ↓
[L4] 검증 — 상태 변화 확인, 성공 시 셀렉터 캐시 저장
    ↓
[L5] Vision — LLM 신뢰도 < 0.7이면 YOLO/VLM으로 시각적 그라운딩
    ↓
[L6] Human Handoff — CAPTCHA, 인증 등 자동화 불가능한 경우
```

### 5대 원칙

1. **LLM-First**: LLM이 의도 분석, 계획 수립, 요소 선택의 주체. 규칙은 캐시 역할
2. **Smart Caching**: 성공한 LLM 결과를 캐시하여 반복 비용 절감 (규칙 "승격"이 아닌 "캐싱")
3. **선택 문제 변환**: LLM에게 자유 행동이 아닌 DOM 후보 중 선택 요청 (비용 절감)
4. **Verify-After-Act**: 모든 핵심 액션 후 검증 필수. 실패 시 LLM이 재판단
5. **Cross-Site 일반화**: LLM은 사이트 간 지식을 전이. 사이트별 규칙 학습이 아님

### 기존 원칙에서 변경된 것

| 기존 (v1-v2) | 변경 (v3) | 이유 |
|---|---|---|
| 토큰 제로 우선 (룰 먼저) | **LLM 우선 (캐시 보조)** | 새 사이트에서 룰 없으면 무조건 실패 |
| R → E+R → F → L | **L → Cache → L+E → X → V** | LLM이 주체, 캐시가 보조 |
| 사이트별 규칙 학습 | **LLM 크로스사이트 일반화** | 10개 사이트 × 규칙 = 확장 불가 |
| Patch-Only 출력 | **유지** | LLM 출력은 구조화된 데이터만 |
| 모듈 간 Protocol 통신 | **유지** | DI 기반 테스트 가능성 |

## 핵심 문서

- `docs/PRD.md` — 제품 요구사항 정의서 (기술 기획서 기반 요약)
- `docs/ARCHITECTURE.md` — 모듈별 상세 아키텍처
- `docs/web-automation-technical-spec-v2.md` — 전체 기술 기획서 (2,268줄, 가장 상세)
- `agents/` — 멀티에이전트 역할 정의

## 기술 스택

- **언어**: Python 3.11+
- **브라우저 자동화**: Playwright (async)
- **LLM**: Google Gemini API (Flash / Pro)
- **객체 탐지**: Ultralytics YOLO11/26 (로컬 GPU)
- **프롬프트 최적화**: DSPy (MIPROv2, GEPA)
- **셀렉터 캐시**: SQLite (PatternDB) — 기존 규칙 엔진을 캐시로 전환
- **DB**: SQLite (개발) → PostgreSQL (운영)
- **이미지 처리**: Pillow + OpenCV
- **비동기**: asyncio
- **테스트**: pytest + pytest-asyncio + playwright fixtures
- **린팅**: ruff
- **타입 체크**: mypy (strict)

## 프로젝트 구조

```
web-agentic/
├── CLAUDE.md                 # 이 파일 (Claude Code 지시서)
├── docs/
│   ├── PRD.md                # 제품 요구사항 정의서
│   ├── ARCHITECTURE.md       # 모듈별 아키텍처
│   └── web-automation-technical-spec-v2.md  # 전체 기술 기획서
├── agents/
│   ├── AGENTS.md             # 멀티에이전트 워크플로우 정의
│   ├── planner.md            # 계획 에이전트 역할
│   ├── developer.md          # 개발 에이전트 역할
│   ├── reviewer.md           # 코드 리뷰 에이전트 역할
│   └── tester.md             # 테스트 에이전트 역할
├── src/
│   ├── core/
│   │   ├── orchestrator.py   # 오케스트레이터 (메인 루프) — v3에서 LLM-First로 전환 필요
│   │   ├── executor.py       # X — Playwright 래퍼
│   │   ├── executor_pool.py  # 세션 풀 (브라우저 재사용)
│   │   ├── extractor.py      # E — DOM→JSON 변환
│   │   ├── rule_engine.py    # R — v3에서 "캐시 저장소"로 역할 전환 필요
│   │   ├── verifier.py       # V — 검증기
│   │   └── fallback_router.py # F — v3에서 VisionRouter로 전환 필요
│   ├── ai/
│   │   ├── llm_planner.py    # L — LLM Planner (Flash/Pro) — v3의 핵심 모듈
│   │   ├── prompt_manager.py # 프롬프트 버전 관리
│   │   └── patch_system.py   # 패치 생성/적용
│   ├── vision/
│   │   ├── yolo_detector.py  # YOLO 로컬 추론
│   │   ├── vlm_client.py     # VLM API 클라이언트
│   │   ├── image_batcher.py  # 이미지 배칭 시스템
│   │   └── coord_mapper.py   # 좌표 역추적
│   ├── learning/
│   │   ├── pattern_db.py     # 패턴 DB — v3에서 "셀렉터 캐시"로 용도 전환
│   │   ├── rule_promoter.py  # v3에서 "캐시 저장 로직"으로 전환
│   │   ├── dspy_optimizer.py # DSPy 최적화
│   │   └── memory_manager.py # 4계층 메모리
│   └── workflow/
│       ├── dsl_parser.py     # YAML DSL 파서
│       └── step_queue.py     # 스텝 큐 관리
├── config/
│   ├── rules/                # YAML 규칙 — v3에서 "초기 캐시 시드"로 용도 전환
│   ├── synonyms.yaml         # 동의어 사전
│   └── settings.yaml         # 환경 설정
├── tests/
│   ├── unit/                 # 706 단위+통합 테스트
│   ├── integration/
│   └── e2e/                  # 36 E2E 브라우저 테스트
└── scripts/
    ├── run_poc.py            # PoC 러너
    └── capture_dom.py        # DOM 캡처 도구
```

## 모듈 역할 (v3 기준)

| 모듈 | 약어 | v1-v2 역할 | **v3 역할** |
|---|---|---|---|
| LLM Planner | L | 폴백 (레벨3) | **주체: 의도 분석 + 계획 + 요소 선택** |
| Executor | X | 브라우저 래퍼 | 브라우저 래퍼 (변경 없음) |
| Extractor | E | DOM 추출 | DOM 추출 → LLM에 후보 제공 |
| Rule Engine | R | 1순위 매칭 | **캐시 저장소: 성공 셀렉터 조회/저장** |
| Verifier | V | 사후 검증 | 사후 검증 (변경 없음) |
| Fallback Router | F | 실패 분류 | **VisionRouter: LLM 신뢰도 기반 Vision 라우팅** |
| Vision (YOLO/VLM) | G | 미연결 플레이스홀더 | **LLM 신뢰도 < 0.7일 때 시각적 그라운딩** |
| PatternDB | - | 패턴 저장 | **셀렉터 캐시 (TTL 기반 유효성 관리)** |

## v3 전환 시 필요한 작업

### Phase 7: LLM-First 오케스트레이션 전환
1. **Orchestrator 재설계**: execute_step() 플로우를 L→Cache→L+E→X→V로 전환
2. **TaskPlanner 신규 모듈**: 사용자 의도 → atomic 스텝 분해 (LLM 기반)
3. **RuleEngine → SelectorCache**: match() 대신 cache_lookup()/cache_save()
4. **FallbackRouter → VisionRouter**: 실패 기반이 아닌 신뢰도 기반 라우팅
5. **PatternDB TTL 추가**: 캐시된 셀렉터의 유효 기간 관리 (사이트 변경 대응)

### 비용 모델 (v3 목표)
- 의도 분해: ~$0.01/태스크 (한 번만, 캐시 가능)
- 요소 선택: ~$0.002/스텝 (DOM 후보에서 선택)
- 캐시 히트: $0/스텝 (반복 실행)
- Vision 폴백: ~$0.005/쿼리 (드물게)
- **태스크당 총 목표: $0.02 이하** (새 사이트), **$0.005 이하** (반복)

## 코딩 컨벤션

### Python 스타일
- ruff로 린팅 (`ruff check --fix`)
- mypy strict 모드 (`mypy --strict`)
- 모든 함수에 type hints 필수
- docstring은 Google 스타일
- 클래스는 dataclass 또는 Pydantic BaseModel 선호
- async/await 패턴 기본

### 네이밍
- 모듈명: snake_case (`rule_engine.py`)
- 클래스명: PascalCase (`RuleEngine`)
- 상수: UPPER_SNAKE (`MAX_RETRIES = 3`)
- 핵심 모듈 약어: L, X, E, R(Cache), V, G(Vision)

### 에러 처리
- 커스텀 예외 클래스 사용 (`SelectorNotFoundError`, `NotInteractableError` 등)
- LLM 신뢰도 < 0.7이면 Vision으로 에스컬레이션
- 재시도 최대 3회, 그 후 Human Handoff

### 테스트
- 단위 테스트: 각 모듈의 순수 로직 (pytest)
- 통합 테스트: 모듈 간 상호작용 (pytest-asyncio)
- E2E 테스트: 실제 브라우저 시나리오 (playwright fixtures)
- 현재: 742 passed (706 unit/integration + 36 E2E)

## 멀티에이전트 워크플로우

이 프로젝트는 4가지 역할의 에이전트가 협업합니다:

1. **Planner** (`agents/planner.md`): 작업 분해, 우선순위, 의존성 분석
2. **Developer** (`agents/developer.md`): 실제 코드 작성
3. **Reviewer** (`agents/reviewer.md`): 코드 리뷰, 아키텍처 준수 확인
4. **Tester** (`agents/tester.md`): 테스트 작성 및 실행

### 작업 진행 순서

```
Planner → Developer → Reviewer → (수정 필요 시 Developer) → Tester → (실패 시 Developer) → 완료
```

## 주의사항

- **보안**: 로그인 정보는 vault/env로만 관리. 코드에 하드코딩 금지
- **PII**: LLM에 PII 전달 금지. 로그 저장 전 마스킹 필수
- **CAPTCHA**: 우회 자동화 금지. Human Handoff만 허용
- **robots.txt**: 대상 사이트 robots.txt 준수
- **비용**: 태스크당 $0.02 이하 목표 (새 사이트), $0.005 이하 (반복)
