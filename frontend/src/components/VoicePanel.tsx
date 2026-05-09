import { useState } from 'react'
import {
  BarVisualizer,
  LiveKitRoom,
  RoomAudioRenderer,
  VoiceAssistantControlBar,
  useVoiceAssistant,
} from '@livekit/components-react'
import { fetchToken, type TokenPayload } from '../api'

export function VoicePanel() {
  const [payload, setPayload] = useState<TokenPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setLoading(true)
    setError(null)
    try {
      const token = await fetchToken()
      setPayload(token)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  function disconnect() {
    setPayload(null)
  }

  if (!payload) {
    return (
      <div className="rounded-xl bg-[color:var(--color-surface)] p-8 text-center">
        <button
          onClick={start}
          disabled={loading}
          className="px-6 py-3 rounded-lg bg-[color:var(--color-accent)] text-white font-medium disabled:opacity-50"
        >
          {loading ? 'Connecting…' : 'Start session'}
        </button>
        {error && (
          <p className="mt-4 text-sm text-red-400 break-words">{error}</p>
        )}
        <p className="mt-6 text-xs text-[color:var(--color-muted)]">
          You'll be asked for microphone permission.
        </p>
      </div>
    )
  }

  return (
    <LiveKitRoom
      token={payload.token}
      serverUrl={payload.url}
      connect
      audio
      video={false}
      onDisconnected={disconnect}
      className="rounded-xl bg-[color:var(--color-surface)] p-6"
    >
      <RoomAudioRenderer />
      <ActiveSession onLeave={disconnect} />
    </LiveKitRoom>
  )
}

function ActiveSession({ onLeave }: { onLeave: () => void }) {
  const { state, audioTrack } = useVoiceAssistant()

  return (
    <div className="flex flex-col items-center gap-6">
      <div className="h-32 w-full flex items-center justify-center">
        <BarVisualizer
          state={state}
          barCount={5}
          trackRef={audioTrack}
          className="h-full"
        />
      </div>
      <p className="text-sm text-[color:var(--color-muted)] capitalize">
        {state}
      </p>
      <VoiceAssistantControlBar />
      <button
        onClick={onLeave}
        className="text-xs text-[color:var(--color-muted)] hover:text-white"
      >
        End session
      </button>
    </div>
  )
}
