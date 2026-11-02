/**
 * Charts for the Features page. Diagnosis uses the outcome tokens, rounds keep
 * their Explore colours and add a marker shape, and the heatmap uses the
 * validated diverging pair (--diverge-neg / --diverge-pos) around the muted
 * surface. Every colour sits next to a label or a tooltip.
 */
import { ROUND_COLOR } from '@/components/explore/shared'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import type { FeatureOverview, FeatureParticipant } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
  type TooltipContentProps,
} from 'recharts'
import type { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'

export const DX_COLOR = 'var(--outcome-cancer)'
export const NO_DX_COLOR = 'var(--outcome-none)'
export const WITHIN_COLOR = 'var(--foreground)'
export const BETWEEN_COLOR = 'var(--reference-line)'

export const dxColor = (diagnosed: boolean | null | undefined) => (diagnosed ? DX_COLOR : NO_DX_COLOR)

type MapPoint = NonNullable<FeatureOverview['map']>['points'][number]

/** Circle, square, triangle: round identity that survives greyscale. */
function RoundMarker({ cx, cy, round, color, size, ring }: {
  cx: number; cy: number; round: string; color: string; size: number; ring?: boolean
}) {
  const stroke = ring ? 'var(--background)' : 'none'
  if (round === 'T1') {
    return <rect x={cx - size} y={cy - size} width={size * 2} height={size * 2} rx={1} fill={color} stroke={stroke} strokeWidth={2} />
  }
  if (round === 'T2') {
    const h = size * 1.25
    return <path d={`M${cx},${cy - h} L${cx + h},${cy + h * 0.8} L${cx - h},${cy + h * 0.8} Z`} fill={color} stroke={stroke} strokeWidth={2} />
  }
  return <circle cx={cx} cy={cy} r={size} fill={color} stroke={stroke} strokeWidth={2} />
}

function MapTip({ active, payload }: TooltipContentProps<ValueType, NameType>) {
  const p = active && payload?.[0]?.payload as MapPoint | undefined
  if (!p) return null
  return (
    <div className="rounded-lg border bg-background px-2.5 py-1.5 text-xs shadow-md">
      <p className="font-medium">Participant {p.nlst_pid} · {p.round}</p>
      <p className="text-muted-foreground">{p.diagnosed ? 'Diagnosed later' : 'Not diagnosed'}</p>
      <p className="font-mono tabular-nums">PC1 {p.x.toFixed(2)} · PC2 {p.y.toFixed(2)}</p>
      <p className="pt-1 text-muted-foreground">Click to open this participant</p>
    </div>
  )
}

/** Every scan on the first two principal components, each person's rounds joined in order. */
export function FeatureMap({ map, selected, onSelect, height = 420 }: {
  map: NonNullable<FeatureOverview['map']>
  selected: string | null
  onSelect: (pid: string) => void
  height?: number
}) {
  const people = new Map<string, MapPoint[]>()
  for (const p of map.points) people.set(p.nlst_pid, [...(people.get(p.nlst_pid) ?? []), p])
  // the selected person is drawn last, so it sits on top
  const order = [...people.keys()].sort((a, b) => Number(a === selected) - Number(b === selected))
  const config = { dx: { label: 'Diagnosed', color: DX_COLOR }, none: { label: 'Not diagnosed', color: NO_DX_COLOR } } satisfies ChartConfig
  const [e1, e2] = map.explained
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
      <ScatterChart margin={{ left: 4, right: 16, top: 12, bottom: 20 }}>
        <CartesianGrid strokeDasharray="2 4" />
        <XAxis type="number" dataKey="x" tickLine={false} axisLine={false} tickMargin={8}
          tickFormatter={(v: number) => v.toFixed(0)}
          label={{ value: `PC1 · ${(e1 * 100).toFixed(0)}% of the variation`, position: 'insideBottom', offset: -12, fontSize: 11 }} />
        <YAxis type="number" dataKey="y" tickLine={false} axisLine={false} width={40}
          tickFormatter={(v: number) => v.toFixed(0)}
          label={{ value: `PC2 · ${(e2 * 100).toFixed(0)}%`, angle: -90, position: 'insideLeft', offset: 12, fontSize: 11 }} />
        <ZAxis range={[60, 60]} />
        <Tooltip content={MapTip} cursor={false} />
        {order.map((pid) => {
          const pts = people.get(pid)!
          const isSel = pid === selected
          const color = isSel ? 'var(--foreground)' : dxColor(pts[0].diagnosed)
          const dim = selected != null && !isSel
          return (
            <Scatter key={pid} data={pts} isAnimationActive={false}
              line={{ stroke: color, strokeWidth: isSel ? 2.5 : 1.5, strokeOpacity: dim ? 0.35 : 0.85 }}
              onClick={() => onSelect(pid)} className="cursor-pointer"
              shape={(props: unknown) => {
                const { cx, cy, payload } = props as { cx: number; cy: number; payload: MapPoint }
                return (
                  <g opacity={dim ? 0.45 : 1}>
                    <RoundMarker cx={cx} cy={cy} round={payload.round} color={color} size={isSel ? 5.5 : 4} ring />
                  </g>
                )
              }} />
          )
        })}
      </ScatterChart>
    </ChartContainer>
  )
}

