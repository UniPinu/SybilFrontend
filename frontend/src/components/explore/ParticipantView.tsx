import { Comparison } from '@/components/explore/Comparison'
import { RoundCard } from '@/components/explore/RoundCard'
import { Timeline } from '@/components/explore/Timeline'
import { estimateMinutes, participantOutcomeText } from '@/components/explore/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError, type RoundDetail } from '@/lib/api'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Loader2, Play } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'

type Props = {
  pid: string
  blind: boolean
  onBack: () => void
  onOpenStory: (examId: string) => void
}

/** Runnable, not cached, not already on its way. */
function canQueue(round: RoundDetail, jobs: Record<string, string>): boolean {
  return round.runnable && !round.ready && !!round.exam_id && !jobs[round.exam_id]
}

export function ParticipantView({ pid, blind, onBack, onOpenStory }: Props) {
  const queryClient = useQueryClient()
  // exam_id -> job_id for runs started here, plus failed ones kept for their message
  const [localJobs, setLocalJobs] = useState<Record<string, string>>({})
  const [finished, setFinished] = useState<Set<string>>(new Set())
  // everything that could run starts ticked; this holds what the user unticked
  const [unticked, setUnticked] = useState<Set<string>>(new Set())

  const detail = useQuery({
    queryKey: ['participant', pid, blind],
    queryFn: () => api.participant(pid, blind),
    // queue positions move while someone else's scan is running
    refetchInterval: (query) =>
      query.state.data?.rounds.some((r) => r.job) || Object.keys(localJobs).length ? 5000 : false,
  })
  const results = useQuery({
    queryKey: ['participant-results', pid, blind],
    queryFn: () => api.participantResults(pid, blind),
  })

  const rounds = useMemo(() => detail.data?.rounds ?? [], [detail.data])
  // Runs the server knows about (a reload, another tab) plus the ones started here.
  const jobs = useMemo(() => {
    const out: Record<string, string> = {}
    for (const r of rounds) {
      if (r.exam_id && r.job && !finished.has(r.job.job_id)) out[r.exam_id] = r.job.job_id
    }
    return { ...out, ...localJobs }
  }, [rounds, localJobs, finished])
  const resultByExam = useMemo(
    () => Object.fromEntries((results.data?.exams ?? []).map((e) => [e.exam_id, e])),
    [results.data],
  )

  const refresh = useCallback(() => {
    for (const key of ['participant', 'participant-results', 'participants', 'cohort', 'health']) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }, [queryClient])

  const onFinished = useCallback(
    (examId: string, jobId: string, ok: boolean) => {
      setFinished((prev) => new Set(prev).add(jobId))
      setLocalJobs((prev) => {
        const next = { ...prev }
        // a failed job stays on its card so the error and "try again" remain visible
        if (ok) delete next[examId]
        else next[examId] = jobId
        return next
      })
      refresh()
    },
    [refresh],
  )

  const run = useMutation({
    mutationFn: (examIds: string[]) => api.runParticipant(pid, examIds),
    onSuccess: ({ runs }) => {
      const started = Object.fromEntries(
        runs.filter((r) => r.job_id).map((r) => [r.exam_id, r.job_id as string]),
      )
      setLocalJobs((prev) => ({ ...prev, ...started }))
      setUnticked(new Set())
      if (runs.some((r) => r.ready)) refresh()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Could not start the run.')
    },
  })

  const retry = (examId: string) => {
    setLocalJobs((prev) => {
      const next = { ...prev }
      delete next[examId]
      return next
    })
    run.mutate([examId])
  }

  if (detail.isError) {
    return (
      <div className="space-y-4 pt-8">
        <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft aria-hidden /> All participants</Button>
        <Alert variant="destructive">
          <AlertDescription>
            {detail.error instanceof ApiError && detail.error.status === 404
              ? `There is no participant ${pid} with a usable scan.`
              : detail.error instanceof ApiError
                ? detail.error.message
                : 'Could not reach the backend. Is it running?'}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const person = detail.data
  const queueable = rounds.filter((r) => canQueue(r, jobs))
  const chosen = queueable.filter((r) => !unticked.has(r.exam_id!))
  const statuses = Object.fromEntries(rounds.map((r) => [r.round, r.status]))
  const facts = person
    ? [
        person.age_at_randomization != null && `${person.age_at_randomization} at enrolment`,
        person.sex,
        person.smoking_status,
        person.race,
      ].filter(Boolean)
    : []

  return (
    <div className="space-y-10 pt-6">
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
          <ArrowLeft aria-hidden /> All participants
        </Button>

        {!person ? (
          <div className="space-y-3">
            <Skeleton className="h-9 w-72" />
            <Skeleton className="h-5 w-96" />
          </div>
        ) : (
          <header className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-semibold">Participant <span className="font-mono">{pid}</span></h1>
              {person.in_regression_set && (
                <Badge variant="outline" title="One of the series upstream's regression test uses">
                  upstream test series
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground">{facts.join(' · ')}</p>
            {person.outcome && (
              <p className={`rounded-md border px-3 py-2 text-sm ${
                person.outcome.diagnosed ? 'border-outcome-cancer/40 bg-outcome-cancer/10' : 'bg-muted/40'}`}>
                {participantOutcomeText(person.outcome)}.
              </p>
            )}
          </header>
        )}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Screening timeline</CardTitle>
        </CardHeader>
        <CardContent>
          {person ? <Timeline timeline={person.timeline} statuses={statuses} /> : <Skeleton className="h-24" />}
        </CardContent>
      </Card>

      <section className="space-y-4" aria-labelledby="rounds-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1">
            <h2 id="rounds-heading" className="text-2xl font-semibold">Screening rounds</h2>
            <p className="max-w-2xl text-muted-foreground">
              NLST offered up to three yearly scans. Choose which ones Sybil should read. One scan
              runs at a time, about a minute and a half each.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {chosen.length > 0 && (
              <span className="text-sm text-muted-foreground">{estimateMinutes(chosen.length)}</span>
            )}
            <Button size="lg" disabled={chosen.length === 0 || run.isPending}
              onClick={() => run.mutate(chosen.map((r) => r.exam_id!))}>
              {run.isPending ? <Loader2 className="size-5 animate-spin" aria-hidden /> : <Play className="size-5" aria-hidden />}
              {chosen.length > 1 ? `Run ${chosen.length} rounds` : chosen.length === 1 ? `Run ${chosen[0].round}` : 'Run Sybil'}
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {person
            ? rounds.map((round) => (
                <RoundCard
                  key={round.round}
                  round={round}
                  result={round.exam_id ? resultByExam[round.exam_id] : undefined}
                  jobId={round.exam_id ? (jobs[round.exam_id] ?? null) : null}
                  selected={!!round.exam_id && !unticked.has(round.exam_id)}
                  selectable={canQueue(round, jobs)}
                  onSelectedChange={(value) =>
                    setUnticked((prev) => {
                      const next = new Set(prev)
                      if (value) next.delete(round.exam_id!)
                      else next.add(round.exam_id!)
                      return next
                    })
                  }
                  onFinished={onFinished}
                  onRetry={retry}
                  onOpenStory={onOpenStory}
                />
              ))
            : [0, 1, 2].map((i) => <Skeleton key={i} className="h-64" />)}
        </div>
      </section>

      {results.data && results.data.exams.length > 0 && (
        <Comparison results={results.data} onOpenStory={onOpenStory} />
      )}
    </div>
  )
}
