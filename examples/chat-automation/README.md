# Chat Automation Example

Chat-based UI for Web-Agentic. Type natural language instructions and watch automation execute in real time.

## Features

- Chat interface for web automation commands
- Real-time step-by-step progress via SSE
- Live screenshots after each turn
- CAPTCHA/authentication handoff handling
- Turn cancellation support
- Session management (create, close, headful/headless toggle)

## Quick Start

```bash
# 1. Start the API server (from project root)
pip install -e ".[server]"
python scripts/start_server.py  # localhost:8000

# 2. Start the frontend
cd examples/chat-automation
npm install
npm run dev                     # localhost:5174
```

Open http://localhost:5174 in your browser.

## Usage

1. Optionally enter a starting URL
2. Type your automation intent (e.g., "Search Google for web automation tools")
3. Watch step-by-step progress in the chat
4. View screenshots after each turn completes
5. Handle CAPTCHA/auth prompts inline when they appear
6. Cancel running turns with the Cancel button

## Architecture

```
Browser ─── SSE (session_progress) ──► Real-time step logs
       ─── POST /api/sessions/{id}/turn ──► Execute turns
       ─── POST /api/sessions/{id}/cancel ──► Cancel running turn
       ─── GET /api/sessions/{id}/screenshot ──► Page screenshots
       ─── POST /api/sessions/{id}/handoffs/{rid}/resolve ──► CAPTCHA input
```

## Tech Stack

- React 19 + TypeScript
- Vite 7 + Tailwind CSS 4
- SSE for real-time updates
- Vite proxy to backend API (localhost:8000)
