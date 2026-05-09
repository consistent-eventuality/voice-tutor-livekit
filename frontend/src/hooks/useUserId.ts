import { useState } from 'react'

const KEY = 'voice-tutor-user-id'

export function useUserId(): string {
  const [id] = useState<string>(() => {
    const existing = localStorage.getItem(KEY)
    if (existing) return existing
    const fresh = crypto.randomUUID()
    localStorage.setItem(KEY, fresh)
    return fresh
  })
  return id
}
