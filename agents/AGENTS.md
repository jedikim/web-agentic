# 멀티에이전트 워크플로우 정의

## 개요

이 프로젝트는 4가지 역할의 에이전트가 순차적으로 협업하여 개발합니다.
Claude Code에서 각 역할을 수행할 때 해당 에이전트의 `.md` 파일을 참조합니다.

## 에이전트 역할

| 역할 | 파일 | 핵심 책임 |
|------|------|----------|
| **Planner** | `planner.md` | 작업 분해, 우선순위, 의존성 분석, 구현 스펙 작성 |
| **Developer** | `developer.md` | 코드 작성, 인터페이스 구현, 타입 정의 |
| **Reviewer** | `reviewer.md` | 코드 리뷰, 아키텍처 준수 확인, 보안 검토 |
| **Tester** | `tester.md` | 테스트 작성, 실행, 커버리지 확인 |
| **Operator** | `operator.md` | 진화 파이프라인 관리, 세션 모니터링, 비용 추적 |

## 워크플로우

```
1. Planner: 태스크 분해 + 구현 스펙
     ↓
2. Developer: 코드 작성
     ↓
3. Reviewer: 코드 리뷰
     ↓ (수정 필요?)
     ├─ Yes → Developer (수정) → Reviewer (재리뷰)
     └─ No ↓
4. Tester: 테스트 작성 + 실행
     ↓ (실패?)
     ├─ Yes → Developer (버그 수정) → Tester (재실행)
     └─ No → 완료 ✅

* Operator: 전체 사이클 모니터링
     ├─ 진화 파이프라인 승인/거절 판단
     ├─ 활성 세션 비용/타임아웃 관리
     ├─ 버전 배포 후 성공률 검증
     └─ 롤백 필요 시 의사결정
```

## 사용법 (Claude Code)

### 방법 1: 역할별 개별 지시

```bash
# Planner로 작업 분해
claude "agents/planner.md 를 읽고, Phase 1의 executor.py 구현 계획을 세워줘"

# Developer로 구현
claude "agents/developer.md 를 읽고, planner가 작성한 스펙대로 src/core/executor.py를 구현해줘"

# Reviewer로 리뷰
claude "agents/reviewer.md 를 읽고, src/core/executor.py를 리뷰해줘"

# Tester로 테스트
claude "agents/tester.md 를 읽고, src/core/executor.py의 테스트를 작성하고 실행해줘"
```

### 방법 2: 전체 사이클 자동

```bash
claude "CLAUDE.md와 agents/AGENTS.md를 읽고, Phase 1의 executor.py를 planner→developer→reviewer→tester 순서로 완성해줘"
```

### 방법 3: 특정 Phase 전체 진행

```bash
claude "CLAUDE.md를 읽고 Phase 1: Deterministic Core를 전체 진행해줘. 각 모듈마다 plan→develop→review→test 사이클을 돌려"
```

## Phase별 태스크 목록

### Phase 1: Deterministic Core

| # | 모듈 | 파일 | 의존성 | 우선순위 |
|---|------|------|--------|---------|
| 1.1 | 타입 정의 | `src/core/types.py` | 없음 | P0 |
| 1.2 | X(Executor) | `src/core/executor.py` | types | P0 |
| 1.3 | E(Extractor) | `src/core/extractor.py` | types | P0 |
| 1.4 | R(Rule Engine) | `src/core/rule_engine.py` | types, synonyms | P0 |
| 1.5 | V(Verifier) | `src/core/verifier.py` | types | P0 |
| 1.6 | DSL Parser | `src/workflow/dsl_parser.py` | types | P1 |
| 1.7 | Orchestrator | `src/core/orchestrator.py` | 1.1~1.6 전부 | P1 |

### Phase 2: Adaptive Fallback

| # | 모듈 | 파일 | 의존성 |
|---|------|------|--------|
| 2.1 | F(Fallback Router) | `src/core/fallback_router.py` | types, verifier |
| 2.2 | L(LLM Planner) | `src/ai/llm_planner.py` | types, Gemini API |
| 2.3 | Patch System | `src/ai/patch_system.py` | types |
| 2.4 | Prompt Manager | `src/ai/prompt_manager.py` | types |
| 2.5 | Memory Manager | `src/learning/memory_manager.py` | types, SQLite |

### Phase 3: Vision Integration

| # | 모듈 | 파일 | 의존성 |
|---|------|------|--------|
| 3.1 | YOLO Detector | `src/vision/yolo_detector.py` | ultralytics |
| 3.2 | Image Batcher | `src/vision/image_batcher.py` | Pillow, OpenCV |
| 3.3 | Coord Mapper | `src/vision/coord_mapper.py` | types |
| 3.4 | VLM Client | `src/vision/vlm_client.py` | Gemini API |

### Phase 4: Self-Improving

| # | 모듈 | 파일 | 의존성 |
|---|------|------|--------|
| 4.1 | Pattern DB | `src/learning/pattern_db.py` | SQLite |
| 4.2 | Rule Promoter | `src/learning/rule_promoter.py` | pattern_db, rule_engine |
| 4.3 | DSPy Optimizer | `src/learning/dspy_optimizer.py` | dspy |
