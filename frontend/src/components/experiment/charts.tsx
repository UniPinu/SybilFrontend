/**
 * Charts and diagrams for the Experiment page. Round colours and dashes match
 * Explore and the research diagrams; every colour is a CSS variable, so both
 * themes work.
 */
import { ROUND_COLOR } from '@/components/explore/shared'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import type { TrajectoryGuide } from '@/lib/api'
import { prefersReducedMotion } from '@/lib/format'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'

export type Series = {
  key: string
  label: string
  color: string
  data: { x: number; y: number }[]
  dash?: string
  width?: number
  opacity?: number
  dots?: boolean
}

export type Marker = { x: number; label: string; color?: string; dash?: string }

function Tip({ active, payload, label }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border bg-background px-2.5 py-1.5 text-xs shadow-md">
      <p className="pb-1 font-medium">{Number(label).toFixed(2)} years</p>
      {payload.map((entry) => (
        <p key={String(entry.name)} className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ background: entry.color }} />
          {entry.name}: <span className="font-mono tabular-nums">{Number(entry.value).toFixed(1)}%</span>
        </p>
      ))}
    </div>
  )
}

/** Several risk curves on one numeric time axis; y is in percent. */
export function ClockChart({ series, xMin = 0, xMax, xLabel, yMax, markers = [], band, height = 280 }: {
  series: Series[]
  xMin?: number
  xMax: number
  xLabel: string
  yMax?: number
  markers?: Marker[]
  band?: { from: number; to: number; label: string }
  height?: number
}) {
  const config = Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }])) satisfies ChartConfig
  const top = yMax ?? Math.ceil((Math.max(5, ...series.flatMap((s) => s.data.map((p) => p.y))) * 1.1) / 10) * 10
  const ticks = Array.from({ length: Math.floor(xMax) - Math.ceil(xMin) + 1 }, (_, i) => Math.ceil(xMin) + i)
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
      <LineChart margin={{ left: 4, right: 16, top: 18, bottom: 16 }}>
        <CartesianGrid vertical={false} />
        <XAxis type="number" dataKey="x" domain={[xMin, xMax]} ticks={ticks} tickLine={false} axisLine={false}
          tickMargin={8} allowDuplicatedCategory={false}
          label={{ value: xLabel, position: 'insideBottom', offset: -10, fontSize: 11 }} />
        <YAxis type="number" dataKey="y" domain={[0, top]} width={44} tickLine={false} axisLine={false}
          tickFormatter={(v: number) => `${v}%`} />
        <Tooltip content={Tip} />
        {band && (
          <ReferenceArea x1={band.from} x2={band.to} fill="var(--round-2)" fillOpacity={0.08}
            label={{ value: band.label, position: 'insideTop', fontSize: 11, fill: 'var(--muted-foreground)' }} />
        )}
        {markers.map((m) => (
          <ReferenceLine key={m.label} x={m.x} stroke={m.color ?? 'var(--muted-foreground)'} strokeDasharray={m.dash ?? '4 4'}
            label={{ value: m.label, position: 'insideTopRight', fill: m.color ?? 'var(--muted-foreground)', fontSize: 11 }} />
        ))}
        {series.map((s) => (
          <Line key={s.key} data={s.data} dataKey="y" name={s.label} type="linear" stroke={s.color}
            strokeWidth={s.width ?? 2.5} strokeDasharray={s.dash} strokeOpacity={s.opacity ?? 1}
            dot={s.dots ? { r: 3.5, fill: s.color, strokeWidth: 0, fillOpacity: s.opacity ?? 1 } : false}
            activeDot={s.dots ? { r: 5 } : false}
            isAnimationActive={!prefersReducedMotion()} />
        ))}
      </LineChart>
    </ChartContainer>
  )
}

