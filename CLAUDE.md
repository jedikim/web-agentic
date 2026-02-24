# CLAUDE.md — 적응형 웹 자동화 엔진 프로젝트

## 프로젝트 개요

"반복 실행할수록 LLM 호출이 줄어드는" 적응형 웹 자동화 엔진.
룰 기반 결정론적 실행을 중심으로, 실패 시에만 LLM/VLM이 개입하여 복구하고, 성공 패턴을 규칙으로 승격시키는 자기 진화형 시스템.

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
- **규칙 엔진**: 자체 YAML DSL
- **DB**: SQLite (개발) → PostgreSQL (운영)
- **이미지 처리**: Pillow + OpenCV
- **비동기**: asyncio
- **테스트**: pytest + pytest-asyncio + playwright fixtures
- **린팅**: ruff
- **타입 체크**: mypy (strict)

## 프로젝트 구조

```
web-agentic-CLAUDE/
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
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # 오케스트레이터 (메인 루프)
│   │   ├── executor.py       # X — Playwright 래퍼
│   │   ├── extractor.py      # E — DOM→JSON 변환
│   │   ├── rule_engine.py    # R — 규칙 엔진
│   │   ├── verifier.py       # V — 검증기
│   │   └── fallback_router.py # F — 폴백 라우터
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── llm_planner.py    # L — LLM Planner (Flash/Pro)
│   │   ├── prompt_manager.py # 프롬프트 버전 관리
│   │   └── patch_system.py   # 패치 생성/적용
│   ├── vision/
│   │   ├── __init__.py
│   │   ├── yolo_detector.py  # YOLO 로컬 추론
│   │   ├── vlm_client.py     # VLM API 클라이언트
│   │   ├── image_batcher.py  # 이미지 배칭 시스템
│   │   └── coord_mapper.py   # 좌표 역추적
│   ├── learning/
│   │   ├── __init__.py
│   │   ├── pattern_db.py     # 패턴 DB
│   │   ├── rule_promoter.py  # 규칙 승격
│   │   ├── dspy_optimizer.py # DSPy 최적화
│   │   └── memory_manager.py # 4계층 메모리
│   └── workflow/
│       ├── __init__.py
│       ├── dsl_parser.py     # YAML DSL 파서
│       └── step_queue.py     # 스텝 큐 관리
├── config/
│   ├── rules/                # YAML 규칙 파일들
│   ├── synonyms.yaml         # 동의어 사전
│   └── settings.yaml         # 환경 설정
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── scripts/
    ├── setup.sh
    └── run_poc.py
```

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
- 6개 핵심 모듈 약어: X, E, R, L, V, F (코드 내 주석에서 사용)

### 아키텍처 원칙
1. **Patch-Only**: LLM 출력은 패치 데이터만 허용. 임의 코드 생성 금지
2. **토큰 제로 우선**: 룰로 처리 가능하면 LLM 호출하지 않음
3. **선택 문제 변환**: LLM/VLM에게 자유 행동이 아닌 후보 중 선택만 요청
4. **Verify-After-Act**: 모든 핵심 액션 후 검증 필수
5. **모듈 간 계약**: 각 모듈은 정의된 인터페이스(Protocol)로만 통신

### 에러 처리
- 커스텀 예외 클래스 사용 (`SelectorNotFoundError`, `NotInteractableError` 등)
- F(Fallback Router)에서 실패 코드 분류 후 복구 경로 결정
- 재시도 최대 3회, 그 후 에스컬레이션

### 테스트
- 단위 테스트: 각 모듈의 순수 로직 (pytest)
- 통합 테스트: 모듈 간 상호작용 (pytest-asyncio)
- E2E 테스트: 실제 브라우저 시나리오 (playwright fixtures)
- 목표: 단위 80%+, 통합 70%+

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

### 작업 지시 방법

각 Phase 별로 아래 형식으로 지시:

```
@planner Phase 1의 첫 번째 태스크를 분해해줘
@developer planner가 정의한 executor.py를 구현해줘
@reviewer developer가 작성한 executor.py를 리뷰해줘
@tester executor.py의 단위 테스트를 작성하고 실행해줘
```

## Phase별 개발 계획

### Phase 1: Deterministic Core (3~4주)
- X(Executor) Playwright 래퍼
- E(Extractor) 4종 구현
- R(Rule Engine) 기본 DSL + 규칙셋
- V(Verifier) 기본 검증 로직
- Orchestrator 기본 루프

### Phase 2: Adaptive Fallback (2~3주)
- F(Fallback Router) 실패 분류
- L(Planner) Flash/Pro 연동
- 4계층 메모리 매니저
- Patch 시스템

### Phase 3: Vision Integration (2~3주)
- YOLO 로컬 추론
- 이미지 배칭 + 좌표 역추적
- VLM Flash/Pro 에스컬레이션

### Phase 4: Self-Improving (2~3주)
- 패턴 DB + 규칙 승격
- DSPy MIPROv2 프롬프트 최적화
- GEPA 진화적 개선

### Phase 5: Exception Hardening (2~3주)
- 95+ 예외 감지 룰셋
- Human Handoff 인터페이스

### Phase 6: Integration & PoC (2주)
- 네이버 쇼핑 E2E 시나리오
- 성능/비용 벤치마크

## 주의사항

- **보안**: 로그인 정보는 vault/env로만 관리. 코드에 하드코딩 금지
- **PII**: LLM에 PII 전달 금지. 로그 저장 전 마스킹 필수
- **CAPTCHA**: 우회 자동화 금지. Human Handoff만 허용
- **robots.txt**: 대상 사이트 robots.txt 준수
- **비용**: 태스크당 $0.01 이하 목표. 예산 초과 시 자동 다운그레이드
