# voice-tutor-livekit

A real-time voice AI tutor for **communication protocols** (HTTP, WebSockets,
WebRTC) built on [LiveKit](https://livekit.io). The product isn't the LLM
teaching — it's the **loop machinery** that turns "voice ChatGPT" into a
structured tutor: teach → grade → adapt.

## The hierarchy

```
Curriculum  =  DAG of Lessons (with prereq edges)              ← parked
Lesson      =  ordered list of Concepts + metadata             ← built (1 lesson)
Concept     =  the loop primitive (TEACH → GRADE → RETEACH?)   ← THE ENGINE
```

The Concept primitive is what makes this not a wrapper around ChatGPT-with-voice:

| Concern | Realized as |
|---|---|
| **Speak this turn** | `AgentSession.say(static_text)` — bypasses the LLM. Content comes verbatim from `agent/lesson.py`. |
| **Transcribe the user's answer** | OpenAI Whisper (streaming STT plugin) |
| **Grade the answer** | A separate `gpt-4o-mini` text completion with `response_format` JSON-schema enforcement. The **only** LLM call in the runtime path. |
| **Decide next action** | A Python `if` in `state_machine.py:transition()`. Pass → advance. Fail → reteach. |

Each LLM call has prose for one task only. The if-statement lives in Python
where if-statements work. The agent's voice never goes through an LLM —
all spoken content is curated.

## Quickstart

```bash
cp .env.example .env   # then fill in 4 keys (see below)
docker compose up --build
```

Open <http://localhost:5173>, click any lesson under **Available**, allow
microphone access, and start talking.

> **Env precedence.** Compose reads variables from your shell first, falling
> back to the `.env` file. If you already export `LIVEKIT_*` and
> `OPENAI_API_KEY` in your shell profile, you don't need to populate `.env`.

### Required keys

| Var | Where to get it |
|---|---|
| `LIVEKIT_URL` | <https://cloud.livekit.io> → Project → Settings (starts with `wss://`) |
| `LIVEKIT_API_KEY` | Same place → Keys → Create new key |
| `LIVEKIT_API_SECRET` | Same key, shown only once at creation |
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> (used for STT, TTS, and the grader) |

Optional:
- `VOICE_TUTOR_CHEAT` — magic phrase that skips grading and force-passes the
  current concept. Default `"abracadabra"`. Useful for demoing the loop end-to-end fast.

### Verifying it's up

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/lessons
# [{"id":"communication_protocols","title":"Communication Protocols", ...}]

docker logs voice-tutor-agent | grep "registered worker"
# INFO:livekit.agents:registered worker  {"agent_name": "", ...}
```

After a session, the agent log shows the loop running:
```
INFO:voice-tutor-agent:Hydrated session 3: lesson=communication_protocols phase=teach idx=0
INFO:voice-tutor-agent:User said: 'HTTP is a request-response protocol.'
INFO:voice-tutor-agent:Grade: concept=HTTP_BASICS score=7 gaps=[] phase_before=teach
INFO:voice-tutor-agent:Phase after transition: teach (idx=1)
```

## The Concept loop, in detail

```
                  ┌────────────────────────────────────────┐
                  │  agent.session.say(curated text)       │
                  │  (bypasses LLM — pure TTS)             │
                  ▼                                        │
  ┌──────────────────────────────────────┐                 │
  │  Agent (livekit-agents pipelined)    │                 │
  │   ─ Whisper STT                      │                 │
  │   ─ no LLM in voice path             │                 │
  │   ─ TTS (OpenAI tts-1, voice=coral)  │                 │
  └──────────┬───────────────────────────┘                 │
             │ user finishes (Silero VAD detects turn)     │
             ▼                                             │
  ┌──────────────────────────────────────┐                 │
  │  grader.grade(concept, user_text)    │                 │
  │   gpt-4o-mini, response_format JSON  │                 │
  │   → {score: int, gaps: list[str]}    │                 │
  └──────────┬───────────────────────────┘                 │
             ▼                                             │
  ┌──────────────────────────────────────────────┐         │
  │  state.transition(grade) — Python if/else    │         │
  │    score ≥ PASS_THRESHOLD → advance          │         │
  │    score <  PASS_THRESHOLD → reteach (loop)  │         │
  └──────────┬───────────────────────────────────┘         │
             ▼                                             │
  ┌──────────────────────────────────────┐                 │
  │  POST /sessions/{id}/state           │                 │
  │  Persists state_json so a reconnect  │                 │
  │  can pick up here.                   │                 │
  └──────────┬───────────────────────────┘                 │
             │                                             │
             └─────────────────────────────────────────────┘
                              loop until phase = done
```

States: `teach` → `reteach` (on fail, loops to itself) → `done`. The
`teach`/`reteach` distinction is purely about spoken wording — the
re-teach prompt has a brief lead-in ("Let me walk through that one more
time"). When `phase = done`, the agent speaks the lesson's `closing`
line and shuts down on the `speaking → listening` transition.

The five agent files that implement this:

| File | Job |
|---|---|
| `agent/lesson.py` | `Concept`, `Lesson`, and the `LESSONS` registry. Pure data. |
| `agent/prompts.py` | `teach_text()`, `reteach_text()`, `closing_text()`. Format spoken text. No LLM prompts. |
| `agent/grader.py` | `Grader.grade()` — gpt-4o-mini with JSON-schema response_format. |
| `agent/state_machine.py` | `LessonState` — pure Python, deterministic transitions, `to_dict` / `from_dict` for serialization. |
| `agent/agent.py` | Wires it together. On dispatch: parse session_id from room name, fetch state, hydrate, run loop. On every transition: persist state. On final concept passed: speak closing, auto-disconnect. |

## Architecture

```
┌─────────┐ POST /sessions ┌──────────────────┐
│ Browser │───────────────▶│ FastAPI (api)    │  user_lessons + sessions
│ (React) │◀───────────────│ port 8000        │  state_json (resumption)
└────┬────┘                └──────────────────┘
     │                              ▲
     │ WebRTC connect               │  POST /sessions/{id}/state
     │ (token in handshake)         │  GET /sessions/{id}
     ▼                              │
┌──────────────────────────────────┐│
│ LiveKit Cloud                    ││
│   • SFU forwards audio packets   ││
│   • Dispatches rooms to workers  ││
└──────────┬───────────────────────┘│
           │ outbound WebSocket     │
           ▼                        │
┌──────────────────────────────────┐│
│ Agent worker (livekit-agents)    ├┘
│   ─ STT (Whisper)                │
│   ─ TTS (OpenAI tts-1)           │
│   ─ Grader (gpt-4o-mini)         │
│   ─ Python state machine         │
└──────────────────────────────────┘
```

Three services, each with one job:

- **`backend/`** (FastAPI + SQLite) mints LiveKit access tokens, persists
  user_lessons + sessions + state_json, serves the agent's lookup endpoint.
- **`agent/`** (livekit-agents worker) is a long-lived process registered with
  LiveKit Cloud. On dispatch it parses the session_id from the room name,
  fetches state from the API, hydrates the state machine, and walks the
  lesson. Per-transition state save makes the lesson resumable.
- **`frontend/`** (Vite + React + Tailwind v4) is the UI: home with Continue
  and Available sections, voice panel with `<LiveKitRoom>` + visualizer.

Token minting and voice/AI logic live in different processes so they scale
independently — the API is HTTP request/response, the agent is long-lived
WebRTC sessions.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Smoke test |
| `GET` | `/lessons` | Catalog of available lesson definitions: `[{id, title, blurb, concept_count}]`. Backed by `backend/app/lesson_catalog.py`. |
| `POST` | `/sessions` | Create a Session (or resume one). Body: `{user_id, lesson_id?, session_id?}`. Pass `session_id` to resume a specific session; pass `lesson_id` to start a fresh one. Returns the LiveKit JWT + room name. |
| `GET` | `/sessions?user_id=...` | The user's in-progress sessions for the **Continue** tiles. Includes `current_concept_name`, `idx`, `phase`, `last_active_at`. |
| `GET` | `/sessions/{id}` | Agent's lookup on dispatch. Returns `{lesson_id, state_json}`. |
| `PUT` | `/sessions/{id}/state` | Agent PUTs after every state transition. Body: `{state_json}`. Idempotent — replays of the same state are safe. When `state_json.phase == "done"` the backend also sets `finished_at`. |

### Persistence (UserLesson + Session)

```python
class UserLesson:
    id, user_id, lesson_id, created_at
    UniqueConstraint(user_id, lesson_id)

class Session:
    id, user_lesson_id (FK)
    state_json (JSON: {idx, phase, last_gaps})
    started_at, last_active_at, finished_at
```

- **`user_lessons`**: one row per (user, lesson_id). The user's stable record
  of having engaged with a lesson.
- **`sessions`**: one row per attempt. Multiple in-progress sessions per
  UserLesson are allowed — clicking *Start* on the Available tile always
  inserts a new Session, leaving any prior in-progress sessions in the DB.
  The user explicitly chooses which to resume from the Continue tiles.

The agent's session lookup uses the **room name** as the join key —
`POST /sessions` mints rooms named `tutor-{session_id}-{uuid}`, the agent extracts
`session_id` from that and calls `GET /sessions/{id}`. No `room_name`
column is needed.

User identity is an anonymous UUID generated client-side and stored in
`localStorage`.

## Design decisions

**Pipelined STT/LLM/TTS, not Realtime.** We started with OpenAI Realtime
(speech-to-speech) for low latency, but it handles turn detection and
transcription server-side, which means livekit-agents'
`Agent.on_user_turn_completed` hook fires *without* the user's text —
making it impossible to grade and run the state machine deterministically.
Switching to pipelined Whisper + gpt-4o-mini + tts-1 + Silero VAD lets the
framework own turn boundaries; the hook fires with text and the loop
works. ~200ms more latency vs Realtime, significantly cheaper per minute.

**Static curated content via `session.say()`, not LLM-generated turns.**
After early experiments with LLM-driven teach/reteach prompts (which drift
into language-tutor mode, acknowledge prior turns, ramble), all agent
voice goes through `session.say(static_text)` which bypasses the LLM
entirely. The LLM is required by `AgentSession` but never invoked for
content; we raise `StopResponse` from every hook exit to suppress the
framework's auto-reply. Reviewer reads a string in `lesson.py`, hears that
string verbatim.

**Externalized grading.** Realtime models drift on multi-step prose
instructions. "If grade < N then reteach" works in testing and silently
fails in prod. So the grader is a separate gpt-4o-mini text completion
with `response_format: json_schema(strict)`. The OpenAI API itself
validates output shape; the grader cannot return malformed JSON. The
if-statement on the score is in Python where if-statements work.

**Per-transition state save.** Every `state.transition()` triggers an
HTTP POST to `/sessions/{id}/state`. This makes the lesson resumable
across browser refreshes, network drops, and server restarts — the
worst-case loss is the in-flight turn. No transcripts are persisted;
state_json is the only durable artifact.

**Multiple in-progress sessions per UserLesson.** A user who stops
mid-lesson and clicks Start fresh later will have *two* in-progress
sessions visible in Continue. They pick which to resume. No data is
destroyed on Start.

**SQLite for persistence.** Single file at `data/voice_tutor.db`, two
tables, no migrations framework. Postgres swap is one URL change.

**No auth.** Reviewers shouldn't have to sign up. JWT middleware on
`/sessions` is the drop-in for real multi-user.

## Scaling to 10k concurrent sessions

Two axes scale separately:

- **Token API (FastAPI)** is stateless and trivial to horizontally scale —
  put it behind any HTTP autoscaler (k8s HPA, ECS, Railway). 10k sessions
  doesn't mean 10k token-mints/sec; it's one call per session join plus
  one POST per turn for state save.
- **Agent worker pool**. Each worker handles N concurrent sessions
  (`WorkerOptions.num_idle_processes`). For 10k:
  - Run agents as a horizontally-scaled stateless Deployment, scaled on
    CPU + active-session count.
  - LiveKit Cloud handles SFU/TURN auto-scaling. Self-hosting would mean
    a LiveKit cluster + Redis + TURN.
  - Swap SQLite for Postgres + add Redis for hot session lookups.
  - Watch OpenAI rate limits — at this scale you'd negotiate higher
    quotas or pool across keys.
  - The Python state machine is per-job, stateless across workers, so no
    cross-worker coordination is needed.

State persistence makes a worker crash recoverable: the user just clicks
Resume on the Continue tile and a new worker hydrates from the DB.

## Project layout

```
.
├── backend/                          # FastAPI + SQLite
│   ├── app/
│   │   ├── main.py                   # /health, /lessons, /sessions/*
│   │   ├── db.py                     # UserLesson + Session models
│   │   ├── lesson_catalog.py         # title/blurb/concept_names mirror
│   │   └── livekit_token.py          # mint + room_name <→ session_id helpers
│   └── tests/                        # (currently stale; see Tests below)
├── agent/                            # livekit-agents worker
│   ├── agent.py                      # state-machine orchestration
│   ├── lesson.py                     # Lesson dataclass + LESSONS registry
│   ├── prompts.py                    # teach_text / reteach_text / closing_text
│   ├── grader.py                     # gpt-4o-mini grader
│   └── state_machine.py              # LessonState; serialization
├── frontend/                         # Vite + React + TS + Tailwind v4
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── hooks/useUserId.ts
│       ├── utils/time.ts
│       └── components/
│           ├── Home.tsx              # Continue + Available sections
│           └── VoicePanel.tsx        # in-session voice UI
├── data/                             # SQLite file (gitignored)
├── docker-compose.yml
├── .env.example
└── README.md
```

## Out of scope (deliberately)

These are explicitly parked. Each is a clear next step:

- **Curriculum content quality and breadth.** One fixture lesson with 4
  concepts. Production wants many more, expert-written, editorially reviewed.
- **Prompt tuning.** Every prompt (teach, reteach, grader) is first-cut.
  A real ship would A/B against held-out transcripts to tune wording, the
  grading threshold, and reteach behavior.
- **Tailored reteach via LLM.** Currently reteach re-reads the same teach
  text with a brief lead-in. The future version uses a `Reteacher` LLM
  call that takes `(concept, gaps_from_grader)` and produces a 2-3
  sentence explanation tailored to the user's specific misunderstanding.
  `state.last_gaps` is already populated; this is a one-function add.
- **Persisting grades.** `Grade` flows through Python in-session but isn't
  written to DB. The next step is a per-(session, concept) grades table
  for analytics and cross-session adaptation.
- **Cross-session adaptation.** Home doesn't show mastery across sessions;
  the agent doesn't get prior mastery in its instructions. State_json
  carries last_gaps within a session; persisting graded misconceptions
  across sessions unlocks "you struggled with X last time, let's start there."
- **Upper bound on reteach attempts.** Currently a user can stay on a
  concept indefinitely. Production would have escalation rules ("third
  miss → flag for review") and a user-facing skip option.
- **Curriculum as a DAG.** Current `LESSONS` is a flat dict. The natural
  next shape is a Curriculum — a DAG of Lessons with prereq edges. The
  state machine would walk the DAG: branch into sub-lessons on weak
  answers, skip ahead when prereqs are mastered, surface "you're ready
  for X next" affordances.
- **Auth.** Anonymous UUID in localStorage. JWT middleware on `/sessions`
  is the drop-in.

## Gotchas

- `LIVEKIT_URL` must start with `wss://`, not `https://`.
- Microphone permission requires `localhost` or HTTPS — testing via your
  LAN IP fails silently with no audio.
- Hot-reload (`agent.py dev`) doesn't re-join rooms that are already live;
  refresh the browser after agent code edits.
- The agent worker must be able to reach LiveKit Cloud over outbound
  WebSocket. If it boots and immediately exits, check `LIVEKIT_API_KEY`
  / `LIVEKIT_API_SECRET`.
- The grader is a separate API call (`gpt-4o-mini`) per user turn. It's
  fast (~500ms-1s) but adds a noticeable pause between you finishing
  speaking and the tutor's next turn.
- After clicking Disconnect or finishing a lesson, the Continue list
  isn't auto-refreshed on the next Home mount — refresh the browser to
  see the latest state. (The `/sessions` filter is correct; the UI just
  doesn't re-fetch on navigation.)

## Cheat code (for demos and testing)

Say **`"abracadabra"`** instead of an answer to skip the grader and
force-pass the current concept. Walks a fresh lesson from start to finish
in ~30 seconds. Logged distinctly in the agent (`[CHEAT] phrase=...`).
Configurable via `VOICE_TUTOR_CHEAT` env if you want a different word.

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

`backend/tests/test_health.py` covers the FastAPI surface end-to-end:
catalog, fresh start, resume, finished-session exclusion, cross-user
guard rails, multi-attempt invariants, state save round-trip, and the
room-name-encodes-session-id scheme. 18 tests, ~0.5s runtime, in-memory
SQLite per run.

The agent's state machine and grader don't have automated tests in this
build — both are pure functions (the state machine especially) and would
be straightforward to test, but loop fidelity is qualitative (does the
model actually speak the focused turn?) and depends on prompt quality
which is fixture/out-of-scope.

## TODO before submission

- [ ] **Spin up a dedicated LiveKit Cloud project for this take-home.**
  This scaffold currently reuses an existing personal LiveKit project for
  development. Before submitting, create a fresh project at
  <https://cloud.livekit.io>, generate new API key + secret, and update
  `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`.
