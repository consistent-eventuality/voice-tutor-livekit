import { useState } from 'react'
import { Home } from './components/Home'
import { VoicePanel } from './components/VoicePanel'
import { useUserId } from './hooks/useUserId'

type View =
  | { kind: 'home' }
  | { kind: 'session'; lessonId: number | null }

export function App() {
  const userId = useUserId()
  const [view, setView] = useState<View>({ kind: 'home' })

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-6">
      <div className="max-w-xl w-full">
        <header className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">Voice Tutor</h1>
          <p className="text-sm text-[color:var(--color-muted)] mt-2">
            Real-time voice AI tutor — talk to it, it talks back.
          </p>
        </header>

        {view.kind === 'home' ? (
          <Home
            userId={userId}
            onStartNew={() => setView({ kind: 'session', lessonId: null })}
            onResume={(lessonId) => setView({ kind: 'session', lessonId })}
          />
        ) : (
          <VoicePanel
            userId={userId}
            lessonId={view.lessonId}
            onLeave={() => setView({ kind: 'home' })}
          />
        )}
      </div>
    </main>
  )
}