export function SeriesLegend({ series }: { series: Pick<Series, 'key' | 'label' | 'color' | 'dash' | 'opacity'>[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <svg viewBox="0 0 24 4" className="h-1 w-6" aria-hidden>
            <line x1="0" y1="2" x2="24" y2="2" stroke={s.color} strokeWidth="3" strokeDasharray={s.dash}
              strokeOpacity={s.opacity ?? 1} />
          </svg>
          {s.label}
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
/** The three scans (and the diagnosis) on one calendar, with the T0 -> T1 gap marked. */
export function ScanTimeline({ guide }: { guide: TrajectoryGuide }) {
  const dx = guide.outcome?.years_rand_to_dx ?? null
  const end = Math.ceil(Math.max(guide.scans[2].years, dx ?? 0) + 0.4)
  const W = 720, H = 150, L = 24, R = 24, AXIS = 96
  const x = (v: number) => L + (v / end) * (W - L - R)
  const [s0, s1] = guide.scans
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img"
      aria-label={`Scans at ${guide.scans.map((s) => `${s.round} ${s.years.toFixed(2)} years`).join(', ')}${dx != null ? `; diagnosis at ${dx.toFixed(2)} years` : ''}`}>
      <line x1={L} x2={W - R} y1={AXIS} y2={AXIS} stroke="var(--border)" strokeWidth={2} />
      {Array.from({ length: end + 1 }, (_, i) => (
        <g key={i}>
          <line x1={x(i)} x2={x(i)} y1={AXIS - 4} y2={AXIS + 4} stroke="var(--muted-foreground)" />
          <text x={x(i)} y={AXIS + 20} textAnchor="middle" fontSize={12} fill="var(--muted-foreground)">{i} y</text>
        </g>
      ))}
      <text x={W - R} y={AXIS + 40} textAnchor="end" fontSize={11} fill="var(--muted-foreground)">years since enrolment</text>

      {/* the 13th input */}
      <path d={`M${x(s0.years)},${AXIS - 40} v-8 H${x(s1.years)} v8`} fill="none" stroke="var(--primary)" strokeWidth={1.5} />
      <text x={(x(s0.years) + x(s1.years)) / 2} y={AXIS - 54} textAnchor="middle" fontSize={12} fontWeight={600} fill="var(--primary)">
        Δ = {guide.offset.toFixed(2)} y
      </text>

      {dx != null && (
        <g>
          <line x1={x(dx)} x2={x(dx)} y1={AXIS - 30} y2={AXIS} stroke="var(--outcome-cancer-text)" strokeWidth={2} strokeDasharray="4 3" />
          <text x={x(dx)} y={AXIS - 36} textAnchor="middle" fontSize={11} fill="var(--outcome-cancer-text)">diagnosis</text>
        </g>
      )}
      {guide.scans.map((s) => (
        <g key={s.round}>
          <circle cx={x(s.years)} cy={AXIS} r={10} fill={ROUND_COLOR[s.round]} stroke="var(--background)" strokeWidth={3} />
          <text x={x(s.years)} y={AXIS - 18} textAnchor="middle" fontSize={13} fontWeight={600} fill="var(--foreground)">{s.round}</text>
        </g>
      ))}
    </svg>
  )
}

// ---------------------------------------------------------------------------
/** 13 inputs -> 8 hidden -> 6 outputs, labelled with this participant's values. */
export function NetworkDiagram({ guide, withOffset }: { guide: TrajectoryGuide; withOffset: boolean }) {
  const { inputs, hidden, outputs } = guide.network
  const W = 720, ROW = 32, TOP = 24
  const H = TOP * 2 + ROW * (inputs.length - 1)
  const col = { in: 230, hid: 440, out: 620 }
  const span = (inputs.length - 1) * ROW
  /** n nodes spread evenly over the height of the input column */
  const yAt = (i: number, n: number) => TOP + (span * (i + 0.5)) / n
  const yIn = (i: number) => TOP + i * ROW
  const yHid = (j: number) => yAt(j, hidden)
  const yOut = (k: number) => yAt(k, outputs.length)
  const inColor = (i: number) => (i < 6 ? ROUND_COLOR.T0 : i < 12 ? ROUND_COLOR.T1 : 'var(--primary)')
  const off = (i: number) => i === 12 && !withOffset

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img"
      aria-label={`A network with ${withOffset ? 13 : 12} inputs, ${hidden} hidden neurons and ${outputs.length} outputs`}>
      <g stroke="var(--muted-foreground)" strokeWidth={0.6}>
        {inputs.map((_, i) => !off(i) && Array.from({ length: hidden }, (_, j) => (
          <line key={`a${i}-${j}`} x1={col.in} y1={yIn(i)} x2={col.hid} y2={yHid(j)}
            strokeOpacity={i === 12 ? 0.55 : 0.18} stroke={i === 12 ? 'var(--primary)' : undefined} />
        )))}
        {Array.from({ length: hidden }, (_, j) => outputs.map((_, k) => (
          <line key={`b${j}-${k}`} x1={col.hid} y1={yHid(j)} x2={col.out} y2={yOut(k)} strokeOpacity={0.18} />
        )))}
      </g>

      {inputs.map((inp, i) => (
        <g key={inp.name} opacity={off(i) ? 0.3 : 1}>
          <text x={col.in - 16} y={yIn(i) + 5} textAnchor="end" fontSize={14} fill="var(--foreground)">
            <tspan>{inp.name}</tspan>
            <tspan dx={10} fontWeight={600} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {i === 12 ? `${inp.value.toFixed(2)} y` : `${(inp.value * 100).toFixed(1)}%`}
            </tspan>
          </text>
          <circle cx={col.in} cy={yIn(i)} r={8} fill={inColor(i)} stroke="var(--background)" strokeWidth={2}
            strokeDasharray={off(i) ? '2 2' : undefined} />
        </g>
      ))}
      {Array.from({ length: hidden }, (_, j) => (
        <circle key={j} cx={col.hid} cy={yHid(j)} r={9} fill="var(--muted)" stroke="var(--muted-foreground)" strokeWidth={1.5} />
      ))}
      <text x={col.hid} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--muted-foreground)">{hidden} × tanh</text>
      {outputs.map((name, k) => (
        <g key={name}>
          <circle cx={col.out} cy={yOut(k)} r={8} fill={ROUND_COLOR.T2} stroke="var(--background)" strokeWidth={2} />
          <text x={col.out + 16} y={yOut(k) + 5} fontSize={14} fill="var(--foreground)">{name}</text>
        </g>
      ))}
      <text x={col.in} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--muted-foreground)">
        {withOffset ? 13 : 12} inputs
      </text>
      <text x={col.out} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--muted-foreground)">6 outputs</text>
    </svg>
  )
}
