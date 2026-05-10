# voice-tutor-livekit

A real-time voice AI tutor for **communication protocols** (HTTP, WebSockets,
WebRTC) built on [LiveKit](https://livekit.io). The product isn't the LLM
teaching — it's the **loop machinery** that turns "voice ChatGPT" into a
structured tutor: teach → grade → adapt.

## What's actually being demonstrated

Three layers of composition. Only the bottom layer is built in this take-home;
the rest is parked but the design is intentional.

```
Curriculum  =  DAG of Lessons (with prereq edges)              ← parked
Lesson      =  ordered list of Concepts (~3-5)                 ← built (3 concepts)
Concept     =  the loop primitive (TEACH → GRADE → RETEACH?)   ← THE ENGINE
```

The Concept primitive is what makes this not a wrapper around ChatGPT-with-voice:

| Concern | Realized as |
|---|---|
| Speak this turn (user-facing voice) | OpenAI Realtime, **single-purpose prompt per turn** |
| Grade the user's last answer | `gpt-4o-mini` text completion, **separate call**, **`response_format` JSON schema enforced** |
| Decide next action | **Python `if`** — `if grade.score >= 7: advance()` |

Each LLM call has prose for one task only. The if-statement lives in Python
where if-statements work. The realtime model never has to police itself
across multi-step instructions.

## Quickstart

```bash
cp .env.example .env   # then fill in 4 keys (see below)
docker compose up --build
```

Open <http://localhost:5173>, click **Start new lesson**, allow microphone
access, and start talking. The agent will run you through HTTP basics →
WebSockets → WebRTC, then give a short synthesis tying them together.

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
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> (Realtime + chat completions access) |

### Verifying it's up

```bash
curl http://localhost:8000/health
# {"status":"ok"}

docker logs voice-tutor-agent | grep "registered worker"
# INFO:livekit.agents:registered worker  {"agent_name": "", ...}
```

After a session, the agent log will show grading lines:
```
INFO:voice-tutor-agent:Grade: concept=HTTP_BASICS score=8 gaps=[] phase_before=teach
INFO:voice-tutor-agent:Phase after transition: teach (idx=1)
```

## The Concept loop, in detail

```
                  ┌─ Python pushes focused instruction ─┐
                  │   prompts.teach(concept N)          │
                  ▼                                     │
  ┌──────────────────────┐                              │
  │  Realtime agent      │ ── speaks turn ──▶  user     │
  │ (one job per turn)   │ ◀── listens ──               │
  └──────────┬───────────┘                              │
             │ user finishes (turn detected)            │
             ▼                                          │
  ┌──────────────────────────────────────────┐          │
  │  grader.grade(concept, user_text)        │          │
  │   → gpt-4o-mini, response_format JSON    │          │
  │   → returns {score: int, gaps: list[str]}│          │
  └──────────┬───────────────────────────────┘          │
             ▼                                          │
  ┌──────────────────────────────────────────────┐      │
  │  state.transition(grade) — Python if/else    │      │
  │    score >= 7  → next concept (or DONE)      │      │
  │    score <  7  → RETEACHING (one attempt)    │      │
  │    already retaught → next concept regardless│      │
  └──────────┬───────────────────────────────────┘      │
             │                                          │
             └──────────────────────────────────────────┘
                              loop until DONE → synthesize
```

Lesson states: `teach(N)` → `reteach(N, gaps)` → next → ... → `synthesize` → `done`.

The four agent files that implement this:

| File | Job |
|---|---|
| `agent/lesson.py` | Concepts + the ordered `LESSON` list. Pure data. |
| `agent/prompts.py` | `teach(concept)`, `reteach(concept, gaps)`, `synthesize(lesson)`. Single-purpose. |
| `agent/grader.py` | `Grader.grade()` — separate gpt-4o-mini call, JSON schema enforced. |
| `agent/state_machine.py` | `LessonState` — pure Python, deterministic transitions. |
| `agent/agent.py` | Wires it together. Listens for `user_input_transcribed`, calls grader, transitions state, pushes next focused instruction via `session.generate_reply(instructions=...)`. |

## Architecture

```
┌─────────┐  POST /token   ┌──────────────────┐
│ Browser │───────────────▶│ FastAPI (api)    │  mints short-lived JWT
│ (React) │◀───────────────│ port 8000        │  persists lesson + sessions
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
┌──────────────────────────────────────────────┐
│ Agent worker (livekit-agents)                │
│   ─ joins room as 2nd participant            │
│   ─ Realtime model speaks (per-turn prompts) │
│   ─ Grader (gpt-4o-mini) judges each user    │
│     turn against rubric → JSON {score, gaps} │
│   ─ Python state machine decides next phase  │
└──────────────────────────────────────────────┘
```

Three services, each with one job:

- **`backend/`** (FastAPI + SQLite) mints LiveKit access tokens, persists
  lessons + transcripts. Stateless except for the SQLite file under `data/`.
- **`agent/`** (livekit-agents worker) is a long-lived process registered with
  LiveKit Cloud. When a user joins a room, the dispatcher assigns this worker;
  the worker runs the structured loop (state machine + grader + focused
  prompts) until the user disconnects.
- **`frontend/`** (Vite + React) is the UI: home view with past-lessons list,
  voice panel with `<LiveKitRoom>`, visualizer, control bar.

Token minting and voice/AI logic live in different processes so they scale
independently — one is HTTP request/response, the other is long-lived WebRTC
sessions.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Smoke test |
| `POST` | `/token` | Mint LiveKit JWT, create lesson + session rows. Pass `lesson_id` to resume. |
| `GET` | `/lessons?user_id=...` | List the user's lessons (most recent first). |
| `GET` | `/sessions/by-room/{room_name}` | Agent fetches this on dispatch — returns prior transcripts on resume (currently unused by the new state machine but kept for future cross-session adaptation). |
| `POST` | `/sessions/end` | Agent posts here on shutdown with the new transcript. Discards empty sessions. |

### Persistence (lessons + sessions)

- **`lessons`** — one row per (user, learning thread). Best understood as
  `UserLesson` — the user's enrollment in a content-Lesson. Currently there's
  only one content-Lesson hardcoded (the 3-concept `LESSON` in
  `agent/lesson.py`), so every row is an instance of the same content. When
  the Curriculum DAG lands, this table will gain a `content_lesson_id` FK.
- **`sessions`** — one row per LiveKit room joined under a lesson. Holds the
  JSON transcript of that specific connection.

User identity is an anonymous UUID generated client-side and stored in
`localStorage` — no auth required, but persistent enough for "come back
tomorrow" continuity.

## Design decisions

**Externalized grading (this is the big one).** Realtime models routinely
drift from multi-step prose instructions. "If grade < 7 then reteach" works
in testing and silently fails in prod. Function calling on the realtime
model has the same flaw — *whether* to call the tool is still prose-driven.
So grading is moved out of the realtime model entirely: a separate
`gpt-4o-mini` text completion with `response_format: json_schema(strict)`,
which the OpenAI API itself validates. The realtime model only ever has one
job per turn (speak the current state's prompt). The if-statement lives in
Python.

**OpenAI Realtime end-to-end for voice.** The agent uses
`livekit.plugins.openai.realtime.RealtimeModel` for STT + LLM + TTS in one
model. Tradeoffs: lowest latency (~500ms speech-to-speech), one provider for
voice. The pipelined alternative (Deepgram STT + OpenAI LLM + Cartesia TTS +
Silero VAD) gives finer control at the cost of 4 plugins, more keys, and
~300ms extra latency. A commented config block in `agent.py` shows the swap.

**Separate agent worker process.** The agent could in principle be embedded
in FastAPI via background tasks, but that would couple HTTP concurrency
(many short requests) to WebRTC concurrency (few long sessions) and lose the
LiveKit dispatcher's worker-pool semantics. Two clean services is canonical.

**SQLite for persistence.** Single file at `data/voice_tutor.db`, two tables,
no migrations framework. Postgres swap is one URL change.

**No auth.** Reviewers shouldn't have to sign up. JWT middleware on `/token`
is the drop-in for real multi-user.

**Plain `os.getenv` config.** No `pydantic-settings`. Minimal dep surface.

## Scaling to 10k concurrent sessions

Two axes scale separately:

- **Token API (FastAPI)** is stateless and trivial to horizontally scale —
  put it behind any HTTP autoscaler (k8s HPA, ECS, Railway). 10k sessions
  doesn't mean 10k token-mints/sec; it's one call per session join.
- **Agent worker pool** is the harder one. Each worker handles N concurrent
  sessions (tunable via `WorkerOptions.num_idle_processes`). For 10k:
  - Run agent workers as a horizontally-scaled stateless Deployment, scaled
    on CPU + active-session count.
  - LiveKit Cloud handles SFU/TURN auto-scaling. Self-hosting would mean
    running a LiveKit cluster + Redis + TURN servers.
  - Swap SQLite for Postgres + Redis if persistence grows.
  - Watch OpenAI rate limits — at this scale you'd negotiate higher quotas
    or pool across keys. The grader (`gpt-4o-mini`) has separate quotas from
    the realtime model.
  - The Python state machine is per-job (per worker subprocess), so it's
    stateless across workers. No cross-worker coordination needed.

The single-process-per-pod model means a worker crash kills only the
sessions on that pod, not the whole fleet.

## Project layout

```
.
├── backend/          # FastAPI + SQLite
│   ├── app/
│   │   ├── main.py            # /health, /token, /lessons, /sessions/...
│   │   ├── db.py              # SQLAlchemy: Lesson + TutorSession models
│   │   └── livekit_token.py
│   └── tests/test_health.py
├── agent/            # livekit-agents worker (the engine)
│   ├── agent.py               # state-machine orchestration; LiveKit integration
│   ├── lesson.py              # 3 concepts as fixture data
│   ├── prompts.py             # teach() / reteach() / synthesize()
│   ├── grader.py              # gpt-4o-mini call with JSON-schema response_format
│   └── state_machine.py       # LessonState; deterministic transitions
├── frontend/         # Vite + React + TS + Tailwind v4
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── hooks/useUserId.ts
│       ├── utils/time.ts
│       └── components/
│           ├── Home.tsx       # past-lessons list + Start new
│           └── VoicePanel.tsx # in-session voice UI
├── data/             # SQLite file (gitignored)
├── docker-compose.yml
├── .env.example
└── README.md
```

## Out of scope (deliberately)

These are explicitly parked so the take-home stays focused on the loop
machinery. Each is a clear next step:

- **Curriculum content quality and breadth.** 3 fixture concepts. Production
  wants 30+, expert-written, editorially reviewed.
- **Prompt tuning.** Every prompt (TEACH / RETEACH / SYNTHESIZE / GRADE) is
  first-cut. A real ship would A/B variations against held-out transcripts to
  tune wording, the grading threshold, the reteach behavior.
- **Persisting grades.** `Grade` flows through Python in-session but isn't
  written to DB. The natural next step is a per-(session, concept) grades
  table for cross-session use.
- **Cross-session adaptation.** Home doesn't show mastery dots; the agent
  doesn't get prior mastery in its instructions. The transcript is in the DB,
  but nothing consumes it across sessions yet.
- **Multi-attempt reteach.** One re-attempt per concept then move on.
  Production would have escalation rules ("third miss → flag for review").
- **Curriculum as a DAG.** Current `LESSON` is a flat ordered list of
  concepts. The natural next shape is a *Curriculum* — a DAG of Lessons with
  prereq edges between them. The state machine would walk the DAG: branch
  into sub-lessons on weak answers, skip ahead when prereqs are clearly
  mastered, surface "you're ready for X next" affordances. The Concept-loop
  machinery built here is the unit; Lessons compose Concepts; a Curriculum
  composes Lessons.
- **Reconnect / brief disconnect tolerance** — partly handled. On
  `participant_disconnected` we branch on `DisconnectReason`: explicit
  disconnect tears down immediately; network drops fall through to LiveKit's
  `empty_timeout` so a brief blip doesn't end the session. Real reconnect
  with localStorage-stored `room_name` is parked.
- **Session resumability in agent prompts.** The agent fetches prior
  transcripts on dispatch but doesn't currently use them — out of scope until
  cross-session adaptation lands.
- **Auth.** Anonymous UUID in localStorage. JWT middleware on `/token` is
  the drop-in.
- **Frontend mastery UI.** Past lessons are listed with a topic derived from
  the user's first utterance — likely awkward fragments. Mastery indicators
  would surface here.

## Gotchas

- `LIVEKIT_URL` must start with `wss://`, not `https://`.
- Microphone permission requires `localhost` or HTTPS — testing via your LAN
  IP will fail silently with no audio.
- Hot-reload (`agent.py dev`) doesn't re-join rooms that are already live;
  refresh the browser after agent code edits.
- The agent worker must be able to reach LiveKit Cloud over outbound
  WebSocket. If it boots and immediately exits, check `LIVEKIT_API_KEY` /
  `LIVEKIT_API_SECRET`.
- The grader is a separate API call (gpt-4o-mini text completion) per user
  turn. It's fast (~500ms-1s) but adds noticeable pause between you finishing
  speaking and the tutor's next turn.

## Running pieces individually

If you'd rather not use Docker:

```bash
# api
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# agent (in another terminal, same .env)
cd agent && pip install -r requirements.txt
python agent.py dev

# frontend
cd frontend && npm install && npm run dev
```

## Tests

```bash
cd backend && pytest
```

6 tests cover token + lesson resume flow. The agent's state machine and
grader don't have automated tests in this build — both are pure functions
that would be straightforward to test, but loop fidelity is qualitative
(does the model actually speak the focused turn?) and depends on prompt
quality which is fixture/out-of-scope.

## TODO before submission

- [ ] **Spin up a dedicated LiveKit Cloud project for this take-home.**
  This scaffold currently reuses an existing personal LiveKit project for
  development. Before submitting, create a fresh project at
  <https://cloud.livekit.io>, generate new API key + secret, and update
  `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`.
