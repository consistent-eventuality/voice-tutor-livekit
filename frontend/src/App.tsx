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
  // Bump on each disconnect so Home knows to poll for the just-ended lesson
  // landing in the DB (agent's shutdown POST happens 1-3s after disconnect)
  const [pollKey, setPollKey] = useState(0)

  function endSession() {
    setView({ kind: 'home' })
    setPollKey((k) => k + 1)
  }

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
            pollKey={pollKey}
            onStartNew={() => setView({ kind: 'session', lessonId: null })}
            onResume={(lessonId) => setView({ kind: 'session', lessonId })}
          />
        ) : (
          <VoicePanel
            userId={userId}
            lessonId={view.lessonId}
            onLeave={endSession}
          />
        )}
      </div>
    </main>
  )
}
