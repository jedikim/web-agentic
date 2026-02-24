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
- **LLM**: Google Gemini API (`google-genai` SDK) — Flash: `gemini-3-flash-preview`, Pro: `gemini-3.1-pro-preview`
- **객체 탐지**: Ultralytics YOLO26 (`yolo26l.pt`, 로컬 GPU)
- **프롬프트 최적화**: Placeholder (DSPy MIPROv2 통합 예정, 현재 경량 휴리스틱)
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
│   ├── tester.md             # 테스트 에이전트 역할
│   └── operator.md           # 운영 에이전트 역할
├── src/
│   ├── web_agent.py          # SDK Facade (WebAgent)
│   ├── core/
│   │   ├── orchestrator.py   # 오케스트레이터 (메인 루프) — v3에서 LLM-First로 전환 필요
│   │   ├── executor.py       # X — Playwright 래퍼 (+ 스텔스/행동 위임)
│   │   ├── executor_pool.py  # 세션 풀 (브라우저 재사용, 스텔스 지원)
│   │   ├── extractor.py      # E — DOM→JSON 변환
│   │   ├── rule_engine.py    # R — v3에서 "캐시 저장소"로 역할 전환 필요
│   │   ├── verifier.py       # V — 검증기
│   │   ├── fallback_router.py # F — 실패 분류 + 에스컬레이션 체인 (오케스트레이터 연결됨)
│   │   ├── stealth.py        # 브라우저 스텔스 패치 (JS init scripts)
│   │   ├── human_behavior.py # 마우스/타이핑/스크롤 휴먼 시뮬레이션
│   │   ├── navigation.py     # 레이트리밋, robots.txt, 홈페이지 워밍
│   │   ├── config.py         # YAML → dataclass 설정 로더
│   │   ├── checkpoint.py     # 스크린샷 checkpoint 평가 (go/not_go/ask_user)
│   │   ├── resilience.py     # 병렬 시나리오 실행 + 복구 + 롤백
│   │   ├── adaptive_controller.py # 반복 의도 감지 + 캐시 스텝 실행
│   │   ├── executor_adapter.py    # IExecutor Protocol 재export + MockExecutor
│   │   ├── retry_policy.py   # 재시도 정책 (non-retryable 코드 분류)
│   │   ├── decision_port.py  # DecisionPort Protocol + Human Loop 드라이버
│   │   ├── selector_recovery.py   # 셀렉터 자동 복구 파이프라인 (+ fingerprint 매칭)
│   │   └── self_healing.py   # 6분류 실패 + 전용 힐링 전략
│   ├── ai/
│   │   ├── llm_planner.py    # L — LLM Planner (Flash/Pro) — ILLMProvider DI 지원
│   │   ├── llm_provider.py   # ILLMProvider Protocol + Gemini/OpenAI 구현
│   │   ├── model_registry.py # 모델 레지스트리 + resolve 로직
│   │   ├── context_reducer.py # LLM 컨텍스트 최적화 (후보 요소 축소)
│   │   ├── prompt_manager.py # 프롬프트 버전 관리
│   │   ├── patch_system.py   # 패치 생성/적용
│   │   └── cascaded_router.py # Flash-first 라우팅 + Pro 에스컬레이션
│   ├── vision/
│   │   ├── yolo_detector.py  # YOLO 로컬 추론
│   │   ├── vlm_client.py     # VLM API 클라이언트
│   │   ├── image_batcher.py  # 이미지 배칭 시스템
│   │   ├── repeated_item_judgement.py # YOLO→VLM 반복 아이템 판별 체인
│   │   └── coord_mapper.py   # 좌표 역추적
│   ├── learning/
│   │   ├── pattern_db.py     # 패턴 DB — v3에서 "셀렉터 캐시"로 용도 전환
│   │   ├── rule_promoter.py  # v3에서 "캐시 저장 로직"으로 전환 + Canary Gate 연결
│   │   ├── canary_gate.py    # 회귀 체크 기반 규칙 승격 게이트
│   │   ├── replay_store.py   # 실행 이력 aiosqlite 저장소 (+ 키워드 퍼지 매칭)
│   │   ├── element_fingerprint.py # Similo 다속성 fingerprint 매칭
│   │   ├── plan_cache.py     # 키워드 추출 + 퍼지 매칭 + 플랜 적응
│   │   ├── recipe_version.py # 셀렉터 레시피 버전 관리 + 패치 적용
│   │   ├── dspy_optimizer.py # 프롬프트 최적화 placeholder (DSPy 미연동)
│   │   └── memory_manager.py # 4계층 메모리
│   ├── workflow/
│   │   ├── dsl_parser.py     # YAML DSL 파서
│   │   └── step_queue.py     # 스텝 큐 관리
│   ├── ops/
│   │   └── metrics_dashboard.py  # 런타임 메트릭 집계 (비용/지연/실패율)
│   └── api/
│       ├── session_db.py     # 세션 데이터베이스 (aiosqlite)
│       ├── session_manager.py # 세션 매니저 (라이브 세션 관리)
│       ├── chat_automation.py # Chat 자동화 서비스 (pause/resume/cancel/captcha)
│       └── routes/
│           ├── sessions.py   # 세션 API 라우트 + Chat 엔드포인트
│           └── run.py        # 원샷 실행 API 라우트
├── config/
│   ├── rules/                # YAML 규칙 — v3에서 "초기 캐시 시드"로 용도 전환
│   ├── synonyms.yaml         # 동의어 사전
│   └── settings.yaml         # 환경 설정
├── tests/
│   ├── unit/                 # 816 단위+통합 테스트
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
| Executor | X | 브라우저 래퍼 | 브라우저 래퍼 + 스텔스/행동/네비게이션 위임 |
| Extractor | E | DOM 추출 | DOM 추출 → LLM에 후보 제공 |
| Rule Engine | R | 1순위 매칭 | **캐시 저장소: 성공 셀렉터 조회/저장** |
| Verifier | V | 사후 검증 | 사후 검증 (변경 없음) |
| Fallback Router | F | 실패 분류 | **오케스트레이터 연결: 적응형 재시도 + 에스컬레이션** |
| Vision (YOLO/VLM) | G | 미연결 플레이스홀더 | **LLM 신뢰도 < 0.7일 때 시각적 그라운딩** |
| PatternDB | - | 패턴 저장 | **셀렉터 캐시 (TTL 기반 유효성 관리)** |
| WebAgent SDK | - | - | **High-level SDK facade** |
| SessionManager | - | - | **Multi-turn session lifecycle** |
| SessionDB | - | - | **Session persistence (aiosqlite)** |
| Stealth | - | - | **브라우저 봇 탐지 회피 (JS 패치)** |
| HumanBehavior | - | - | **베지어 마우스, 자연 타이핑, 스크롤** |
| NavigationGuard | - | - | **레이트리밋, robots.txt, 홈페이지 워밍** |
| EngineConfig | - | - | **통합 설정 로더 (YAML → dataclass)** |
| Checkpoint | - | - | **스크린샷 기반 go/not_go/ask_user 판정** |
| Canary Gate | - | - | **회귀 체크 기반 규칙 승격 게이트** |
| Resilience Orch | - | - | **병렬 시나리오 실행 + 복구 + 롤백** |
| Adaptive Controller | - | - | **반복 의도 감지 + 캐시 스텝 실행** |
| Replay Store | - | - | **실행 이력 aiosqlite 저장소** |
| LLM Provider | - | - | **ILLMProvider Protocol (Gemini/OpenAI)** |
| Model Registry | - | - | **모델 레지스트리 + 해석 로직** |
| Patch Validator | - | - | **패치 구조/구문 검증 (진화 안전장치)** |
| Repeated Item Judge | - | - | **YOLO→VLM 반복 아이템 판별 체인** |
| Chat Automation | - | - | **실시간 자동화 (pause/resume/cancel/captcha)** |
| Executor Adapter | - | - | **IExecutor Protocol + MockExecutor 팩토리** |
| Retry Policy | - | - | **재시도 정책 (non-retryable 코드 분류)** |
| Decision Port | - | - | **DecisionPort Protocol + Human Loop 드라이버** |
| Selector Recovery | - | - | **셀렉터 자동 복구 파이프라인** |
| Context Reducer | - | - | **LLM 컨텍스트 최적화 (후보 축소)** |
| Model Policy | - | - | **진화 모델 티어 정책 (코딩=Pro, 자동화=Flash)** |
| Recipe Version | - | - | **셀렉터 레시피 버전 관리 + 패치 적용** |
| Scenario Growth | - | - | **시나리오 팩 빌더 (baseline + exception matrix)** |
| Auto Improvement | - | - | **자동 진화 트리거 (실패 → 진화 사이클)** |
| Metrics Dashboard | - | - | **런타임 메트릭 집계 (비용/지연/실패율)** |
| Element Fingerprint | - | - | **Similo 다속성 fingerprint 매칭 (LLM-free 셀렉터 복구)** |
| Plan Cache | - | - | **키워드 기반 퍼지 매칭 + 플랜 적응 (반복 비용 절감)** |
| Cascaded Router | - | - | **Flash-first 라우팅 + 성공률 추적 (비용 30-50% 절감)** |
| Self-Healing | - | - | **6분류 실패 + 전용 힐링 전략 (timing/hidden/stale/nav/data)** |

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