export function MapLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: DX_COLOR }} /> Diagnosed later</span>
      <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: NO_DX_COLOR }} /> Not diagnosed</span>
      <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-foreground" /> Selected</span>
      <span className="flex items-center gap-3 pl-2">
        {(['T0', 'T1', 'T2'] as const).map((r) => (
          <span key={r} className="flex items-center gap-1">
            <svg width="12" height="12" aria-hidden><RoundMarker cx={6} cy={6} round={r} color="var(--muted-foreground)" size={4} /></svg>
            {r}
          </span>
        ))}
      </span>
    </div>
  )
}

function HistTip({ active, payload, label }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border bg-background px-2.5 py-1.5 text-xs shadow-md">
      <p className="pb-1 font-medium">distance {String(label)}</p>
      {payload.map((e) => (
        <p key={String(e.name)} className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ background: e.color }} />
          {e.name}: <span className="font-mono tabular-nums">{(Number(e.value) * 100).toFixed(0)}%</span>
        </p>
      ))}
    </div>
  )
}

/** Share of pairs per distance bin: one person's two rounds vs two different people. */
export function DistanceHistogram({ bins, within, between, height = 220 }: {
  bins: number[]; within: number[]; between: number[]; height?: number
}) {
  const data = within.map((w, i) => ({
    bin: i === within.length - 1 ? `≥ ${bins[i].toFixed(1)}` : `${bins[i].toFixed(1)}–${bins[i + 1].toFixed(1)}`,
    within: w,
    between: between[i],
  }))
  const config = {
    within: { label: 'Same person, two rounds', color: WITHIN_COLOR },
    between: { label: 'Two different people', color: BETWEEN_COLOR },
  } satisfies ChartConfig
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
      <BarChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 20 }} barGap={2} barCategoryGap="12%">
        <CartesianGrid vertical={false} />
        <XAxis dataKey="bin" tickLine={false} axisLine={false} interval={1} fontSize={10}
          label={{ value: 'RMS standardized distance (√2 ≈ 1.41: two unrelated scans)', position: 'insideBottom', offset: -12, fontSize: 11 }} />
        <YAxis tickLine={false} axisLine={false} width={40} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
        <Tooltip content={HistTip} cursor={{ fill: 'var(--muted)', opacity: 0.5 }} />
        <Bar dataKey="within" name="Same person" fill={WITHIN_COLOR} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="between" name="Different people" fill={BETWEEN_COLOR} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  )
}

export type StripValue = { value: number; label: string; color: string }

