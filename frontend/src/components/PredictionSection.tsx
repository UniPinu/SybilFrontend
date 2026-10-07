import { Term } from '@/components/Glossary'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import type { Outcome, RiskResult } from '@/lib/api'
import { inHundred, prefersReducedMotion, riskColor, riskTextColor, riskWord } from '@/lib/format'
import { animate } from 'motion'
import { useEffect, useRef } from 'react'
import { Area, AreaChart, CartesianGrid, Line, ReferenceLine, XAxis, YAxis } from 'recharts'

const chartConfig = {
  person: { label: 'This person', color: 'var(--chart-1)' },
  typical: { label: 'A typical participant', color: 'var(--chart-2)' },
} satisfies ChartConfig

function CountUp({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    if (prefersReducedMotion()) {
      node.textContent = value.toFixed(1)
      return
    }
    const controls = animate(0, value, {
      duration: 1.1,
      ease: 'easeOut',
      onUpdate: (latest: number) => {
        node.textContent = latest.toFixed(1)
      },
    })
    return () => controls.stop()
  }, [value])
  return <span ref={ref}>0.0</span>
}

function IconArray({ filled, color }: { filled: number; color: string }) {
  return (
    <div
      className="grid w-fit grid-cols-10 gap-[3px]"
      role="img"
      aria-label={`${filled} of 100 people shaded`}
    >
      {Array.from({ length: 100 }, (_, i) => (
        <svg key={i} viewBox="0 0 12 20" className="h-5 w-3" aria-hidden>
          <circle cx="6" cy="4" r="3.2" fill={i < filled ? color : 'var(--muted)'} />
          <path d="M6 8c-3 0-5 2-5 5v6h10v-6c0-3-2-5-5-5z" fill={i < filled ? color : 'var(--muted)'} />
        </svg>
      ))}
    </div>
  )
}

type Props = {
  result: RiskResult | undefined
  loading: boolean
  outcome: Outcome | null
}

export function PredictionSection({ result, loading, outcome }: Props) {
  if (loading && !result) {
    return (
      <section id="prediction" className="section-anchor space-y-4">
        <h2 className="text-2xl font-semibold">The prediction</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </section>
    )
  }
  if (!result) return null

  const risk6 = result.risk_by_year[5]
  const people = result.people_in_100
  const colour = riskColor(risk6)
  const textColour = riskTextColor(risk6)
  const reference = result.reference
  const data = result.risk_by_year.map((value, i) => ({
    year: `Year ${i + 1}`,
    person: Number((value * 100).toFixed(2)),
    typical: reference ? Number((reference.median[i] * 100).toFixed(2)) : null,
  }))
  const diagnosisYear = outcome?.cancer_within_6y ? (outcome.diagnosis_year ?? null) : null

  return (
    <section id="prediction" className="section-anchor space-y-4">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold">The prediction</h2>
        <p className="max-w-2xl text-muted-foreground">
          Six numbers, one per year. They are cumulative: the year-6 number includes everyone
          diagnosed in years 1 to 5.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>6-year risk</CardDescription>
            <CardTitle className="text-5xl font-semibold tabular-nums" style={{ color: textColour }}>
              <CountUp value={result.headline_pct} />%
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">
              About <span className="font-semibold">{people} in 100</span> people with a scan like this
              are diagnosed with lung cancer within 6 years.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" style={{ borderColor: textColour, color: textColour }}>
                {riskWord(risk6)} risk
              </Badge>
              {result.band.band && <Badge variant="secondary">{result.band.band}</Badge>}
            </div>
            {result.band.times_typical != null && (
              <p className="text-xs text-muted-foreground">
                That is about {result.band.times_typical}x the median of our small reference sample
                ({((result.band.reference_median_6y ?? 0) * 100).toFixed(1)}%). It is a comparison,
                not a diagnosis.
              </p>
            )}
            <IconArray filled={people} color={textColour} />
            <p className="text-xs text-muted-foreground">
              Each figure is one person. {people} shaded, {100 - people} not.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Risk year by year</CardTitle>
            <CardDescription>
              {reference
                ? `The dashed line is the median of ${reference.n} randomly chosen participants.`
                : 'Prepare the reference sample to compare against a typical participant.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ChartContainer config={chartConfig} className="h-[260px] w-full">
              <AreaChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 4 }}>
                <defs>
                  <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={colour} stopOpacity={0.5} />
                    <stop offset="100%" stopColor={colour} stopOpacity={0.06} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="year" tickLine={false} axisLine={false} tickMargin={8} />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={44}
                  tickFormatter={(value: number) => `${value}%`}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      formatter={(value, name) => [
                        `${Number(value).toFixed(1)}%  `,
                        name === 'person' ? 'this person' : 'typical participant',
                      ]}
                    />
                  }
                />
                {diagnosisYear && (
                  <ReferenceLine
                    x={`Year ${diagnosisYear}`}
                    stroke="var(--outcome-cancer-text)"
                    strokeDasharray="4 4"
                    label={{
                      value: 'diagnosed',
                      position: 'insideTopRight',
                      fill: 'var(--outcome-cancer-text)',
                      fontSize: 11,
                    }}
                  />
                )}
                <Area
                  dataKey="person"
                  type="monotone"
                  stroke={textColour}
                  strokeWidth={2.5}
                  fill="url(#riskFill)"
                  dot={{ r: 3 }}
                  isAnimationActive={!prefersReducedMotion()}
                />
                {reference && (
                  <Line
                    dataKey="typical"
                    type="monotone"
                    stroke="var(--chart-2)"
                    strokeWidth={2}
                    strokeDasharray="5 4"
                    dot={false}
                    isAnimationActive={!prefersReducedMotion()}
                  />
                )}
              </AreaChart>
            </ChartContainer>
            <p className="pt-2 text-xs text-muted-foreground">
              Percentages come out of Sybil's <Term term="calibration">calibration</Term> step, so
              "{result.risk_pct_by_year[2]}% by year 3" means about{' '}
              {inHundred(result.risk_by_year[2])} in 100 people like this.
            </p>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
