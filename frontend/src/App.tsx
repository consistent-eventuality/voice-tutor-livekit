import { VoicePanel } from './components/VoicePanel'

export function App() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-6">
      <div className="max-w-xl w-full">
        <header className="mb-8 text-center">
          <h1 className="text-3xl font-semibold tracking-tight">Voice Tutor</h1>
          <p className="text-sm text-[color:var(--color-muted)] mt-2">
            Real-time voice AI tutor — talk to it, it talks back.
          </p>
        </header>
        <VoicePanel />
      </div>
    </main>
  )
}
