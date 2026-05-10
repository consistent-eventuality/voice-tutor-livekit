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
    <div className="flex flex-col gap-6">
      {sessions.length > 0 && (
        <section>
          <h2 className="mb-3 text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
            Continue where you left off
          </h2>
          <ul className="flex flex-col gap-2">
            {sessions.map((s) => (
              <li key={s.session_id}>
                <button
                  onClick={() => onResumeSession(s.session_id)}
                  className="w-full text-left px-4 py-3 rounded-lg border border-white/10 hover:border-[color:var(--color-accent)] hover:bg-white/5 transition"
                >
                  <div className="font-medium">{s.lesson_title}</div>
                  <div className="text-xs text-[color:var(--color-muted)] mt-1">
                    {s.current_concept_name
                      ? `On ${s.current_concept_name} · ${s.idx + 1} of ${s.concept_count}`
                      : 'Completed'}{' '}
                    · {phaseLabel(s.phase)} · {timeAgo(s.last_active_at)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
          Available lessons
        </h2>
        <ul className="flex flex-col gap-2">
          {catalog.map((lesson) => (
            <li key={lesson.id}>
              <button
                onClick={() => onStartLesson(lesson.id)}
                className="w-full text-left px-4 py-3 rounded-lg border border-white/10 hover:border-[color:var(--color-accent)] hover:bg-white/5 transition"
              >
                <div className="font-medium">{lesson.title}</div>
                <div className="text-xs text-[color:var(--color-muted)] mt-1">
                  {lesson.blurb}
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
    </div>
  )
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case 'teach':
      return 'in progress'
    case 'reteach':
      return 'reteaching'
    case 'done':
      return 'completed'
    default:
      return phase
  }
}
