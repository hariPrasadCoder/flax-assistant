# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dev Commands

### Start everything (dev)
```bash
bash start.sh                          # starts backend + desktop in parallel
```

### Backend only
```bash
cd backend && source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8747        # production-like
uvicorn main:app --reload                           # hot reload
bash run.sh                                        # auto-restart on crash
```

### Desktop only
```bash
cd desktop
npm run dev          # Electron dev mode (live reload)
npm run build        # build Vite assets only
npm run package      # build + package to macOS DMG
npm run typecheck    # TypeScript type check
```

### Logs when running
- Backend: stdout or `/tmp/flax-backend.log` (if started with nohup)
- Desktop: `/tmp/flax-desktop.log` (if started with nohup)
- Stop: `pkill -f "uvicorn main:app" && pkill -f "electron"`

## Architecture Overview

Flax Assistant is an AI accountability agent — a tray app that autonomously monitors tasks and nudges users. Three tiers:

1. **Backend (Python/FastAPI, port 8747)** — The brain. Runs the autonomous agent loop, REST API, and WebSocket server.
2. **Desktop (Electron + React)** — Two windows: a chat panel (380×540) and a notification banner (380×160). Lives in the system tray.
3. **Database (Supabase PostgreSQL)** — All persistent state. Backend uses the Supabase Python SDK (service role); desktop uses `@supabase/supabase-js` for auth only.

**Communication:**
- Desktop → Backend: REST (`http://localhost:8747/api/...`)
- Backend → Desktop: WebSocket (`ws://localhost:8747/ws/mascot?user_id=...`) for nudges, mascot state, reflections
- Auth: Supabase OTP (email) handled entirely in the renderer via `@supabase/supabase-js` anon key; backend uses service role key for DB queries only

## Backend Structure

```
backend/
├── main.py              # FastAPI app, lifespan hooks, router registration
├── app/
│   ├── config.py        # Pydantic Settings — all env vars
│   ├── database.py      # Supabase AsyncClient singleton (lazy init)
│   ├── models.py        # Enums only: TaskStatus, MemoryType + new_id()
│   ├── scheduler.py     # APScheduler: agent cycles every ~15 min per user
│   ├── websocket_manager.py  # Singleton: one WS connection per user, push methods
│   ├── routers/
│   │   ├── auth.py      # POST /api/auth/setup, GET /api/auth/me, focus endpoints
│   │   ├── tasks.py     # CRUD + status updates
│   │   ├── chat.py      # POST /api/chat (rate-limited 20/min), GET history
│   │   ├── nudges.py    # Nudge action responses
│   │   ├── team.py      # Team create/join, member management
│   │   ├── calendar.py  # Google Calendar sync
│   │   └── websocket.py # WS connection handler
│   └── ai/
│       ├── agent.py     # LangGraph agent: tools + observe→think→act loop
│       ├── brain.py     # Chat completions (stateless, context-injected)
│       ├── llm.py       # Gemini client via LiteLLM + Langfuse tracing
│       └── memory.py    # Memory CRUD: save, get_recent, get_learnings, upsert_learning
```

## Desktop Structure

```
desktop/src/
├── main/index.ts         # Electron main: tray, two BrowserWindows, WS relay, IPC handlers
├── preload/index.ts      # IPC bridge exposed as window.flaxie.*
└── renderer/src/
    ├── ChatApp.tsx        # Main chat UI: messages, QuickAddTask, task chips, settings panel
    ├── NotifBanner.tsx    # Notification banner with action buttons
    ├── chat/
    │   ├── Onboarding.tsx    # 4-step OTP auth flow (welcome→email→otp→name→team)
    │   ├── MessageBubble.tsx # Renders chat messages with inline markdown
    │   └── TaskChip.tsx      # Task row with done/snooze/expand actions
    └── lib/
        └── parseTaskDate.ts  # NLP date parser ("by Friday", "next Monday", "April 3")
```

## Key Patterns

### Autonomous Agent Loop
`scheduler.py` runs `run_agent_cycle(user_id)` per connected user. Each cycle:
1. **Observe**: load tasks, memories, learnings, nudge history, focus state from Supabase
2. **Think**: LangGraph runs the agent with tools (max 3 iterations)
3. **Act**: agent calls tools → nudges queued → sent via WebSocket

The agent decides its own next check time (adaptive interval, respects quiet hours).

### Memory System
Four `MemoryType` values: `conversation`, `task_event`, `learning`, `context_snapshot`. Memories have optional TTL. `learning` type is upserted (deduped by content hash). The agent loads the last 48h of memories + all learnings on every cycle.

### Chat vs Agent
- `brain.py` — stateless, called per chat message, returns `{ reply, tasks_to_create, tasks_to_update, task_refs }`
- `agent.py` — stateful LangGraph agent, called on a schedule, sends nudges, never directly responds in chat

### Markdown in Chat
`MessageBubble.tsx` has a hand-rolled inline markdown renderer (no external deps). Supports `**bold**`, `*italic*`, bullet lists (`- item`), blank line spacing. Brain is instructed to use markdown in responses.

### Date Parsing
`parseTaskDate(input)` in `lib/parseTaskDate.ts` is pure regex — no AI. Returns `{ title, deadline, deadlineLabel }`. Used in QuickAddTask for live deadline preview.

### Env Vars
- Backend: standard `.env` loaded by Pydantic Settings
- Desktop main process: must use `MAIN_VITE_` prefix (electron-vite convention), accessed via `import.meta.env.MAIN_VITE_*`
- Desktop renderer: must use `VITE_` prefix, accessed via `import.meta.env.VITE_*`

### Python Version
The backend venv uses Python 3.9. Use `Optional[X]` instead of `X | None` and `from __future__ import annotations` in any file that uses union type syntax.

## Environment Setup

**Backend** (`backend/.env`):
```
GEMINI_API_KEY=...
SECRET_KEY=...
BACKEND_PORT=8747
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_KEY=<service-role-key>
LANGFUSE_SECRET_KEY=...   # optional
LANGFUSE_PUBLIC_KEY=...   # optional
LANGFUSE_HOST=https://cloud.langfuse.com
```

**Desktop** (`desktop/.env`):
```
MAIN_VITE_BACKEND_URL=http://localhost:8747
MAIN_VITE_WS_URL=ws://localhost:8747/ws/mascot
MAIN_VITE_SUPABASE_URL=https://<ref>.supabase.co
MAIN_VITE_SUPABASE_ANON_KEY=<anon-key>
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon-key>
```

## Supabase Schema

Schema lives in `supabase/schema.sql`. Run it directly in the Supabase SQL Editor (CLI `supabase db push` requires interactive login). Key tables: `users`, `teams`, `tasks`, `memories`, `nudge_logs`, `chat_messages`, `invite_codes`.

## Deployment

See `DEPLOYMENT.md` for full AWS ECS + ECR + ALB setup. CI/CD via `.github/workflows/deploy-backend.yml` (backend) and `.github/workflows/build-desktop.yml` (macOS DMG). Backend uses `backend/Dockerfile`; task definition at `infrastructure/ecs/assistant-task-definition.json`.
