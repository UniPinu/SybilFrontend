import {
  ROUND_COLOR,
  ROUND_DASH,
  ROUND_NAME,
  examOutcomeText,
} from '@/components/explore/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Toggle } from '@/components/ui/toggle'
import { api, type ExamResult, type ParticipantResults } from '@/lib/api'
import { YEARS, pct, prefersReducedMotion } from '@/lib/format'
import { Crosshair, Download, ExternalLink } from 'lucide-react'
import { useId, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'

const chartConfig = {
  T0: { label: ROUND_NAME.T0, color: ROUND_COLOR.T0 },
  T1: { label: ROUND_NAME.T1, color: ROUND_COLOR.T1 },
  T2: { label: ROUND_NAME.T2, color: ROUND_COLOR.T2 },
} satisfies ChartConfig

type Point = { x: number; y: number; round: string; horizon: number }

function placed(exams: ExamResult[]) {
  return exams.filter((e) => e.years_since_rand != null)
}

/** Each scan's cumulative curve, one point per year 1 to 6 after the scan. */
function curvePoints(exam: ExamResult): Point[] {
  const t = exam.years_since_rand ?? 0
  return exam.risk_by_year.map((risk, k) => ({
    x: Number((t + k + 1).toFixed(2)),
    y: Number((risk * 100).toFixed(2)),
    round: exam.round,
    horizon: k + 1,
  }))
}

function ChartTip({ active, payload, label }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border bg-background px-2.5 py-1.5 text-xs shadow-md">
      <p className="pb-1 font-medium">{Number(label).toFixed(1)} years after enrolment</p>
      {payload.map((entry) => {
        const point = entry.payload as Point
        return (
          <p key={`${point.round}-${point.horizon}`} className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: ROUND_COLOR[point.round] }} />
            {point.round}
            , {point.horizon}-year risk:{' '}
            <span className="font-mono tabular-nums">{point.y.toFixed(1)}%</span>
          </p>
        )
      })}
    </div>
  )
}

function Markers({ results }: { results: ParticipantResults }) {
  const { diagnosis_years: dx, last_cancer_free_years: free } = results.timeline
  return (
    <>
      {dx != null && (
        <ReferenceLine x={dx} stroke="var(--outcome-cancer-text)" strokeWidth={2}
          label={{ value: 'diagnosis', position: 'insideTopLeft', fill: 'var(--outcome-cancer-text)', fontSize: 11 }} />
      )}
      {free != null && dx == null && (
        <ReferenceLine x={free} stroke="var(--outcome-none)" strokeDasharray="4 4"
          label={{ value: 'last cancer-free', position: 'insideTopLeft', fill: 'var(--muted-foreground)', fontSize: 11 }} />
      )}
    </>
  )
}

function CurvesChart({ results }: { results: ParticipantResults }) {
  const exams = placed(results.exams)
  const xMax = Math.ceil(Math.max(7, ...exams.map((e) => (e.years_since_rand ?? 0) + 6),
    results.timeline.diagnosis_years ?? 0, results.timeline.last_cancer_free_years ?? 0))
  const yMax = Math.max(5, ...exams.flatMap((e) => e.risk_by_year.map((r) => r * 100)))
  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-[300px] w-full">
      <LineChart margin={{ left: 4, right: 16, top: 16, bottom: 16 }}>
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="x" domain={[0, xMax]} ticks={Array.from({ length: xMax + 1 }, (_, i) => i)}
          tickLine={false} axisLine={false} tickMargin={8}
          label={{ value: 'years since enrolment', position: 'insideBottom', offset: -10, fontSize: 11 }} />
        <YAxis type="number" dataKey="y" domain={[0, Math.ceil(yMax * 1.1)]} width={44}
          tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
        <Tooltip content={ChartTip} />
        <Markers results={results} />
        {exams.map((exam) => (
          <Line key={exam.exam_id} data={curvePoints(exam)} dataKey="y" name={exam.round}
            type="monotone" stroke={ROUND_COLOR[exam.round]} strokeWidth={2.5}
            strokeDasharray={ROUND_DASH[exam.round]} dot={{ r: 3, fill: ROUND_COLOR[exam.round] }}
            isAnimationActive={!prefersReducedMotion()} />
        ))}
      </LineChart>
    </ChartContainer>
  )
}