## 프로덕션 강화 (Production Hardening)

### 스텔스 레이어 (`src/core/stealth.py`)
- 3단계 레벨: minimal | standard | aggressive
- `navigator.webdriver` 제거, `chrome.runtime` 위장, plugins/mimeTypes 주입
- aggressive: WebGL vendor/renderer 위장 + Canvas 노이즈
- User-Agent 자동 로테이션 (Win/Mac/Linux Chrome 124)
- `create_executor(stealth=StealthConfig(level="standard"))` 으로 사용

### 휴먼 행동 시뮬레이션 (`src/core/human_behavior.py`)
- 3차 베지어 커브 마우스 이동 (20포인트, 랜덤 제어점 2개)
- 문자별 타이핑 딜레이 (50-150ms)
- 점진적 스크롤 (step_px 단위)
- 지터 대기 (base_ms ± 30%)
- 딥 URL 방문 시 홈페이지 먼저 방문

### 적응형 재시도 + 재계획 (`src/core/llm_orchestrator.py`)
- FallbackRouter가 오케스트레이터에 연결됨
- 지수 백오프 (500ms → 1s → 2s → ... max 10s) + 지터
- 에스컬레이션 체인: retry → LLM(Flash) → LLM(Pro) → Vision → Human Handoff
- 연속 실패 3회 시 서킷 브레이커 발동
- 실패 시 남은 스텝 재계획 (LLM에게 현재 페이지 상태로 재계획 요청)

