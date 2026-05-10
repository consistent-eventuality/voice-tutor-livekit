const API_BASE = import.meta.env.DEV
  ? '/api'
  : (import.meta.env.VITE_API_URL ?? '')

export interface TokenPayload {
  token: string
  url: string
  room_name: string
  identity: string
  session_id: number
  lesson_id: string
  resuming: boolean
}

export interface LessonCatalogItem {
  id: string
  title: string
  blurb: string
  concept_count: number
}

export interface InProgressSession {
  session_id: number
  lesson_id: string
  lesson_title: string
  concept_count: number
  idx: number
  phase: string
  current_concept_name: string | null
  started_at: string
  last_active_at: string
}

export async function fetchToken(opts: {
  userId: string
  lessonId?: string | null
  sessionId?: number | null
  participantName?: string
}): Promise<TokenPayload> {
  const res = await fetch(`${API_BASE}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: opts.userId,
      lesson_id: opts.lessonId ?? null,
      session_id: opts.sessionId ?? null,
      participant_name: opts.participantName ?? null,
    }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`Token request failed: ${res.status} ${text}`)
  }
  return res.json()
}

export async function listLessonCatalog(): Promise<LessonCatalogItem[]> {
  const res = await fetch(`${API_BASE}/lessons`)
  if (!res.ok) {
    throw new Error(`Listing lessons failed: ${res.status}`)
  }
  return res.json()
}

export async function listInProgressSessions(userId: string): Promise<InProgressSession[]> {
  const res = await fetch(`${API_BASE}/sessions?user_id=${encodeURIComponent(userId)}`)
  if (!res.ok) {
    throw new Error(`Listing sessions failed: ${res.status}`)
  }
  return res.json()
}
