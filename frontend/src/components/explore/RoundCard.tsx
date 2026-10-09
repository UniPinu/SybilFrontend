import {
  ROUND_COLOR,
  ROUND_NAME,
  STATUS_LABEL,
  examOutcomeText,
} from '@/components/explore/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { useJobEvents, type JobState } from '@/hooks/useJobEvents'
import type { ExamResult, RoundDetail } from '@/lib/api'
import { formatDuration, pct, riskTextColor } from '@/lib/format'
import { AlertTriangle, Check, ExternalLink, Loader2 } from 'lucide-react'
import { useEffect, useId } from 'react'

const STAGE_TEXT: Record<string, string> = {
  queued: 'Waiting in the queue',
  downloading: 'Fetching the scan',
  reading: 'Reading the scan',
  standardizing: 'Standardising',
  model: 'Experts voting',
  calibrating: 'Calibrating',
  rendering: 'Preparing pictures',
  done: 'Done',
}

/** One bar for the whole run, weighted roughly by where the time goes. */
function progressOf(job: JobState): number {
  switch (job.stage) {
    case 'downloading':
      return 5 + (job.bytesTotal ? (job.bytesDone / job.bytesTotal) * 20 : 0)
    case 'reading':
      return 27
    case 'standardizing':
      return 32
    case 'model':
      // `index` arrives as each expert starts, so the finished count is one less
      return 35 + (Math.max(0, Math.min(job.expertsDone, 5) - 1) / 5) * 50
    case 'calibrating':
      return 88
    case 'rendering':
      return 92
    case 'done':
      return 100
    default:
      return 2
  }
}

function RoundProgress({ job, position }: { job: JobState; position: number | null }) {
  const queued = !job.stage || job.stage === 'queued'
  const ahead = job.queuePosition ?? position
  const label = queued
    ? ahead
      ? `Waiting: ${ahead} ahead in the queue`
      : STAGE_TEXT.queued
    : job.stage === 'model'
      ? `${STAGE_TEXT.model}: expert ${Math.max(1, Math.min(job.expertsDone, 5))} of 5`
      : (STAGE_TEXT[job.stage ?? 'queued'] ?? job.stage)
  const value = progressOf(job)
  return (
    <div className="space-y-1.5" aria-live="polite">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-1.5">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          {label}
        </span>
        {!queued && (
          <span className="font-mono text-xs text-muted-foreground">{formatDuration(job.elapsed)}</span>
        )}
      </div>
      <Progress value={value} className="h-1.5" aria-label={`Run progress: ${Math.round(value)}%`} />
    </div>
  )
}

type Props = {
  round: RoundDetail
  result: ExamResult | undefined
  jobId: string | null
  selected: boolean
  selectable: boolean
  onSelectedChange: (selected: boolean) => void
  onFinished: (examId: string, jobId: string, ok: boolean) => void
  onRetry: (examId: string) => void
  onOpenStory: (examId: string) => void
}

export function RoundCard({
  round, result, jobId, selected, selectable, onSelectedChange, onFinished, onRetry, onOpenStory,
}: Props) {
  const job = useJobEvents(jobId)
  const checkboxId = useId()
  const examId = round.exam_id
  const color = ROUND_COLOR[round.round]
  const outcomeText = examOutcomeText(round.outcome)
  const running = !!jobId && !job.finished

  useEffect(() => {
    if (jobId && examId && job.finished) onFinished(examId, jobId, !job.error)
    // onFinished is stable in the parent; firing once per finish is the point
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.finished, job.error, jobId, examId])

  return (
    <Card className={round.runnable ? 'h-full' : 'h-full border-dashed bg-muted/20'}>
      <CardHeader className="space-y-2 pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <span className="size-3 rounded-full" style={{ background: round.runnable ? color : 'var(--muted)' }} aria-hidden />
            {ROUND_NAME[round.round]}
          </CardTitle>
          {round.ready ? (
            <Badge variant="secondary"><Check aria-hidden /> Run</Badge>
          ) : (
            <Badge variant="outline">{STATUS_LABEL[round.status]}</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {round.years_since_rand != null
            ? `${round.years_since_rand.toFixed(1)} years after enrolment`
            : round.status === 'no_images'
              ? 'No scan for this round'
              : 'Screening date not recorded'}
          {round.age_at_scan != null && ` · age ${round.age_at_scan}`}
        </p>
      </CardHeader>

      <CardContent className="space-y-3 text-sm">
        {round.status !== 'eligible' && round.reason && (
          <p className="text-xs text-muted-foreground">
            {round.status === 'excluded' ? 'Excluded from evaluation: ' : ''}
            {round.reason}
          </p>
        )}
        {round.status === 'excluded' && (
          <p className="text-xs">
            Sybil can still read it, but its result is not counted towards any accuracy figure.
          </p>
        )}

        {round.series && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            <dt className="text-muted-foreground">Scanner</dt>
            <dd>{round.series.manufacturer ?? '—'}</dd>
            <dt className="text-muted-foreground">Kernel</dt>
            <dd>{round.series.kernel ?? '—'}</dd>
            <dt className="text-muted-foreground">Slices</dt>
            <dd>
              {round.series.n_instances ?? '—'} × {round.series.thickness_mm ?? '—'} mm
              <span className="text-muted-foreground"> · {round.series.series_size_mb} MB</span>
            </dd>
          </dl>
        )}

        {outcomeText && (
          <p className="text-xs">
            <span className="text-muted-foreground">After this scan: </span>
            <span className={round.outcome?.cancer_within_6y || (round.outcome?.years_to_cancer ?? -1) >= 0
              ? 'text-outcome-cancer-text' : ''}>
              {outcomeText}
            </span>
          </p>
        )}

        {result && (
          <p>
            6-year risk{' '}
            <span className="text-lg font-semibold tabular-nums"
              style={{ color: riskTextColor(result.risk_by_year[5]) }}>
              {pct(result.risk_by_year[5])}
            </span>
          </p>
        )}

        {running && <RoundProgress job={job} position={round.job?.position ?? null} />}

        {jobId && job.error && (
          <div className="space-y-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs">
            <p className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {job.error}
            </p>
            {examId && (
              <Button variant="outline" size="xs" onClick={() => onRetry(examId)}>Try again</Button>
            )}
          </div>
        )}

        {round.ready && examId && (
          <Button variant="outline" size="sm" onClick={() => onOpenStory(examId)}>
            <ExternalLink aria-hidden /> Open in story view
          </Button>
        )}

        {selectable && !running && !(jobId && job.error) && (
          <div className="flex items-center gap-2 pt-1">
            <Checkbox id={checkboxId} checked={selected}
              onCheckedChange={(value) => onSelectedChange(value === true)} />
            <Label htmlFor={checkboxId} className="text-sm">Include in the next run</Label>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