### 네비게이션 인텔리전스 (`src/core/navigation.py`)
- robots.txt 준수 (stdlib `urllib.robotparser`)
- 도메인별 레이트리밋 (기본 2000ms)
- 딥 URL 방문 시 루트 도메인 먼저 방문 (봇 패턴 방지)
- `NavigationBlockedError` + `BotDetectedError` 신규 에러 타입

### 통합 설정 (`src/core/config.py` + `config/settings.yaml`)
- `EngineConfig` 통합: StealthConfig, BehaviorConfig, NavigationConfig, RetryConfig
- `load_config("config/settings.yaml")` 으로 YAML 로딩
- 프로그래밍적 오버라이드 지원

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
- 현재: 1260 passed (1084 unit + 95 integration + 57 E2E + 24 skipped)

### 검증 필수 사항 (반드시 준수)

코드 변경 후 커밋 전, **아래 검증을 모두 직접 실행**해야 한다. 테스트 통과만으로는 부족하다.

```bash
# 1. 단위 + 통합 테스트
python -m pytest tests/unit/ tests/integration/ -x -q

# 2. E2E 브라우저 테스트
python -m pytest tests/e2e/ -x -q -m "not live"

# 3. 서버 실제 기동 확인 (uvicorn 프로세스가 정상 시작되는지 반드시 검증)
source .venv/bin/activate
timeout 10 python scripts/start_server.py  # "Application startup complete" 확인

# 4. API 헬스체크 (서버 기동 상태에서)
curl -s http://localhost:8000/health  # {"status":"ok"} 확인

# 5. ruff + mypy
ruff check src/ tests/ --fix
mypy src/ --strict
```

**왜 서버 기동 테스트가 필수인가:**
- pytest는 프로젝트 루트에서 `src/`를 직접 import하므로 패키지 설정 오류를 발견하지 못한다
- uvicorn은 별도 프로세스를 spawn하므로 `pyproject.toml`, 의존성, import 경로 문제가 여기서 발견된다
- 서버 lifespan (DB 초기화, ExecutorPool 생성 등)의 실제 동작은 테스트로 커버되지 않는다

## 멀티에이전트 워크플로우

이 프로젝트는 5가지 역할의 에이전트가 협업합니다:

1. **Planner** (`agents/planner.md`): 작업 분해, 우선순위, 의존성 분석
2. **Developer** (`agents/developer.md`): 실제 코드 작성
3. **Reviewer** (`agents/reviewer.md`): 코드 리뷰, 아키텍처 준수 확인
4. **Tester** (`agents/tester.md`): 테스트 작성 및 실행
5. **Operator** (`agents/operator.md`): 진화 파이프라인 관리, 세션 모니터링, 비용 추적

### 작업 진행 순서

```
Planner → Developer → Reviewer → (수정 필요 시 Developer) → Tester → (실패 시 Developer) → 완료
                                                                                              ↓
Operator: 전체 사이클 모니터링 + 진화 승인/거절 + 세션 비용 관리 + 버전 배포 조율
```

## 자가 진화 시스템 (Self-Evolving Engine)

### 아키텍처

