import { useEffect, useState } from 'react'
import { listLessons, type LessonListItem } from '../api'
import { timeAgo } from '../utils/time'

interface HomeProps {
  userId: string
  pollKey: number  // bumped after a session ends → triggers brief polling
  onStartNew: () => void
  onResume: (lessonId: number) => void
}

export function Home({ userId, pollKey, onStartNew, onResume }: HomeProps) {
  const [lessons, setLessons] = useState<LessonListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchOnce() {
      try {
        const items = await listLessons(userId)
        if (!cancelled) setLessons(items)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchOnce()

    // Poll briefly after each disconnect to catch the agent's /sessions/end
    // POST landing in the DB. Skipped on the very first mount (pollKey === 0).
    if (pollKey === 0) {
      return () => {
        cancelled = true
      }
    }

    const interval = setInterval(fetchOnce, 1000)
    const stop = setTimeout(() => clearInterval(interval), 6000)
    return () => {
      cancelled = true
      clearInterval(interval)
      clearTimeout(stop)
    }
  }, [userId, pollKey])

  return (
    <div className="rounded-xl bg-[color:var(--color-surface)] p-8">
      <button
        onClick={onStartNew}
        className="w-full px-6 py-3 rounded-lg bg-[color:var(--color-accent)] text-white font-medium"
      >
        Start new lesson
      </button>

      {error && (
        <p className="mt-4 text-sm text-red-400 break-words">{error}</p>
      )}

      {lessons.length > 0 && (
        <>
          <h2 className="mt-8 mb-3 text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
            Past lessons
          </h2>
          <ul className="flex flex-col gap-2">
            {lessons.map((lesson) => (
              <li key={lesson.id}>
                <button
                  onClick={() => onResume(lesson.id)}
                  className="w-full text-left px-4 py-3 rounded-lg border border-white/10 hover:border-[color:var(--color-accent)] hover:bg-white/5 transition"
                >
                  <span className="text-[color:var(--color-muted)]">
                    {timeAgo(lesson.last_session_at)}
                  </span>
                  <span className="text-[color:var(--color-muted)] mx-2">·</span>
                  <span>{lesson.topic}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {!loading && lessons.length === 0 && !error && (
        <p className="mt-8 text-center text-xs text-[color:var(--color-muted)]">
          No past lessons yet.
        </p>
      )}
    </div>
  )
}
