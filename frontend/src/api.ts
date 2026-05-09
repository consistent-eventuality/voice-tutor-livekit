const API_BASE = import.meta.env.DEV
  ? '/api'
  : (import.meta.env.VITE_API_URL ?? '')

export interface TokenPayload {
  token: string
  url: string
  room_name: string
  identity: string
}

export async function fetchToken(opts: { participantName?: string } = {}): Promise<TokenPayload> {
  const res = await fetch(`${API_BASE}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participant_name: opts.participantName ?? null }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`Token request failed: ${res.status} ${text}`)
  }
  return res.json()
}