```
실패 감지 → 분석(Pro) → 코드 생성(Pro) → Git 브랜치 → 테스트 → 승인 대기 → 머지+태그
    ↑                                                                          |
    └──────────────── 새 시나리오 실행 결과 피드백 ─────────────────────────────┘
```

### 모듈 구조

| 모듈 | 경로 | 역할 |
|------|------|------|
| Evolution DB | `src/evolution/db.py` | 진화 사이클/변경/버전/시나리오/실패패턴 저장 (aiosqlite) |
| Analyzer | `src/evolution/analyzer.py` | 실패 패턴 감지 및 분류 |
| Code Generator | `src/evolution/code_generator.py` | Gemini 2.5 Pro로 코드 수정 생성 |
| Sandbox | `src/evolution/sandbox.py` | Git 브랜치 기반 격리 테스트 |
| Pipeline | `src/evolution/pipeline.py` | 전체 진화 사이클 상태 머신 |
| Version Manager | `src/evolution/version_manager.py` | 버전 태깅, 머지, 롤백 |
| Notifier | `src/evolution/notifier.py` | SSE 이벤트 브로드캐스터 |
| Patch Validator | `src/evolution/patch_validator.py` | 패치 구조/구문 검증 (진화 안전장치) |
| Model Policy | `src/evolution/model_policy.py` | 코딩/자동화 모델 티어 정책 |
| Scenario Growth | `src/evolution/scenario_growth.py` | 시나리오 팩 빌더 (baseline + exception) |
| Auto Improvement | `src/evolution/auto_improvement.py` | 자동 진화 트리거 오케스트레이터 |

### API 서버

FastAPI 기반 (`src/api/`), 포트 8000:
- `POST /api/evolution/trigger` — 진화 사이클 시작
- `GET /api/evolution/` — 진화 목록
- `POST /api/evolution/{id}/approve` — 승인 → 머지
- `POST /api/evolution/{id}/reject` — 거절
- `POST /api/scenarios/run` — 시나리오 실행
- `GET /api/scenarios/results` — 결과 이력
- `GET /api/scenarios/trends` — 트렌드
- `GET /api/versions/` — 버전 목록
- `GET /api/progress/stream` — SSE 실시간 이벤트
- `POST /api/sessions/` — 세션 생성
- `POST /api/sessions/{id}/turn` — 턴 실행
- `GET /api/sessions/{id}/screenshot` — 스크린샷 조회
- `GET /api/sessions/{id}/handoffs` — Handoff 목록
- `POST /api/sessions/{id}/handoffs/{rid}/resolve` — Handoff 해결
- `DELETE /api/sessions/{id}` — 세션 종료
- `POST /api/sessions/{id}/chat/start` — Chat 자동화 시작
- `POST /api/sessions/{id}/chat/{rid}/pause` — 일시정지
- `POST /api/sessions/{id}/chat/{rid}/resume` — 재개
- `POST /api/sessions/{id}/chat/{rid}/cancel` — 취소
- `POST /api/sessions/{id}/chat/{rid}/captcha` — CAPTCHA 솔루션 제출
- `GET /api/sessions/{id}/chat/{rid}/status` — Chat 상태 조회
- `POST /api/run` — 원샷 실행

### UI

`evolution-ui/` — React 19 + Vite + Tailwind CSS. 6개 페이지:
1. **Dashboard** — 현재 버전, 활성 진화, 시나리오 결과, 실시간 이벤트
2. **Evolutions** — 진화 상세 (diff, 테스트 결과, 승인/거절)
3. **Scenarios** — 시나리오 실행/결과/트렌드
4. **Versions** — 버전 타임라인, 롤백
5. **Automation** — 원샷 태스크 실행, 실시간 스텝 진행 및 비용 표시
6. **Sessions** — 멀티턴 세션 관리, 실시간 스크린샷 및 Handoff 처리

### 진화 상태 머신

```
PENDING → ANALYZING → GENERATING → TESTING → AWAITING_APPROVAL
                                                     ↓
                                              APPROVED → MERGED
                                              REJECTED (브랜치 삭제)
                                              FAILED (에러)
```

테스트 실패 시 1회 자동 재시도 (재분석 → 재생성).

### 실행

```bash
pip install -e ".[server]"
python scripts/start_server.py        # API 서버 (localhost:8000)
cd evolution-ui && npm run dev         # UI (localhost:5173)
```

## 주의사항

- **보안**: 로그인 정보는 vault/env로만 관리. 코드에 하드코딩 금지
- **PII**: LLM에 PII 전달 금지. 로그 저장 전 마스킹 필수
- **CAPTCHA**: 우회 자동화 금지. Human Handoff만 허용
- **robots.txt**: 대상 사이트 robots.txt 준수
- **비용**: 태스크당 $0.02 이하 목표 (새 사이트), $0.005 이하 (반복)