function HorizonChart({ results, horizon }: { results: ParticipantResults; horizon: number }) {
  const exams = placed(results.exams)
  const points: Point[] = exams.map((e) => ({
    x: e.years_since_rand ?? 0,
    y: Number((e.risk_by_year[horizon - 1] * 100).toFixed(2)),
    round: e.round,
    horizon,
  }))
  const xMax = Math.ceil(Math.max(3, ...points.map((p) => p.x + 0.5),
    results.timeline.diagnosis_years ?? 0, results.timeline.last_cancer_free_years ?? 0))
  const yMax = Math.max(2, ...points.map((p) => p.y))
  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-[300px] w-full">
      <LineChart data={points} margin={{ left: 4, right: 16, top: 16, bottom: 16 }}>
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="x" domain={[0, xMax]} ticks={Array.from({ length: xMax + 1 }, (_, i) => i)}
          tickLine={false} axisLine={false} tickMargin={8}
          label={{ value: 'years since enrolment (date of each scan)', position: 'insideBottom', offset: -10, fontSize: 11 }} />
        <YAxis type="number" dataKey="y" domain={[0, Math.ceil(yMax * 1.2)]} width={44}
          tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
        <Tooltip content={ChartTip} />
        <Markers results={results} />
        <Line dataKey="y" type="linear" stroke="var(--muted-foreground)" strokeWidth={1.5}
          isAnimationActive={!prefersReducedMotion()}
          dot={(props: { cx?: number; cy?: number; payload?: Point }) => (
            <circle key={props.payload?.round} cx={props.cx} cy={props.cy} r={6}
              fill={ROUND_COLOR[props.payload?.round ?? 'T0']} stroke="var(--background)" strokeWidth={2} />
          )} />
      </LineChart>
    </ChartContainer>
  )
}

