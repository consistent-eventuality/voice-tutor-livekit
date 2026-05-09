# voice-tutor-livekit

A real-time voice AI tutor built on [LiveKit](https://livekit.io). The user
talks, the tutor talks back — bidirectional, low-latency, in the browser.

The tutor's subject is intentionally open-ended in this scaffold: the agent
asks the user what they'd like to learn and teaches whatever they pick. See
[Parked decisions](#parked-decisions) for a topic shortlist.

## Quickstart

Two commands:

```bash
cp .env.example .env   # then fill in 4 keys (see below)
docker compose up --build
```

Then open <http://localhost:5173>, click **Start session**, allow microphone
access, and start talking.

### Required keys

| Var | Where to get it |
|---|---|
| `LIVEKIT_URL` | <https://cloud.livekit.io> → Project → Settings (starts with `wss://`) |
| `LIVEKIT_API_KEY` | Same place → Keys → Create new key |
| `LIVEKIT_API_SECRET` | Same key, shown only once at creation |
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> (Realtime API access) |

### Verifying it's up

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/token -H 'content-type: application/json' -d '{}'
# {"token":"eyJ...","url":"wss://...","room_name":"tutor-...","identity":"guest-..."}
```

## Architecture

```
┌─────────┐  POST /token   ┌──────────────────┐
│ Browser │───────────────▶│ FastAPI (api)    │  mints short-lived JWT
│ (React) │◀───────────────│ port 8000        │
└────┬────┘                └──────────────────┘
     │
     │ WebRTC connect (token in handshake)
     ▼
┌──────────────────────────────────────────────┐
│ LiveKit Cloud (SFU + dispatcher)             │
│   • Forwards audio packets between peers     │
│   • Dispatches new rooms to idle workers     │
└──────────┬───────────────────────────────────┘
           │ outbound WebSocket
           ▼
┌────────────────────────────────────┐
│ Agent worker (livekit-agents)      │
│   joins room as 2nd participant    │
│   ─ subscribes to user's audio     │
│   ─ runs OpenAI Realtime           │
│     (STT + LLM + TTS in one model) │
│   ─ publishes agent audio back     │
└────────────────────────────────────┘
```

Three services, each with one job:

- **`backend/`** (FastAPI) mints LiveKit access tokens. Stateless. Never
  touches audio.
- **`agent/`** (livekit-agents worker) is a long-lived process that registers
  with LiveKit Cloud. When a user joins a room, the dispatcher assigns this
  worker; it joins the room as a participant, runs the voice loop, and leaves
  when the user does.
- **`frontend/`** (Vite + React) is the UI: token fetch, `<LiveKitRoom>`,
  visualizer, and a single Start/Stop button.

Token minting and voice/AI logic live in different processes so they scale
independently — one is HTTP request/response, the other is long-lived WebRTC
sessions.

## Design decisions

**OpenAI Realtime end-to-end.** The agent uses
`livekit.plugins.openai.realtime.RealtimeModel` for STT + LLM + TTS in one
model. Tradeoffs: lowest latency (~500ms speech-to-speech), one provider, one
API key, ~30 LOC in `agent.py`. The pipelined alternative (Deepgram STT +
OpenAI LLM + Cartesia TTS + Silero VAD) gives finer control over each stage
and best-in-class TTS, at the cost of 4 API keys, more plugins, and ~300ms
extra latency. A commented-out config block is preserved in `agent.py` to
show the swap path.

**Separate agent worker process.** The agent could in principle be embedded
in FastAPI via background tasks, but that would couple HTTP concurrency
(many short requests) to WebRTC concurrency (few long sessions) and lose the
LiveKit dispatcher's worker-pool semantics. Two clean services is the
canonical pattern.

**No database.** The scaffold is stateless — sessions don't persist. Adding
SQLite for transcript history is a ~30-minute extension (see
[Parked decisions](#parked-decisions)).

**No auth.** Reviewers shouldn't have to sign up to talk to the tutor. If
multi-user persistence becomes a goal, drop in a JWT middleware on the
`/token` endpoint.

**Plain `os.getenv` config.** Mirrors the broader codebase style; no
`pydantic-settings` to keep dep surface minimal.

## Scaling to 10k concurrent sessions

Two axes scale separately:

- **Token API (FastAPI)** is stateless and trivial to horizontally scale —
  put it behind any HTTP autoscaler (k8s HPA, ECS, Railway). 10k sessions
  doesn't mean 10k token-mints/sec; it's a one-time call per session join.
  A handful of pods is enough.
- **Agent worker pool** is the harder one. Each worker handles N concurrent
  sessions (tunable via `WorkerOptions.num_idle_processes`). For 10k:
  - Run agent workers as a horizontally-scaled stateless Deployment in k8s
    or ECS, scaled on CPU + active-session count.
  - LiveKit Cloud handles SFU/TURN scaling automatically. For self-hosting,
    you'd run a LiveKit cluster with Redis for session state and TURN
    servers for NAT traversal.
  - Add Postgres + Redis if persistence (transcripts, resumability) is
    introduced.
  - Watch OpenAI Realtime rate limits — at this scale you'd negotiate
    higher quotas or pool across multiple keys.

The single-process-per-pod model means a worker crash kills only the
sessions on that pod, not the whole fleet.

## Project layout

```
.
├── backend/          # FastAPI: /health, /token
│   ├── app/
│   │   ├── main.py
│   │   └── livekit_token.py
│   └── tests/
├── agent/            # livekit-agents worker (long-lived)
│   └── agent.py
├── frontend/         # Vite + React + TS + Tailwind v4
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       └── components/VoicePanel.tsx
├── docker-compose.yml
├── .env.example
└── README.md
```

## Parked decisions

These were intentionally deferred so the scaffold is easy to evaluate. Each
is a small, contained extension:

- **Tutor topic.** The agent currently asks the user what they want to learn.
  Candidate fixed subjects: cocktail mixology, chess openings, music theory,
  obscure history. To pick one, edit `TUTOR_INSTRUCTIONS` in `agent/agent.py`.
- **Post-session summary** *(bonus)*. After the room closes, a summary task
  could send the transcript to GPT-4o for "key topics + suggested follow-ups."
  Requires either capturing transcripts via the agent's STT events or via
  LiveKit's recording API.
- **Session resumability** *(bonus)*. Persist transcripts keyed by user id;
  on reconnect, prepend prior context to the agent's instructions. Needs
  SQLite + a stable user identifier.
- **Reconnect / error handling** *(bonus)*. Frontend already retries on
  user-initiated reconnect; agent-side could wrap the LLM call in a
  try/except and play a friendly "let me try that again" fallback.
- **Auth.** No auth in the scaffold. JWT middleware on `/token` would be the
  drop-in.

## Gotchas

- `LIVEKIT_URL` must start with `wss://`, not `https://`.
- Microphone permission requires `localhost` or HTTPS — testing via your
  LAN IP will fail silently with no audio.
- Hot-reload (`agent.py dev`) doesn't re-join rooms that are already live;
  refresh the browser after agent code edits.
- The agent worker must be able to reach LiveKit Cloud over outbound
  WebSocket. If it boots and immediately exits, check `LIVEKIT_API_KEY` /
  `LIVEKIT_API_SECRET`.

## Running pieces individually

If you'd rather not use Docker for local dev:

```bash
# api
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# agent (in another terminal, same .env loaded)
cd agent && pip install -r requirements.txt
python agent.py dev

# frontend (in another terminal)
cd frontend && npm install && npm run dev
```

## Tests

```bash
cd backend && pytest
```

Two endpoints are covered (`/health` and `/token` shape). Frontend has no
test runner wired up — out of scope for the scaffold.
