import { useEffect, useState } from 'react'
import {
  listInProgressSessions,
  listLessonCatalog,
  type InProgressSession,
  type LessonCatalogItem,
} from '../api'
import { timeAgo } from '../utils/time'

interface HomeProps {
  userId: string
  onStartLesson: (lessonId: string) => void
  onResumeSession: (sessionId: number) => void
}

export function Home({ userId, onStartLesson, onResumeSession }: HomeProps) {
  const [catalog, setCatalog] = useState<LessonCatalogItem[]>([])
  const [sessions, setSessions] = useState<InProgressSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([listLessonCatalog(), listInProgressSessions(userId)])
      .then(([cat, sess]) => {
        if (cancelled) return
        setCatalog(cat)
        setSessions(sess)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  if (loading) {
    return (
      <div className="rounded-xl bg-[color:var(--color-surface)] p-8 text-center">
        <p className="text-sm text-[color:var(--color-muted)]">Loading…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl bg-[color:var(--color-surface)] p-8 text-center">
        <p className="text-sm text-red-400 break-words">{error}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-8">
      {/* Available lessons — primary action, prominent cards */}
      <section>
        <h2 className="mb-3 text-sm font-medium text-[color:var(--color-text)]">
          Lessons
        </h2>
        <ul className="flex flex-col gap-3">
          {catalog.map((lesson) => (
            <li key={lesson.id}>
              <button
                onClick={() => onStartLesson(lesson.id)}
                className="group w-full text-left px-5 py-4 rounded-xl border-2 border-[color:var(--color-accent)]/40 bg-[color:var(--color-accent)]/5 hover:border-[color:var(--color-accent)] hover:bg-[color:var(--color-accent)]/15 transition"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="text-base font-semibold">
                      {lesson.title}
                    </div>
                    <div className="text-sm text-[color:var(--color-muted)] mt-1">
                      {lesson.blurb}
                    </div>
                    <div className="text-xs text-[color:var(--color-muted)] mt-2">
                      {lesson.concept_count} concepts
                    </div>
                  </div>
                  <div className="text-[color:var(--color-accent)] text-xl group-hover:translate-x-0.5 transition-transform">
                    →
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
        {catalog.length === 0 && (
          <p className="text-center text-xs text-[color:var(--color-muted)]">
            No lessons available.
          </p>
        )}
      </section>

      {/* In-progress sessions — secondary, compact list */}
      {sessions.length > 0 && (
        <section>
          <h2 className="mb-2 text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
            Resume in progress
          </h2>
          <ul className="flex flex-col gap-1">
            {sessions.map((s) => (
              <li key={s.session_id}>
                <button
                  onClick={() => onResumeSession(s.session_id)}
                  className="w-full text-left px-3 py-2 rounded-md hover:bg-white/5 transition flex items-baseline justify-between gap-3"
                >
                  <span className="text-sm">
                    <span className="text-[color:var(--color-text)]">
                      {s.lesson_title}
                    </span>
                    {s.current_concept_name && (
                      <span className="text-[color:var(--color-muted)]">
                        {' · '}
                        {s.current_concept_name}
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-[color:var(--color-muted)] shrink-0">
                    {timeAgo(s.last_active_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
