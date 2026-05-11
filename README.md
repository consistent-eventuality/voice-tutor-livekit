## Product Overview

For the voice tutor I had two goals:

- voice is not a gimmick
- a curriculum and workflow that adds value over voice mode in horizontal apps like ChatGPT.

Research on what use cases work well for voice tutoring uncovered these insights:

- Voice works best for skills where deliberate practice matters but people avoid doing the reps.
- Voice is strongest when learners must produce understanding, not just consume information.
- The real value comes from adaptive learning loops, not just voice-enabled conversation.
- Strong tutors hide structured curriculum and progression underneath natural conversation.

So I picked technical interview prep — all three preconditions are present:
reps matter, people procrastinate on doing them, and verbal explanation
surfaces gaps that silent reading doesn't. The framework extends to any
subject that fits voice AI well; the loop machinery is the part that
generalizes.

## Curriculum, Lesson and Concept

```
Curriculum  =  DAG of Lessons (out of scope)
Lesson      =  ordered list of Concepts  (built 2 lessons)
Concept     =  the loop primitive (TEACH → GRADE → RETEACH?)   
```
The Concept tutoring loop is what makes this not a wrapper around ChatGPT-with-voice.

The loop, at a glance:

```
TEACH  →  USER PRACTICE  →  EVALUATE  →  RETEACH OR PROGRESS
```

 The agent's voice never goes through an LLM — all spoken content is curated.

| Concern | Realized as |
|---|---|
| **Voice Tutoring** | `AgentSession.say(static_text)` — bypasses the LLM. Content comes verbatim from `agent/lesson.py`. |
| **Transcribe the user's answer** | OpenAI Whisper (streaming STT plugin) |
| **Grade the answer** | A separate `gpt-4o-mini` text completion with `response_format` JSON-schema enforcement. The **only** LLM call in the runtime path. |
| **Decide next action** | Python code . Pass → advance. Fail → reteach. |

 ### Bonus features delivered

- **Session resumability.** Disconnect mid-lesson and the session shows
  up under **Resume in progress** on the home screen — click it and you
  pick up from the same concept on a fresh agent worker.
- **Connection-drop recovery.** Same mechanism covers network blips,
  browser refreshes, and worker crashes. Worst-case loss is the in-flight
  turn.