/** Two rows of dots on one axis, with each row's median as a tick: small-n group comparison. */
export function StripPlot({ rows, unit }: { rows: { name: string; values: StripValue[] }[]; unit: string }) {
  const all = rows.flatMap((r) => r.values.map((v) => v.value))
  const max = Math.max(0.1, ...all) * 1.05
  const W = 640, rowH = 44, left = 150, right = 16
  const x = (v: number) => left + (v / max) * (W - left - right)
  const ticks = Array.from({ length: 5 }, (_, i) => (max * i) / 4)
  const median = (vs: number[]) => {
    const s = [...vs].sort((a, b) => a - b)
    return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null
  }
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * rowH + 30}`} className="w-full" role="img"
      aria-label={rows.map((r) => `${r.name}: ${r.values.length} values, median ${median(r.values.map((v) => v.value))?.toFixed(3) ?? 'none'} ${unit}`).join('; ')}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={4} y2={rows.length * rowH} stroke="var(--border)" />
          <text x={x(t)} y={rows.length * rowH + 16} textAnchor="middle" fontSize={10} fill="var(--muted-foreground)">{t.toFixed(2)}</text>
        </g>
      ))}
      {rows.map((r, i) => {
        const cy = i * rowH + rowH / 2
        const m = median(r.values.map((v) => v.value))
        return (
          <g key={r.name}>
            <text x={0} y={cy + 4} fontSize={12} fill="var(--foreground)">{r.name}</text>
            <text x={0} y={cy + 18} fontSize={10} fill="var(--muted-foreground)">n = {r.values.length}</text>
            {r.values.map((v, k) => (
              // deterministic jitter so dots with equal values stay visible
              <circle key={k} cx={x(v.value)} cy={cy + (((k * 37) % 11) - 5) * 1.6} r={4.5} fill={v.color}
                stroke="var(--background)" strokeWidth={1.5} opacity={0.9}>
                <title>{`${v.label}: ${v.value.toFixed(3)} ${unit}`}</title>
              </circle>
            ))}
            {m != null && (
              <g>
                <line x1={x(m)} x2={x(m)} y1={cy - 16} y2={cy + 16} stroke="var(--foreground)" strokeWidth={2.5} />
                <text x={x(m) + 4} y={cy - 10} fontSize={10} fill="var(--foreground)">median {m.toFixed(3)}</text>
              </g>
            )}
          </g>
        )
      })}
      <text x={W - right} y={rows.length * rowH + 28} textAnchor="end" fontSize={10} fill="var(--muted-foreground)">{unit}</text>
    </svg>
  )
}

/** z in [-3, 3] -> the diverging pair, mixed from the muted midpoint. */
function zColor(z: number) {
  const t = Math.min(1, Math.abs(z) / 3)
  const pole = z < 0 ? 'var(--diverge-neg)' : 'var(--diverge-pos)'
  return `color-mix(in oklab, ${pole} ${Math.round(t * 100)}%, var(--muted))`
}

/** The dimensions that moved most, one row each, a column per round. */
export function FeatureHeatmap({ detail }: { detail: FeatureParticipant }) {
  const rounds = detail.rounds.map((r) => r.round)
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] border-separate border-spacing-[2px] text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th scope="col" className="px-2 py-1 text-left font-medium">Feature</th>
              {rounds.map((r) => (
                <th key={r} scope="col" className="px-2 py-1 font-medium" style={{ color: ROUND_COLOR[r] }}>{r}</th>
              ))}
              <th scope="col" className="px-2 py-1 text-right font-medium">Biggest step</th>
              {detail.top_features[0]?.risk_weight != null && (
                <th scope="col" className="px-2 py-1 text-right font-medium" title="Change in Sybil's 6-year logit for +1 SD of this feature">
                  Risk weight / SD
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {detail.top_features.map((f) => {
              const steps = f.z.slice(1).map((z, i) => z - f.z[i])
              const big = steps.length ? steps.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a)) : 0
              return (
                <tr key={f.label}>
                  <th scope="row" className="px-2 py-1 text-left font-mono font-normal whitespace-nowrap">{f.label}</th>
                  {f.z.map((z, i) => (
                    <td key={i} className={cn('rounded-[4px] px-2 py-1 text-center font-mono tabular-nums', Math.abs(z) > 1.8 && 'text-white')}
                      style={{ background: zColor(z) }}
                      title={`${f.label} at ${rounds[i]}: ${z >= 0 ? '+' : ''}${z.toFixed(2)} SD from the mean (raw ${f.raw[i].toFixed(3)})`}>
                      {z >= 0 ? '+' : ''}{z.toFixed(1)}
                    </td>
                  ))}
                  <td className="px-2 py-1 text-right font-mono tabular-nums">{big >= 0 ? '+' : ''}{big.toFixed(2)}</td>
                  {f.risk_weight != null && (
                    <td className="px-2 py-1 text-right font-mono tabular-nums text-muted-foreground">
                      {f.risk_weight >= 0 ? '+' : ''}{f.risk_weight.toFixed(4)}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>below the mean</span>
        <span className="h-2.5 w-40 rounded-full"
          style={{ background: 'linear-gradient(90deg, var(--diverge-neg), var(--muted), var(--diverge-pos))' }} aria-hidden />
        <span>above the mean</span>
        <span className="pl-2">(values are standard deviations across every scan; ±3 saturates)</span>
      </div>
    </div>
  )
}
