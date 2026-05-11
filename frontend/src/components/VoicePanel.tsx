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
  lessonId: string | null    // for fresh starts (Available tile)
  sessionId: number | null   // for resumes (Continue tile)
  lessonTitle: string        // for display in the voice panel header
  onLeave: () => void
}

export function VoicePanel({
  userId,
  lessonId,
  sessionId,
  lessonTitle,
  onLeave,
}: VoicePanelProps) {
  const [payload, setPayload] = useState<TokenPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchToken({ userId, lessonId, sessionId })
      .then((p) => {
        if (!cancelled) setPayload(p)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [userId, lessonId, sessionId])

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
      <ActiveSession lessonTitle={lessonTitle} resuming={payload.resuming} />
    </LiveKitRoom>
  )
}

function ActiveSession({
  lessonTitle,
  resuming,
}: {
  lessonTitle: string
  resuming: boolean
}) {
  const { state, audioTrack } = useVoiceAssistant()

  return (
    <div className="flex flex-col items-center gap-6">
      <div className="text-center">
        <div className="text-sm font-semibold text-[color:var(--color-text)]">
          {lessonTitle}
        </div>
        {resuming && (
          <div className="text-xs text-[color:var(--color-muted)] mt-1">
            Resuming…
          </div>
        )}
      </div>
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
