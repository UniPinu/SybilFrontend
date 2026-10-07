import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDuration, formatMb } from '@/lib/format'
import type { JobState, StageName } from '@/hooks/useJobEvents'
import { AlertTriangle, Check, Loader2, Play } from 'lucide-react'

export type RunPhase = 'idle' | 'running' | 'done' | 'error'

const STEPS: { stage: StageName; label: string; detail: string }[] = [
  { stage: 'downloading', label: 'Fetching the scan', detail: 'straight from the public trial archive' },
  { stage: 'reading', label: 'Reading the scan', detail: 'sorting the slices and checking the spacing' },
  { stage: 'standardizing', label: 'Making every scan look alike', detail: 'same millimetres per voxel, same size' },
  { stage: 'model', label: '5 experts vote', detail: 'five separately trained copies of Sybil' },
  { stage: 'calibrating', label: 'Turning votes into honest percentages', detail: 'so 7% means about 7 in 100' },
  { stage: 'rendering', label: 'Preparing the pictures', detail: 'slices, overlays and the coronal map' },
]

const ORDER: StageName[] = ['queued', ...STEPS.map((s) => s.stage), 'done']

function stageRank(stage: StageName | null): number {
  if (!stage) return -1
  const index = ORDER.indexOf(stage)
  return index === -1 ? ORDER.length : index
}

type Props = {
  job: JobState
  phase: RunPhase
  canRun: boolean
  cachedReplay: boolean
  onRun: () => void
  onRetry: () => void
}

export function RunSection({ job, phase, canRun, cachedReplay, onRun, onRetry }: Props) {
  const rank = stageRank(job.stage)
  const downloadPct = job.bytesTotal ? Math.min(100, (job.bytesDone / job.bytesTotal) * 100) : 0

  return (
    <section id="run" className="section-anchor space-y-4">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold">Run Sybil</h2>
        <p className="max-w-2xl text-muted-foreground">
          Five separately trained copies of the model each read the whole scan and cast a vote. Their
          average is then calibrated into percentages.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-4">
        <Button size="lg" onClick={onRun} disabled={!canRun || phase === 'running'}>
          {phase === 'running' ? (
            <Loader2 className="size-5 animate-spin" aria-hidden />
          ) : (
            <Play className="size-5" aria-hidden />
          )}
          {phase === 'running' ? 'Sybil is working…' : 'Run Sybil'}
        </Button>
        {phase === 'running' && (
          <span className="font-mono text-sm text-muted-foreground">
            {formatDuration(job.elapsed)}
          </span>
        )}
        {cachedReplay && phase !== 'idle' && (
          <span className="text-sm text-muted-foreground">
            This person was processed in advance - replaying the steps.
          </span>
        )}
      </div>

      {phase !== 'idle' && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">What is happening</CardTitle>
              {job.queuePosition !== null && job.queuePosition > 0 && (
                <CardDescription>
                  Waiting for Sybil: {job.queuePosition} ahead in the queue. Only one scan runs at a
                  time.
                </CardDescription>
              )}
            </CardHeader>
            <CardContent className="space-y-3">
              {STEPS.map((step) => {
                const stepRank = stageRank(step.stage)
                const state =
                  job.stage === 'error' && stepRank === rank
                    ? 'error'
                    : stepRank < rank || job.finished
                      ? 'done'
                      : stepRank === rank
                        ? 'active'
                        : 'todo'
                return (
                  <div key={step.stage} className="flex items-start gap-3">
                    <span
                      className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border text-[10px] ${
                        state === 'done'
                          ? 'border-risk-2 bg-risk-2/20 text-foreground'
                          : state === 'active'
                            ? 'border-risk-4 bg-risk-4/20'
                            : state === 'error'
                              ? 'border-destructive bg-destructive/20'
                              : 'border-muted text-muted-foreground'
                      }`}
                      aria-hidden
                    >
                      {state === 'done' ? (
                        <Check className="size-3" />
                      ) : state === 'active' ? (
                        <Loader2 className="size-3 animate-spin" />
                      ) : state === 'error' ? (
                        <AlertTriangle className="size-3" />
                      ) : null}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p
                        className={`text-sm ${state === 'todo' ? 'text-muted-foreground' : 'font-medium'}`}
                      >
                        {step.label}
                        {step.stage === 'model' && job.expertsDone > 0 && (
                          <span className="pl-2 font-normal text-muted-foreground">
                            expert {Math.min(job.expertsDone, 5)} of 5
                          </span>
                        )}
                        {step.stage === 'reading' && job.nSlices && (
                          <span className="pl-2 font-normal text-muted-foreground">
                            {job.nSlices} slices
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">{step.detail}</p>
                      {step.stage === 'downloading' && state !== 'todo' && job.bytesTotal > 0 && (
                        <div className="flex items-center gap-2 pt-1">
                          <Progress value={downloadPct} className="h-1.5 flex-1" />
                          <span className="font-mono text-xs text-muted-foreground">
                            {formatMb(job.bytesDone)} / {formatMb(job.bytesTotal)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}

              {job.error && (
                <div className="space-y-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
                  <p>{job.error}</p>
                  <Button variant="outline" size="sm" onClick={onRetry}>
                    Try again
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">The five experts</CardTitle>
              <CardDescription>
                Each was trained on a different split of the data, so they disagree a little.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-3">
                {[1, 2, 3, 4, 5].map((n) => {
                  const done = job.expertsDone >= n
                  const active = job.expertsDone === n - 1 && job.stage === 'model'
                  return (
                    <div key={n} className="flex flex-col items-center gap-1">
                      <span
                        className={`flex size-11 items-center justify-center rounded-full border-2 text-sm font-medium transition-colors ${
                          done
                            ? 'border-risk-4 bg-risk-4/25 text-foreground'
                            : active
                              ? 'border-risk-3 bg-risk-3/10'
                              : 'border-dashed border-muted text-muted-foreground'
                        }`}
                      >
                        {done ? <Check className="size-5" aria-hidden /> : n}
                      </span>
                      <span className="text-[10px] text-muted-foreground">expert {n}</span>
                    </div>
                  )
                })}
              </div>
              {!job.finished && (
                <div className="space-y-2 pt-4">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-24 w-full" />
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </section>
  )
}
