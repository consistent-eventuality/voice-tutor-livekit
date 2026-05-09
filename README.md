# voice-tutor-livekit

A real-time voice AI tutor built on [LiveKit](https://livekit.io). The user
talks, the tutor talks back — bidirectional, low-latency, in the browser.

The tutor's subject is intentionally open-ended in this scaffold: the agent
asks the user what they'd like to learn and teaches whatever they pick. See
[Parked decisions](#parked-decisions) for a topic shortlist.

## Quickstart

```bash
cp .env.example .env   # then fill in 4 keys (see below)
docker compose up --build
```

Then open <http://localhost:5173>, click **Start session**, allow microphone
access, and start talking.

> **Env precedence.** Compose reads variables from your shell first, falling
> back to the `.env` file. If you already export `LIVEKIT_*` and
> `OPENAI_API_KEY` in your shell profile (`~/.zprofile` etc.), you don't need
> to populate `.env` at all.

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

- **`backend/`** (FastAPI + SQLite) mints LiveKit access tokens, persists
  lessons, and serves the agent's "what's the prior context for this room?"
  query. Stateless except for the SQLite file under `data/`.
- **`agent/`** (livekit-agents worker) is a long-lived process that registers
  with LiveKit Cloud. When a user joins a room, the dispatcher assigns this
  worker; it joins the room as a participant, runs the voice loop, and leaves
  when the user does. On dispatch it fetches prior-lesson context from the
  backend; on shutdown it posts the new transcript back.
- **`frontend/`** (Vite + React) is the UI: home view with past-lessons list,
  voice panel with `<LiveKitRoom>`, visualizer, and the LiveKit control bar.

Token minting and voice/AI logic live in different processes so they scale
independently — one is HTTP request/response, the other is long-lived WebRTC
sessions.

## Resumable lessons

The data model has two tables:

- **`lessons`** — the persistent learning thread. One row per topic the user
  has explored. Has a `topic` derived from the first user utterance.
- **`sessions`** — one row per LiveKit room joined. Children of a lesson.
  Holds the JSON transcript for that specific connection.

When the user clicks **Resume** on a past lesson, the API attaches a new
`sessions` row to that existing lesson. On dispatch, the agent calls
`GET /sessions/by-room/{room}` and the API returns the concatenated
transcript across all prior sessions of that lesson. The agent seeds its
instructions with that history and continues.

User identity is an anonymous UUID generated client-side and stored in
`localStorage` — no auth required, but persistent enough for "come back
tomorrow."

### Endpoints at a glance

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Smoke test |
| `POST` | `/token` | Mint LiveKit JWT, create lesson + session rows. Pass `lesson_id` to resume. |
| `GET` | `/lessons?user_id=...` | List the user's lessons (most recent activity first). |
| `GET` | `/sessions/by-room/{room_name}` | Agent fetches this on dispatch — returns concatenated prior-lesson transcript. |
| `POST` | `/sessions/end` | Agent posts here on shutdown with the new transcript. Discards empty sessions. |

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

**SQLite for lesson persistence.** A single file at `data/voice_tutor.db`,
two tables (`lessons`, `sessions`), no migrations framework. Sufficient for
single-instance deployment — the migration to Postgres is one URL change.

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
├── backend/          # FastAPI + SQLite
│   ├── app/
│   │   ├── main.py            # endpoints: /health, /token, /lessons, /sessions/...
│   │   ├── db.py              # SQLAlchemy: Lesson + TutorSession models
│   │   └── livekit_token.py
│   └── tests/test_health.py   # 6 tests covering token + lesson resume flow
├── agent/            # livekit-agents worker (long-lived)
│   └── agent.py
├── frontend/         # Vite + React + TS + Tailwind v4
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── hooks/useUserId.ts
│       ├── utils/time.ts
│       └── components/
│           ├── Home.tsx       # past-lessons list + Start new
│           └── VoicePanel.tsx # in-session voice UI
├── data/             # SQLite file lives here (gitignored)
├── docker-compose.yml
├── .env.example
└── README.md
```

## TODO before submission

- [ ] **Spin up a dedicated LiveKit Cloud project for this take-home.**
  During development this scaffold reuses an existing personal LiveKit project,
  which means tutor sessions count against that project's quota. Before
  submitting, create a fresh project at <https://cloud.livekit.io>, generate
  new API key + secret, and update `LIVEKIT_URL` / `LIVEKIT_API_KEY` /
  `LIVEKIT_API_SECRET`.

## Parked decisions

These were intentionally deferred so the scaffold is easy to evaluate. Each
is a small, contained extension:

- **Tutor topic.** The agent currently asks the user what they want to learn.
  Candidate fixed subjects: cocktail mixology, chess openings, music theory,
  obscure history. To pick one, edit `TUTOR_INSTRUCTIONS` in `agent/agent.py`.
- **Session resumability — implemented.** See [Resumable lessons](#resumable-lessons)
  above. Past lessons appear on the home screen; clicking one resumes with
  full prior-conversation context fed to the agent.
- **Post-session summary** *(deferred)*. Right now the agent receives the full
  prior transcript on resume. For long lessons (30min+), this dilutes the
  agent's working context. The fix is a one-shot LLM call at session end that
  produces a 2-sentence summary stored on the `lessons` row, with the agent
  receiving "summary of older sessions + verbatim of latest session."
- **Reconnect / brief disconnect tolerance** *(deferred)*. LiveKit's
  `empty_timeout` would let the agent stay in the room for ~60s after the
  user drops, so a refresh or network blip doesn't end the session. One field
  on the room-create call.
- **Auth.** No auth in the scaffold; user identity is an anonymous UUID in
  localStorage. JWT middleware on `/token` would be the drop-in for real
  multi-user.

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