function Legend({ exams }: { exams: ExamResult[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {exams.map((e) => (
        <li key={e.exam_id} className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 4" className="h-1 w-6" aria-hidden>
            <line x1="0" y1="2" x2="24" y2="2" stroke={ROUND_COLOR[e.round]} strokeWidth="3"
              strokeDasharray={ROUND_DASH[e.round]} />
          </svg>
          {ROUND_NAME[e.round]}
          {e.years_since_rand == null && <span className="text-muted-foreground"> (undated, not plotted)</span>}
          {!e.eligible && <Badge variant="outline" className="h-4 text-[10px]">excluded</Badge>}
        </li>
      ))}
    </ul>
  )
}

function ComparisonTable({ results, onOpenStory }: {
  results: ParticipantResults
  onOpenStory: (examId: string) => void
}) {
  const blind = results.blind
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <caption className="sr-only">Sybil's risk for each screening round</caption>
        <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Round</th>
            <th scope="col" className="px-3 py-2 font-medium">When</th>
            <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">Scanner</th>
            {YEARS.map((y) => (
              <th key={y} scope="col" className="px-2 py-2 text-right font-medium">{y} y</th>
            ))}
            <th scope="col" className="px-3 py-2 text-right font-medium whitespace-nowrap">Δ 6 y</th>
            <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">Band</th>
            {!blind && <th scope="col" className="px-3 py-2 font-medium">After this scan</th>}
            <th scope="col" className="px-3 py-2"><span className="sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {results.exams.map((e) => {
            const change = e.change_from_previous?.risk_by_year[5]
            return (
              <tr key={e.exam_id} className="border-t">
                <th scope="row" className="px-3 py-2 text-left font-medium whitespace-nowrap">
                  <span className="mr-1.5 inline-block size-2.5 rounded-full" style={{ background: ROUND_COLOR[e.round] }} aria-hidden />
                  {e.round}
                  {!e.eligible && <Badge variant="outline" className="ml-1.5 h-4 text-[10px]">excluded</Badge>}
                </th>
                <td className="px-3 py-2 text-xs whitespace-nowrap">
                  {e.years_since_rand != null ? `yr ${e.years_since_rand.toFixed(1)}` : 'undated'}
                  {e.age_at_scan != null && <span className="text-muted-foreground"> · age {e.age_at_scan}</span>}
                </td>
                <td className="hidden px-3 py-2 text-xs md:table-cell">
                  {e.manufacturer ?? '—'}{e.kernel ? `, ${e.kernel}` : ''}
                </td>
                {e.risk_by_year.map((r, i) => (
                  <td key={i} className={`px-2 py-2 text-right font-mono tabular-nums ${i === 5 ? 'font-semibold' : ''}`}>
                    {(r * 100).toFixed(1)}
                  </td>
                ))}
                <td className="px-3 py-2 text-right font-mono tabular-nums whitespace-nowrap">
                  {change == null ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <>
                      {change > 0 ? '+' : change < 0 ? '−' : '±'}
                      {Math.abs(change * 100).toFixed(1)}
                      <span className="sr-only"> percentage points since {e.change_from_previous?.from_round}</span>
                    </>
                  )}
                </td>
                <td className="hidden px-3 py-2 text-xs lg:table-cell">{e.band ?? '—'}</td>
                {!blind && <td className="px-3 py-2 text-xs">{examOutcomeText(e.outcome) ?? '—'}</td>}
                <td className="px-3 py-2">
                  <Button variant="ghost" size="xs" onClick={() => onOpenStory(e.exam_id)}
                    aria-label={`Open ${e.round} in the story view`}>
                    <ExternalLink aria-hidden />
                  </Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="border-t px-3 py-2 text-xs text-muted-foreground">
        Cumulative risk in %, from each scan's own date. "Change" is in percentage points against
        the previous round that has a result.
      </p>
    </div>
  )
}

function MiniScan({ exam, overlay }: { exam: ExamResult; overlay: boolean }) {
  const n = exam.n_slices ?? 1
  const hotspot = exam.hotspot_slice ?? Math.floor(n / 2)
  const [index, setIndex] = useState(hotspot)
  const importance = exam.slice_importance ?? []
  const peak = importance.length ? Math.max(...importance) : 1
  return (
    <figure className="space-y-2">
      <figcaption className="flex items-center justify-between gap-2 text-sm font-medium">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full" style={{ background: ROUND_COLOR[exam.round] }} aria-hidden />
          {ROUND_NAME[exam.round]}
        </span>
        <span className="font-mono text-xs tabular-nums" style={{ color: ROUND_COLOR[exam.round] }}>
          {pct(exam.risk_by_year[5])}
        </span>
      </figcaption>
      <div className="relative aspect-square overflow-hidden rounded-md border border-scan-panel-border bg-scan-panel">
        <img src={api.sliceUrl(exam.exam_id, index)} alt={`${exam.round}, CT slice ${index + 1} of ${n}`}
          className="absolute inset-0 size-full object-contain" draggable={false} />
        {overlay && (
          <img src={api.overlayUrl(exam.exam_id, index)} alt="" aria-hidden
            className="pointer-events-none absolute inset-0 size-full object-contain opacity-75" draggable={false} />
        )}
        <span className="absolute right-1.5 bottom-1.5 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white">
          {index + 1}/{n}{index === hotspot ? ' · hotspot' : ''}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Slider value={[index]} min={0} max={Math.max(0, n - 1)} step={1}
          onValueChange={([v]) => setIndex(v)} aria-label={`${exam.round} slice`} className="flex-1" />
        <Button variant="ghost" size="icon-sm" onClick={() => setIndex(hotspot)}
          aria-label={`Jump to ${exam.round} hotspot`} title="Jump to hotspot">
          <Crosshair aria-hidden />
        </Button>
      </div>
      {overlay && importance.length > 0 && (
        <div className="flex h-8 items-end gap-px" role="img"
          aria-label={`${exam.round} attention per slice. The peak is at slice ${hotspot + 1} of ${n}.`}>
          {importance.map((value, i) => (
            <button key={i} type="button" tabIndex={-1} aria-hidden
              title={`Slice ${i + 1}: ${(100 * value).toFixed(1)}% of the attention`}
              onClick={() => setIndex(i)}
              className="min-w-px flex-1 rounded-t transition-colors"
              style={{
                height: `${Math.max(4, (value / peak) * 100)}%`,
                backgroundColor: i === index ? 'var(--risk-5-text)' : 'var(--risk-3-text)',
              }} />
          ))}
        </div>
      )}
      <img src={api.coronalUrl(exam.exam_id)} alt={`${exam.round}: front-on summary of where Sybil looked`}
        className="w-full rounded-md border border-scan-panel-border bg-scan-panel" />
    </figure>
  )
}

