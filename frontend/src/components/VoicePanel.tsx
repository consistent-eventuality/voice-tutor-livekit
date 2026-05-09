import { useEffect, useState } from 'react'
import {
  BarVisualizer,
  LiveKitRoom,
  RoomAudioRenderer,
  VoiceAssistantControlBar,
  useVoiceAssistant,
} from '@livekit/components-react'
import { fetchToken, type TokenPayload } from '../api'

interface VoicePanelProps {
  userId: string
  lessonId: number | null      // null = start a new lesson
  onLeave: () => void
}

export function VoicePanel({ userId, lessonId, onLeave }: VoicePanelProps) {
  const [payload, setPayload] = useState<TokenPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchToken({ userId, lessonId })
      .then((p) => {
        if (!cancelled) setPayload(p)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [userId, lessonId])

  if (error) {
    return (
      <div className="rounded-xl bg-[color:var(--color-surface)] p-8 text-center">
        <p className="text-sm text-red-400 break-words">{error}</p>
        <button
          onClick={onLeave}
          className="mt-4 text-xs text-[color:var(--color-muted)] hover:text-white"
        >
          Back
        </button>
      </div>
    )
  }

  if (!payload) {
    return (
      <div className="rounded-xl bg-[color:var(--color-surface)] p-8 text-center">
        <p className="text-sm text-[color:var(--color-muted)]">Connecting…</p>
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
      onDisconnected={onLeave}
      className="rounded-xl bg-[color:var(--color-surface)] p-6"
    >
      <RoomAudioRenderer />
      <ActiveSession resuming={payload.resuming} />
    </LiveKitRoom>
  )
}

function ActiveSession({ resuming }: { resuming: boolean }) {
  const { state, audioTrack } = useVoiceAssistant()

  return (
    <div className="flex flex-col items-center gap-6">
      {resuming && (
        <p className="text-xs text-[color:var(--color-muted)]">
          Resuming previous lesson…
        </p>
      )}
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
    </div>
  )
}
