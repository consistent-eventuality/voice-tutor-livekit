const API_BASE = import.meta.env.DEV
  ? '/api'
  : (import.meta.env.VITE_API_URL ?? '')

export interface TokenPayload {
  token: string
  url: string
  room_name: string
  identity: string
  lesson_id: number
  session_id: number
  resuming: boolean
}

export interface LessonListItem {
  id: number
  topic: string
  created_at: string
  last_session_at: string
  session_count: number
}

export async function fetchToken(opts: {
  userId: string
  lessonId?: number | null
  participantName?: string
}): Promise<TokenPayload> {
  const res = await fetch(`${API_BASE}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: opts.userId,
      lesson_id: opts.lessonId ?? null,
      participant_name: opts.participantName ?? null,
    }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`Token request failed: ${res.status} ${text}`)
  }
  return res.json()
}

export async function listLessons(userId: string): Promise<LessonListItem[]> {
  const res = await fetch(`${API_BASE}/lessons?user_id=${encodeURIComponent(userId)}`)
  if (!res.ok) {
    throw new Error(`Listing lessons failed: ${res.status}`)
  }
  return res.json()
}