- **Post-session summary** — not built. Design sketch below
  ([Post-session summary (design sketch)](#post-session-summary-design-sketch)).

### Tip: skip the grader

Say **`"abracadabra"`** instead of an answer to skip the grader and force-pass
the current concept. Walks a fresh lesson start-to-finish in ~30 seconds.
Configurable via `VOICE_TUTOR_CHEAT` env if you want a different phrase.

## Quickstart

```bash
cp .env.example .env   # then fill in 4 keys (see below)
docker compose up --build
```

Open <http://localhost:5173> (use `localhost` or HTTPS — browsers block mic
access over plain HTTP and LAN IPs), click any lesson under **Available**,
allow microphone access, and start talking.

> **Expect short pauses.** The tutor takes ~1–2s to start speaking after you
> join (agent dispatch + first TTS), and ~500ms–1s after each of your turns
> while the grader runs as a separate `gpt-4o-mini` call. Those pauses are
> the loop running, not the app being stuck.

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

## Out of scope

- **Polished frontend.** The frontend was AI-generated end-to-end so engineering effort could concentrate on the loop machinery.
- **Clarify phase.** A voice tutor should let the user ask questions. A `clarify` phase + a separate `Clarifier` LLM call slots into the state machine alongside `teach` / `reteach`.
- **Speech-skill detection and coaching.** Pronunciation, accent, words per minute, speaking style. Not in scope here; possible against the same STT stream.
- **Curriculum content quality and breadth.** Two very basic "lessons" with static content. Quality of the teaching content is a non goal. 
- **Prompt tuning.** Production would A/B against transcripts to tune wording, the grading threshold, and reteach behavior.
- **Tailored reteach via LLM.** Reteach currently re-reads the same teach text with a brief lead-in. The future version uses a `Reteacher` LLM call that takes `(concept, gaps_from_grader)` and produces a 2–3 sentence explanation tailored to the user's specific misunderstanding. `state.last_gaps` is already populated; this is a one-function add.
- **Persisting grades.** `Grade` flows through Python in-session but isn't written to DB. A per-(session, concept) grades table unlocks analytics and cross-session adaptation.
- **Cross-session learning progression.** Home doesn't show mastery, streaks, or prior-misconception flags. Persisting graded misconceptions across sessions unlocks "you struggled with X last time, let's start there."
- **Upper bound on reteach attempts.** A user can stay on a concept indefinitely. Production would have escalation rules ("third miss → flag for review") and a user-facing skip option.
- **Curriculum as a DAG.** Current `LESSONS` is a flat dict. The natural next shape is a Curriculum — a DAG of Lessons with prereq edges. The state machine would walk the DAG: branch into sub-lessons on weak answers, skip ahead when prereqs are mastered, surface "you're ready for X next" affordances.
- **Voice-chat performance tuning.** Turn-detection thresholds, VAD sensitivity, TTS streaming latency — all left at framework defaults.
- **Auth.** Anonymous UUID in localStorage. JWT middleware on `/sessions` is the drop-in.
- **Exhaustive testing.** I tested the happy path and the main negative path (user fails the grader); edgecases not exhaustively tested. Did not focus on test coverage and only on getting the core loop to work.

---

## Architecture

```
┌─────────┐ POST /sessions ┌──────────────────┐
│ Browser │───────────────▶│ FastAPI (api)    │  sessions + state_json
│ (React) │◀───────────────│ port 8000        │  state_json (resumption)
└────┬────┘                └──────────────────┘
     │                              ▲
     │ WebRTC connect               │  PUT /sessions/{id}/state
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
  sessions + state_json, serves the agent's lookup endpoint.
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
  │  PUT /sessions/{id}/state            │                 │
  │  Persists state_json so a reconnect  │                 │
  │  can pick up here.                   │                 │
  └──────────┬───────────────────────────┘                 │
             │                                             │
             └─────────────────────────────────────────────┘
                              loop until phase = done
```

States: `teach` → `reteach` (on fail, loops to itself) → `done`. The
`teach`/`reteach` distinction is purely about spoken wording — the re-teach
prompt has a brief lead-in ("Let me walk through that one more time"). When
`phase = done`, the agent speaks the lesson's `closing` line and shuts down
on the `speaking → listening` transition.

The five agent files that implement this:

| File | Job |
|---|---|
| `agent/lesson.py` | `Concept`, `Lesson`, and the `LESSONS` registry. Pure data. |
| `agent/prompts.py` | `teach_text()`, `reteach_text()`, `closing_text()`. Format spoken text. No LLM prompts. |
| `agent/grader.py` | `Grader.grade()` — gpt-4o-mini with JSON-schema response_format. |
| `agent/state_machine.py` | `LessonState` — pure Python, deterministic transitions, `to_dict` / `from_dict` for serialization. |
| `agent/agent.py` | Wires it together. On dispatch: parse session_id from room name, fetch state, hydrate, run loop. On every transition: persist state. On final concept passed: speak closing, auto-disconnect. |

## Persistence

```python
class Session:
    id, user_id, lesson_id
    state_json (JSON: {idx, phase, last_gaps})
    started_at, last_active_at, finished_at
```

One table. Each row is one attempt at a lesson by a user. Multiple in-progress
sessions per `(user_id, lesson_id)` are allowed — clicking *Start* always
inserts a new row, leaving prior in-progress sessions alone. The user
explicitly chooses which to resume from the Continue tiles.

`user_id` and `lesson_id` are denormalized onto each session row. There's no
separate `user_lessons` parent table — there was nothing per-(user, lesson) to
attach to it. Add if cross-session features land later (mastery, preferences, total time-on-lesson).

The agent's session lookup uses the **room name** as the join key —
`POST /sessions` mints rooms named `tutor-{session_id}-{uuid}`, the agent
extracts `session_id` from that and calls `GET /sessions/{id}`. No
`room_name` column is needed.

User identity is an anonymous UUID generated client-side and stored in
`localStorage`.

## Design decisions

**Pipelined STT/LLM/TTS, not Realtime.** We started with OpenAI Realtime
(speech-to-speech) for low latency, but it handles turn detection and
transcription server-side, which means livekit-agents'
`Agent.on_user_turn_completed` hook fires *without* the user's text — making
it impossible to grade and run the state machine deterministically. Switching
to pipelined Whisper + gpt-4o-mini + tts-1 + Silero VAD lets the framework
own turn boundaries; the hook fires with text and the loop works. ~200ms more
latency vs Realtime, significantly cheaper per minute.

**Static curated content via `session.say()`, not LLM-generated turns.** Early
experiments with LLM-driven teach/reteach prompts drifted into language-tutor
mode, acknowledged prior turns, and rambled. So all agent voice now goes
through `session.say(static_text)`, which bypasses the LLM entirely. The LLM
is required by `AgentSession` but never invoked for content; we raise
`StopResponse` from every hook exit to suppress the framework's auto-reply.
A reviewer reads a string in `lesson.py` and hears that string verbatim.

**Externalized grading.** LLMs drift on multi-step prose instructions. "If
grade < N then reteach" cannot be deterministically guaranteed in a prompt. So the
grader is a separate gpt-4o-mini text completion with `response_format:
json_schema(strict)`. The OpenAI API itself validates output shape; the
grader cannot return malformed JSON. Logical branching happens in Python.
**Intelligence concentrated to grading i.e. feedback on user speech**.

**Per-transition state save.** Every `state.transition()` triggers a PUT to
`/sessions/{id}/state`. This makes the lesson resumable across browser
refreshes, network drops, and server restarts — worst-case loss is the
in-flight turn. No transcripts are persisted; state_json is the only durable
artifact.

**Multiple in-progress sessions per (user, lesson).** A user who stops
mid-lesson and clicks Start fresh later will have *two* in-progress sessions
visible in Continue. They pick which to resume. No data is destroyed on
Start.

**SQLite for persistence.** Single file at `data/voice_tutor.db`, one table,
no migrations framework. Postgres swap is one URL change.

**No auth.** Reviewers shouldn't have to sign up. JWT middleware on
`/sessions` is the drop-in for real multi-user.

## Post-session summary (design sketch)

Not built, but the agent already produces the two inputs a real summary
needs:

1. **Transcript** — capture every `session.say(...)` and
   `on_user_turn_completed(text)` into a `transcript_json` column on
   `sessions`, written per turn alongside `state_json`.
2. **Gaps** — accumulate per-concept gaps from the grader's existing
   `Grade(score, gaps)` output into `state_json.gaps_by_concept`
   (no schema change — rides on the existing JSON blob).

On `phase == "done"`, one LLM call with both inputs and a strict
`response_format` JSON schema produces `{covered, struggled, next_focus}`.
Persist to a `summary_json` column. Surface on Home → **Recently
completed**. Estimated build: ~30 min, no new infra.

## Scaling to 10k concurrent sessions

Two axes scale separately:

- **Token API (FastAPI)** is stateless and trivial to horizontally scale —
  put it behind any HTTP autoscaler (k8s HPA, ECS, Railway). 10k sessions
  doesn't mean 10k token-mints/sec; it's one call per session join plus one
  PUT per turn for state save.
- **Agent worker pool.** Each worker handles N concurrent sessions
  (`WorkerOptions.num_idle_processes`). For 10k:
  - Run agents as a horizontally-scaled stateless Deployment, scaled on
    CPU + active-session count.
  - LiveKit Cloud handles SFU/TURN auto-scaling. Self-hosting would mean a
    LiveKit cluster + Redis + TURN.
  - Swap SQLite for Postgres + add Redis for hot session lookups.
  - Watch OpenAI rate limits — at this scale you'd negotiate higher quotas
    or pool across keys.
  - The Python state machine is per-job, stateless across workers, so no
    cross-worker coordination is needed.

State persistence makes a worker crash recoverable: the user just clicks
Resume on the Continue tile and a new worker hydrates from the DB.

## Project layout

Build/config plumbing (`Dockerfile`s, `requirements.txt`, `tsconfig*.json`, etc.) omitted.

```
.
├── backend/                       # FastAPI + SQLite — token mint, session persistence
│   └── app/
│       ├── main.py                # /health, /lessons, /sessions/*
│       ├── db.py                  # Session model (single table)
│       ├── lesson_catalog.py      # backend-side mirror of agent/lesson.py metadata
│       └── livekit_token.py       # mint + room_name <→ session_id helpers
├── agent/                         # livekit-agents worker — the loop runs here
│   ├── agent.py                   # orchestration; on_user_turn_completed hook
│   ├── state_machine.py           # LessonState — pure Python, deterministic
│   ├── grader.py                  # gpt-4o-mini grader (the only LLM call)
│   ├── lesson.py                  # Lesson + LESSONS registry (curated content)
│   └── prompts.py                 # teach_text / reteach_text / closing_text
├── frontend/                      # Vite + React + Tailwind v4
│   └── src/
│       ├── App.tsx                # view router (home ↔ session)
│       ├── api.ts                 # /sessions, /lessons fetchers + types
│       └── components/
│           ├── Home.tsx           # Continue + Available sections
│           └── VoicePanel.tsx     # in-session voice UI
└── docker-compose.yml
```

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

`backend/tests/test_health.py` covers the FastAPI surface end-to-end: catalog,
fresh start, resume, finished-session exclusion, cross-user guard rails,
multi-attempt invariants, state save round-trip, and the
room-name-encodes-session-id scheme. 18 tests, ~0.5s runtime, in-memory
SQLite per run.

The agent's state machine and grader don't have automated tests in this
build — both are pure functions (the state machine especially) and would be
straightforward to test, but loop fidelity is qualitative (does the model
actually speak the focused turn?) and depends on prompt quality, which is
fixture/out-of-scope.
