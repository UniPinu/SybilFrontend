import { HomeNotices } from '@/components/Hero'
import { ResearchBody, ResearchHero } from '@/components/research/ResearchSection'
import { PersonSection } from '@/components/PersonSection'
import { PredictionSection } from '@/components/PredictionSection'
import { RevealSection } from '@/components/RevealSection'
import { RunSection, type RunPhase } from '@/components/RunSection'
import { ScanViewer } from '@/components/ScanViewer'
import { Scoreboard } from '@/components/Scoreboard'
import { SiteFooter } from '@/components/SiteFooter'
import { useJobEvents, type JobState, type StageName } from '@/hooks/useJobEvents'
import { api, ApiError, READ_ONLY, type Outcome } from '@/lib/api'
import { goTo, setParams } from '@/lib/url'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

/** Cached people are already computed, so there is nothing to wait for. We still
 *  walk the stepper once, clearly labelled as a replay, so the story is the same
 *  one a live run tells. */
const REPLAY: { stage: StageName; after: number }[] = [
  { stage: 'reading', after: 250 },
  { stage: 'standardizing', after: 550 },
  { stage: 'model', after: 850 },
  { stage: 'model', after: 1150 },
  { stage: 'model', after: 1450 },
  { stage: 'model', after: 1750 },
  { stage: 'model', after: 2050 },
  { stage: 'calibrating', after: 2350 },
  { stage: 'rendering', after: 2550 },
  { stage: 'done', after: 2750 },
]

const EMPTY_JOB: JobState = {
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

function patientFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('p')
}

export function StoryView() {
  const queryClient = useQueryClient()
  const [patientId, setPatientId] = useState<string | null>(patientFromUrl)
  const [liveMode, setLiveMode] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [replay, setReplay] = useState<JobState | null>(null)
  const [showResult, setShowResult] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const timers = useRef<number[]>([])

  const liveJob = useJobEvents(jobId)
  const job = replay ?? liveJob
  const cachedReplay = replay !== null

  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 20_000 })
  const person = useQuery({
    queryKey: ['patient', patientId],
    queryFn: () => api.patient(patientId!),
    enabled: !!patientId,
  })
  const result = useQuery({
    queryKey: ['result', patientId],
    queryFn: () => api.result(patientId!),
    enabled: !!patientId && showResult,
    retry: false,
  })
  const cohort = useQuery({ queryKey: ['cohort'], queryFn: api.cohort })

  const clearTimers = useCallback(() => {
    timers.current.forEach(window.clearTimeout)
    timers.current = []
  }, [])

  const selectPatient = useCallback(
    (id: string) => {
      clearTimers()
      setPatientId(id)
      setJobId(null)
      setReplay(null)
      setShowResult(false)
      setRevealed(false)
      setOutcome(null)
      setParams({ p: id }, { replace: true })
      document.getElementById('person')?.scrollIntoView({ block: 'start' })
    },
    [clearTimers],
  )

  const pick = useMutation({
    mutationFn: () => api.randomPatient(liveMode ? 'live' : 'curated', patientId ?? undefined),
    onSuccess: (card) => selectPatient(card.patient_id),
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? error.message : 'Could not reach the backend. Is it running?',
      )
    },
  })

  const run = useMutation({
    mutationFn: () => api.run(patientId!),
    onSuccess: (started) => {
      if (started.ready) {
        // Walk the stepper over ~2.7s, then show the result.
        let experts = 0
        setReplay({ ...EMPTY_JOB, stage: 'queued' })
        for (const step of REPLAY) {
          timers.current.push(
            window.setTimeout(() => {
              if (step.stage === 'model') experts += 1
              setReplay((prev) => ({
                ...(prev ?? EMPTY_JOB),
                stage: step.stage,
                expertsDone: step.stage === 'model' ? experts : step.stage === 'queued' ? 0 : 5,
                finished: step.stage === 'done',
                elapsed: step.after / 1000,
              }))
              if (step.stage === 'done') setShowResult(true)
            }, step.after),
          )
        }
      } else {
        setReplay(null)
        setJobId(started.job_id)
      }
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Could not start the run.')
    },
  })

  // A live job finishing is what makes the scan and the result available.
  useEffect(() => {
    if (liveJob.finished && !liveJob.error && jobId) {
      setShowResult(true)
      queryClient.invalidateQueries({ queryKey: ['patient', patientId] })
      queryClient.invalidateQueries({ queryKey: ['cohort'] })
      queryClient.invalidateQueries({ queryKey: ['health'] })
    }
  }, [liveJob.finished, liveJob.error, jobId, patientId, queryClient])

  useEffect(() => () => clearTimers(), [clearTimers])

  useEffect(() => {
    if (showResult && result.data) {
      document.getElementById('prediction')?.scrollIntoView({ block: 'start' })
    }
  }, [showResult, result.data])

  const reveal = async () => {
    if (!patientId) return
    try {
      setOutcome(await api.outcome(patientId))
      setRevealed(true)
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : 'Could not load the outcome.',
      )
    }
  }

  const phase: RunPhase = job.error
    ? 'error'
    : job.finished
      ? 'done'
      : job.stage
        ? 'running'
        : 'idle'

  return (
    <>
      <main className="mx-auto max-w-6xl space-y-16 px-4 pb-10">
        <ResearchHero />
        <ResearchBody />
        <HomeNotices health={health.data} />

        <PersonSection
          person={person.data}
          loading={pick.isPending || person.isLoading}
          liveMode={liveMode}
          onLiveModeChange={setLiveMode}
          onPick={() => pick.mutate()}
          onUseDemoScan={() => selectPatient('demo_offline')}
          onBrowse={() => goTo({ view: 'explore' })}
          offerDemoScan={
            !READ_ONLY &&
            !!health.data && health.data.cache.pool === 0 && health.data.weights_present
          }
          revealed={revealed}
        />

        {person.data && (
          <>
            {/* keyed per patient so the viewer's own state resets with the person */}
            <ScanViewer
              key={person.data.patient_id}
              person={person.data}
              result={showResult ? result.data : undefined}
              overlayAvailable={showResult && !!result.data}
            />

            <RunSection
              job={job}
              phase={phase}
              canRun={!!patientId && !run.isPending}
              cachedReplay={cachedReplay}
              onRun={() => run.mutate()}
              onRetry={() => {
                setJobId(null)
                setReplay(null)
                run.mutate()
              }}
            />

            <PredictionSection
              result={showResult ? result.data : undefined}
              loading={showResult && result.isLoading}
              outcome={outcome}
            />

            <RevealSection
              outcome={outcome}
              result={result.data}
              revealed={revealed}
              canReveal={showResult && !!result.data}
              onReveal={reveal}
            />
          </>
        )}

        <Scoreboard
          cohort={cohort.data}
          loading={cohort.isLoading}
          currentId={patientId}
          onSelect={selectPatient}
        />

        <SiteFooter health={health.data} />
      </main>
    </>
  )
}
