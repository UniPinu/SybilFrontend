import { useEffect, useRef, useState } from 'react'

/** The stages the backend emits, in the order they happen (MVP.md 6.3). */
export const STAGES = [
  'queued',
  'downloading',
  'reading',
  'standardizing',
  'model',
  'calibrating',
  'rendering',
  'done',
] as const

export type StageName = (typeof STAGES)[number] | 'error' | 'ping'

export type JobEvent = {
  stage: StageName
  text?: string
  at?: string
  position?: number
  bytes_done?: number
  bytes_total?: number
  n_slices?: number
  index?: number
  of?: number
  message?: string
  cached?: boolean
  seconds?: number
}

export type JobState = {
  stage: StageName | null
  events: JobEvent[]
  expertsDone: number
  bytesDone: number
  bytesTotal: number
  nSlices: number | null
  queuePosition: number | null
  error: string | null
  finished: boolean
  elapsed: number
}

const EMPTY: JobState = {
  stage: null,
  events: [],
  expertsDone: 0,
  bytesDone: 0,
  bytesTotal: 0,
  nSlices: null,
  queuePosition: null,
  error: null,
  finished: false,
  elapsed: 0,
}

/** Subscribe to one job's SSE stream. Returns a reduced view for the stepper. */
export function useJobEvents(jobId: string | null): JobState {
  const [state, setState] = useState<JobState>(EMPTY)
  const startedAt = useRef<number>(0)

  useEffect(() => {
    if (!jobId) {
      setState(EMPTY)
      return
    }
    setState({ ...EMPTY, stage: 'queued' })
    startedAt.current = performance.now()

    const source = new EventSource(`/api/jobs/${jobId}/events`)
    const tick = window.setInterval(() => {
      setState((prev) =>
        prev.finished ? prev : { ...prev, elapsed: (performance.now() - startedAt.current) / 1000 },
      )
    }, 250)

    const handle = (stage: StageName) => (message: MessageEvent<string>) => {
      let payload: JobEvent
      try {
        payload = { ...(JSON.parse(message.data) as JobEvent), stage }
      } catch {
        payload = { stage }
      }
      if (stage === 'ping') return
      setState((prev) => {
        const next: JobState = {
          ...prev,
          stage,
          events: [...prev.events, payload],
          elapsed: (performance.now() - startedAt.current) / 1000,
        }
        if (stage === 'queued') next.queuePosition = payload.position ?? null
        if (stage === 'downloading') {
          next.bytesDone = payload.bytes_done ?? prev.bytesDone
          next.bytesTotal = payload.bytes_total ?? prev.bytesTotal
        }
        if (stage === 'reading') next.nSlices = payload.n_slices ?? null
        if (stage === 'model') next.expertsDone = payload.index ?? prev.expertsDone
        if (stage === 'calibrating') next.expertsDone = 5
        if (stage === 'done') next.finished = true
        if (stage === 'error') {
          next.error = payload.message ?? 'Something went wrong.'
          next.finished = true
        }
        return next
      })
      if (stage === 'done' || stage === 'error') source.close()
    }

    const names: StageName[] = [...STAGES, 'error', 'ping']
    for (const name of names) source.addEventListener(name, handle(name) as EventListener)
    source.onerror = () => {
      // The stream closes itself after `done`; only surface a real failure.
      setState((prev) =>
        prev.finished ? prev : { ...prev, error: 'Lost the connection to the server.', finished: true },
      )
      source.close()
    }

    return () => {
      window.clearInterval(tick)
      source.close()
    }
  }, [jobId])

  return state
}
