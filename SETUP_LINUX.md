# 리눅스 머신 전체 셋업 가이드

> web-agentic-CLAUDE 프로젝트를 새 리눅스 머신에서 Claude Code 멀티에이전트로 개발하기 위한 완전한 설치 가이드

---

## 1단계: 시스템 기본 패키지

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y \
  python3.11 python3.11-venv python3.11-dev \
  git curl wget build-essential \
  libgl1-mesa-glx libglib2.0-0 \
  sqlite3 libsqlite3-dev \
  nodejs npm

# Python 3.11이 기본이 아닌 경우
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

### GPU 사용 시 (YOLO 로컬 추론용, 선택사항)

```bash
# NVIDIA CUDA (Ubuntu)
sudo apt install -y nvidia-driver-535 nvidia-cuda-toolkit

# 확인
nvidia-smi
```

---

## 2단계: Claude Code 설치

```bash
# 네이티브 설치 (권장, Node.js 불필요)
curl -fsSL https://claude.ai/install.sh | bash

# 설치 확인
claude --version

# 시스템 진단
claude doctor
```

### 인증

```bash
# 첫 실행 시 브라우저 인증 또는 API 키 설정
claude

# 또는 API 키 직접 설정
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## 3단계: Claude Code 플러그인 설치

Claude Code를 실행한 상태에서 (`claude` 명령 후) 아래 명령어들을 입력합니다.

### 3-1. Superpowers (핵심 — 멀티에이전트 계획/실행)

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

설치 후 사용 가능한 명령어:

| 명령어 | 용도 |
|--------|------|
| `/superpowers:brainstorm` | 복잡한 기능 구현 전 요구사항을 소크라틱 방식으로 정리 |
| `/superpowers:write-plan` | 멀티파일 리팩터링/마이그레이션 상세 계획 수립 |
| `/superpowers:execute-plan` | 병렬 서브에이전트로 계획을 배치 실행 |

### 3-2. Python 백엔드 플러그인 (FastAPI, SQLAlchemy, async 패턴)

```
/plugin marketplace add ruslan-korneev/python-backend-claude-plugins
/plugin install python-backend@python-backend-claude-plugins
```

### 3-3. Playwright Skill (브라우저 자동화 전문)

```
/plugin marketplace add lackeyjb/playwright-skill
/plugin install playwright-skill@playwright-skill
```

### 3-4. 공식 플러그인 (기본 마켓플레이스)

```
/plugin install code-intelligence
/plugin install semgrep
```

### 3-5. 설치 확인

```
/plugin list
```

---

## 4단계: MCP 서버 설정 (선택사항)

### GitHub MCP (이슈/PR 관리)

```bash
claude mcp add github --transport http https://api.githubcopilot.com/mcp
```

### Context7 MCP (라이브 문서 조회)

```bash
claude mcp add context7 --transport http https://mcp.context7.com/mcp
```

---

## 5단계: Python 프로젝트 환경 구성

```bash
cd /path/to/web-agentic-CLAUDE

# 가상환경 생성
python3.11 -m venv .venv
source .venv/bin/activate

# 핵심 의존성 설치
pip install --upgrade pip
```

### requirements.txt 생성 (아직 없는 경우)

```bash
cat > requirements.txt << 'EOF'
# === 브라우저 자동화 ===
playwright>=1.40.0

# === LLM API ===
google-generativeai>=0.8.0

# === 비전/객체 탐지 ===
ultralytics>=8.1.0
Pillow>=10.0.0
opencv-python-headless>=4.8.0

# === 프롬프트 최적화 ===
dspy-ai>=2.4.0

# === 데이터 모델 ===
pydantic>=2.5.0
PyYAML>=6.0.1

# === 데이터베이스 ===
aiosqlite>=0.19.0
# psycopg[binary]>=3.1.0   # PostgreSQL 사용 시 주석 해제

# === 린팅/타입체크 ===
ruff>=0.4.0
mypy>=1.8.0

# === 테스트 ===
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
pytest-playwright>=0.4.0

# === 유틸리티 ===
httpx>=0.27.0
EOF
```

```bash
pip install -r requirements.txt

# Playwright 브라우저 바이너리 설치 (필수!)
playwright install chromium
playwright install-deps
```

---

## 6단계: 환경 변수 설정

```bash
cat > .env << 'EOF'
# Google Gemini API
GEMINI_API_KEY=your-gemini-api-key-here

# 선택사항
DATABASE_URL=sqlite:///data/patterns.db
LOG_LEVEL=INFO
BUDGET_PER_TASK=0.05
EOF
```

> `.env`는 `.gitignore`에 반드시 추가할 것

---

## 7단계: 프로젝트 초기 검증

```bash
# 린팅 확인
ruff check src/

# 타입 체크 확인
mypy --strict src/

# 테스트 실행
pytest tests/ -v

# Playwright 동작 확인
python -c "from playwright.async_api import async_playwright; print('OK')"

# YOLO 동작 확인 (GPU 있는 경우)
python -c "from ultralytics import YOLO; print('OK')"
```

---

## 8단계: Claude Code로 개발 시작

```bash
cd /path/to/web-agentic-CLAUDE

# Claude Code 실행
claude
```

진입 후:

```
# CLAUDE.md를 읽어서 프로젝트 이해
CLAUDE.md를 읽고 Phase 1을 시작해줘

# 또는 Superpowers 사용
/superpowers:brainstorm Phase 1의 Executor 모듈을 어떻게 구현할지 논의하자
/superpowers:write-plan Phase 1 전체 구현 계획을 세워줘
/superpowers:execute-plan
```

### 멀티에이전트 방식 직접 사용

```
@planner Phase 1의 Executor 태스크를 분해해줘
@developer planner가 정의한 executor.py를 구현해줘
@reviewer developer가 작성한 executor.py를 리뷰해줘
@tester executor.py의 단위 테스트를 작성하고 실행해줘
```

---

## 전체 설치 명령어 요약 (원-라이너)

시스템 패키지부터 Python 환경까지 한번에:

```bash
# 1. 시스템 패키지
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-dev git curl build-essential libgl1-mesa-glx libglib2.0-0 sqlite3

# 2. Claude Code
curl -fsSL https://claude.ai/install.sh | bash

# 3. Python 환경
cd /path/to/web-agentic-CLAUDE
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium && playwright install-deps

# 4. Claude Code 플러그인 (claude 실행 후)
# /plugin marketplace add obra/superpowers-marketplace
# /plugin install superpowers@superpowers-marketplace
```

---

## 트러블슈팅

| 문제 | 해결 |
|------|------|
| `claude: command not found` | `source ~/.bashrc` 또는 새 터미널 열기 |
| Playwright 브라우저 없음 | `playwright install chromium && playwright install-deps` |
| YOLO GPU 미인식 | `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121` |
| mypy 타입 에러 다수 | Phase 1 개발 중에는 `mypy --strict src/core/` 모듈별 실행 |
| SQLite 권한 에러 | `mkdir -p data && chmod 755 data` |
| `/plugin` 명령 안 됨 | Claude Code 최신 버전 확인: `claude --version` |
| Alpine Linux 호환성 | `apk add libgcc libstdc++ ripgrep` + `export USE_BUILTIN_RIPGREP=0` |