type Props = {
  results: ParticipantResults
  onOpenStory: (examId: string) => void
}

export function Comparison({ results, onOpenStory }: Props) {
  const [horizon, setHorizon] = useState(6)
  const [overlay, setOverlay] = useState(true)
  const overlayId = useId()
  const exams = results.exams
  const several = exams.length > 1

  return (
    <section id="compare" className="space-y-4" aria-labelledby="compare-heading">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 id="compare-heading" className="text-2xl font-semibold">
            {several ? 'How the prediction changed' : 'The prediction so far'}
          </h2>
          <p className="max-w-3xl text-muted-foreground">
            {several
              ? 'Each scan gets its own prediction for the six years after it was taken. Lined up on one calendar, you can see whether later scans looked riskier.'
              : 'Run another round to compare scans over time.'}
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <a href={api.exportUrl(results.nlst_pid, results.blind)} download>
            <Download aria-hidden /> Export CSV
          </a>
        </Button>
      </header>

      <Card>
        <CardContent className="space-y-3 pt-4">
          <Tabs defaultValue="curves">
            <TabsList>
              <TabsTrigger value="curves">Risk curves</TabsTrigger>
              <TabsTrigger value="horizon">One horizon</TabsTrigger>
            </TabsList>
            <TabsContent value="curves" className="space-y-2 pt-2">
              <p className="text-xs text-muted-foreground">
                Each line shows a scan's cumulative risk for years 1 to 6 after the date it was taken.
              </p>
              <CurvesChart results={results} />
            </TabsContent>
            <TabsContent value="horizon" className="space-y-2 pt-2">
              <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Risk horizon">
                <span className="pr-1 text-xs text-muted-foreground">Risk within</span>
                {YEARS.map((y) => (
                  <Toggle key={y} size="sm" variant="outline" pressed={horizon === y}
                    onPressedChange={() => setHorizon(y)}>
                    {y} y
                  </Toggle>
                ))}
              </div>
              <HorizonChart results={results} horizon={horizon} />
            </TabsContent>
          </Tabs>
          <Legend exams={exams} />
        </CardContent>
      </Card>

      <ComparisonTable results={results} onOpenStory={onOpenStory} />

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Where Sybil looked, scan by scan</CardTitle>
              <CardDescription>
                Each scan opens on its hotspot. The scans are not aligned to each other, so the same
                slice number is not the same place in the body.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Switch id={overlayId} checked={overlay} onCheckedChange={setOverlay} />
              <Label htmlFor={overlayId} className="text-sm">Attention overlay</Label>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {exams.map((exam) => <MiniScan key={exam.exam_id} exam={exam} overlay={overlay} />)}
          </div>
        </CardContent>
      </Card>
    </section>
  )
}
