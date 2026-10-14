/**
 * Hand-drawn SVG diagrams for the research page. They share the round colours
 * and dash patterns of Explore's comparison chart, scale with their container,
 * and read in both themes because every colour is a CSS variable.
 */
import { ROUND_COLOR, ROUND_DASH } from '@/components/explore/shared'
import {
  EXAMPLE,
  nudged,
  offsets,
  type ScanCurve,
} from '@/lib/trajectory'
import { type ReactNode } from 'react'

type Frame = {
  w: number
  h: number
  m: { t: number; r: number; b: number; l: number }
  x: (v: number) => number
  y: (v: number) => number
}

function frame(w: number, h: number, xd: [number, number], yd: [number, number],
  m = { t: 16, r: 16, b: 40, l: 46 }): Frame {
  return {
    w, h, m,
    x: (v) => m.l + ((v - xd[0]) / (xd[1] - xd[0])) * (w - m.l - m.r),
    y: (v) => h - m.b - ((v - yd[0]) / (yd[1] - yd[0])) * (h - m.t - m.b),
  }
}

function Axes({ f, xs, ys, xLabel, yFmt = (v) => `${Math.round(v * 100)}%`, xFmt = (v) => String(v) }: {
  f: Frame
  xs: number[]
  ys: number[]
  xLabel: string
  yFmt?: (v: number) => string
  xFmt?: (v: number) => string
}) {
  return (
    <g className="text-muted-foreground" fontSize={11}>
      {ys.map((v) => (
        <g key={`y${v}`}>
          <line x1={f.m.l} x2={f.w - f.m.r} y1={f.y(v)} y2={f.y(v)} stroke="var(--border)" />
          <text x={f.m.l - 8} y={f.y(v)} dy="0.32em" textAnchor="end" fill="currentColor">{yFmt(v)}</text>
        </g>
      ))}
      {xs.map((v) => (
        <text key={`x${v}`} x={f.x(v)} y={f.h - f.m.b + 16} textAnchor="middle" fill="currentColor">{xFmt(v)}</text>
      ))}
      <text x={(f.m.l + f.w - f.m.r) / 2} y={f.h - 4} textAnchor="middle" fill="currentColor">{xLabel}</text>
    </g>
  )
}

/** A cumulative curve drawn from its scan date: (t, 0), then one point per year. */
function curvePath(f: Frame, scan: ScanCurve, offset = 0) {
  const pts = [[scan.t + offset, 0], ...scan.risk.map((r, i) => [scan.t + offset + i + 1, r])]
  return pts.map(([x, y], i) => `${i ? 'L' : 'M'}${f.x(x).toFixed(1)},${f.y(y).toFixed(1)}`).join('')
}

function Legend({ items }: { items: { label: string; color: string; dash?: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden>
            <line x1="1" x2="21" y1="4" y2="4" stroke={it.color} strokeWidth="2.5" strokeDasharray={it.dash} />
          </svg>
          {it.label}
        </li>
      ))}
    </ul>
  )
}

export function Figure({ title, caption, children }: { title: string; caption?: ReactNode; children: ReactNode }) {
  return (
    <figure className="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      {children}
      {caption && <p className="text-xs leading-relaxed text-muted-foreground">{caption}</p>}
    </figure>
  )
}

// ---------------------------------------------------------------------------
/** The hero: three scans of one person, each with its own six-year curve, on one calendar. */
export function CalendarDiagram() {
  const f = frame(720, 320, [0, 8.4], [0, 0.8])
  const [t0, t1] = EXAMPLE.scans
  const dx = EXAMPLE.diagnosisYears
  return (
    <div className="space-y-3">
      <svg viewBox={`0 0 ${f.w} ${f.h}`} className="w-full" role="img"
        aria-label="Three cumulative risk curves, one per screening scan, starting at 0.03, 0.95 and 2.08 years; the person was diagnosed at 2.28 years.">
        <rect x={f.x(t1.t)} width={f.x(t0.t + 6) - f.x(t1.t)} y={f.m.t} height={f.h - f.m.t - f.m.b}
          fill="var(--muted)" opacity={0.7} />
        <text x={(f.x(t1.t) + f.x(t0.t + 6)) / 2} y={f.m.t + 14} textAnchor="middle" fontSize={11}
          className="fill-muted-foreground">years both T0 and T1 predict</text>
        <Axes f={f} xs={[0, 1, 2, 3, 4, 5, 6, 7, 8]} ys={[0, 0.2, 0.4, 0.6, 0.8]} xLabel="years since enrolment" />
        <line x1={f.x(dx)} x2={f.x(dx)} y1={f.m.t + 22} y2={f.h - f.m.b} stroke="var(--outcome-cancer-text)" strokeWidth={2} />
        <text x={f.x(dx) + 6} y={f.m.t + 34} fontSize={11} fill="var(--outcome-cancer-text)">diagnosis, {EXAMPLE.stage}</text>
        {EXAMPLE.scans.map((s, k) => (
          <g key={s.round}>
            <path d={curvePath(f, s)} fill="none" stroke={ROUND_COLOR[s.round]} strokeWidth={2.5}
              strokeDasharray={ROUND_DASH[s.round]} className="draw-in" style={{ animationDelay: `${k * 0.35}s` }} />
            {s.risk.map((r, i) => (
              <circle key={i} cx={f.x(s.t + i + 1)} cy={f.y(r)} r={3.2} fill={ROUND_COLOR[s.round]}
                className="fade-in" style={{ animationDelay: `${0.6 + k * 0.35}s` }} />
            ))}
            <g transform={`translate(${f.x(s.t)},${f.h - f.m.b})`}>
              <path d="M0,0 l-5,-9 h10 z" fill={ROUND_COLOR[s.round]} />
              <text y={-14} textAnchor="middle" fontSize={11} fontWeight={600} fill={ROUND_COLOR[s.round]}>{s.round}</text>
            </g>
            {/* T1 ends right where T2's curve passes, so its label sits above-left instead */}
            <text x={f.x(s.t + 6) + (s.round === 'T1' ? -4 : 6)} y={f.y(s.risk[5]) - (s.round === 'T1' ? 12 : 0)}
              dy="0.32em" textAnchor={s.round === 'T1' ? 'end' : 'start'} fontSize={11} fill={ROUND_COLOR[s.round]}>
              {Math.round(s.risk[5] * 100)}%
            </text>
          </g>
        ))}
      </svg>
      <Legend items={EXAMPLE.scans.map((s) => ({
        label: `${s.round}: scan at ${s.t.toFixed(2)} y`, color: ROUND_COLOR[s.round], dash: ROUND_DASH[s.round],
      }))} />
    </div>
  )
}

// ---------------------------------------------------------------------------
/** T0's curve rebased onto T1's clock, next to T1's own curve, with the logit gap at each year. */
export function OffsetDiagram() {
  const [t0, t1] = EXAMPLE.scans
  const pts = offsets(t0, t1)
  const f = frame(560, 300, [0, 6], [0, 0.7])
  const line = (key: 'rebased' | 'fresh') =>
    `M${f.x(0)},${f.y(0)}` + pts.map((p) => `L${f.x(p.h).toFixed(1)},${f.y(p[key]).toFixed(1)}`).join('')
  return (
    <div className="space-y-3">
      <svg viewBox={`0 0 ${f.w} ${f.h}`} className="w-full" role="img"
        aria-label="On T1's clock, T0's rebased curve sits well below T1's own curve at every year from 1 to 5.">
        <defs>
          <marker id="arrow-up" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--foreground)" />
          </marker>
        </defs>
        <Axes f={f} xs={[0, 1, 2, 3, 4, 5, 6]} ys={[0, 0.2, 0.4, 0.6]} xLabel="years after the T1 scan (h)" />
        <path d={line('rebased')} fill="none" stroke={ROUND_COLOR.T0} strokeWidth={2.5} strokeDasharray="5 4" />
        <path d={line('fresh')} fill="none" stroke={ROUND_COLOR.T1} strokeWidth={2.5} />
        {pts.map((p) => (
          <g key={p.h}>
            <line x1={f.x(p.h)} x2={f.x(p.h)} y1={f.y(p.rebased) - 5} y2={f.y(p.fresh) + 7}
              stroke="var(--foreground)" strokeWidth={1.4} markerEnd="url(#arrow-up)" opacity={0.8} />
            <circle cx={f.x(p.h)} cy={f.y(p.rebased)} r={3.5} fill="var(--background)" stroke={ROUND_COLOR.T0} strokeWidth={2} />
            <circle cx={f.x(p.h)} cy={f.y(p.fresh)} r={3.5} fill={ROUND_COLOR.T1} />
            <text x={f.x(p.h) + 7} y={(f.y(p.rebased) + f.y(p.fresh)) / 2} dy="0.32em" fontSize={11} className="fill-foreground">
              δ={p.delta.toFixed(2)}
            </text>
          </g>
        ))}
      </svg>
      <Legend items={[
        { label: 'T0, rebased to T1 (conditioned on no cancer by T1)', color: ROUND_COLOR.T0, dash: '5 4' },
        { label: 'T1, as Sybil reads the new scan', color: ROUND_COLOR.T1 },
      ]} />
    </div>
  )
}

// ---------------------------------------------------------------------------
/** T1 carried to T2's clock, nudged by lambda * delta_01, against T2's own curve. */
export function NudgeDiagram({ lambda }: { lambda: number }) {
  const [t0, t1, t2] = EXAMPLE.scans
  const pts = nudged(t0, t1, t2, lambda)
  const f = frame(560, 300, [0, 5], [0, 0.8])
  const path = (key: 'carried' | 'nudged' | 'actual') =>
    `M${f.x(0)},${f.y(0)}` + pts.map((p) => `L${f.x(p.h).toFixed(1)},${f.y(p[key]).toFixed(1)}`).join('')
  return (
    <div className="space-y-3">
      <svg viewBox={`0 0 ${f.w} ${f.h}`} className="w-full" role="img"
        aria-label={`With lambda ${lambda.toFixed(2)}, the nudged T1 curve is compared with T2's own curve on T2's clock.`}>
        <Axes f={f} xs={[0, 1, 2, 3, 4, 5]} ys={[0, 0.2, 0.4, 0.6, 0.8]} xLabel="years after the T2 scan (h)" />
        <path d={path('carried')} fill="none" stroke={ROUND_COLOR.T1} strokeWidth={2} strokeDasharray="5 4" opacity={0.7} />
        <path d={path('actual')} fill="none" stroke={ROUND_COLOR.T2} strokeWidth={2.5} />
        <path d={path('nudged')} fill="none" stroke="var(--risk-5)" strokeWidth={3} />
        {pts.map((p) => (
          <g key={p.h}>
            <line x1={f.x(p.h)} x2={f.x(p.h)} y1={f.y(p.carried)} y2={f.y(p.nudged)}
              stroke="var(--risk-5)" strokeWidth={1} strokeDasharray="2 3" />
            <circle cx={f.x(p.h)} cy={f.y(p.actual)} r={4} fill={ROUND_COLOR.T2} />
            <circle cx={f.x(p.h)} cy={f.y(p.nudged)} r={3.5} fill="var(--background)" stroke="var(--risk-5)" strokeWidth={2.2} />
          </g>
        ))}
      </svg>
      <Legend items={[
        { label: 'T1 carried forward to T2 (λ = 0)', color: ROUND_COLOR.T1, dash: '5 4' },
        { label: 'T1 nudged by λ·δ₀₁', color: 'var(--risk-5)' },
        { label: 'T2, as Sybil reads the third scan', color: ROUND_COLOR.T2 },
      ]} />
    </div>
  )
}

// ---------------------------------------------------------------------------
/** How one scan becomes six numbers: base hazard plus a running sum of yearly hazards, then a sigmoid. */
export function HazardStackDiagram({ base, hazards }: { base: number; hazards: number[] }) {
  const cum = hazards.map((_, i) => base + hazards.slice(0, i + 1).reduce((a, b) => a + b, 0))
  const lo = Math.min(0, base, ...cum) - 0.2
  const hi = Math.max(0, ...cum) + 0.3
  const f = frame(560, 260, [0.4, 6.6], [lo, hi], { t: 16, r: 16, b: 40, l: 46 })
  const bw = (f.x(1) - f.x(0)) * 0.5
  return (
    <svg viewBox={`0 0 ${f.w} ${f.h}`} className="w-full" role="img"
      aria-label="Six stacked bars: each year's logit is the base hazard plus every yearly hazard up to that year.">
      <Axes f={f} xs={[1, 2, 3, 4, 5, 6]} ys={[]} xLabel="year h" xFmt={(v) => `F(${v})`} />
      <line x1={f.m.l} x2={f.w - f.m.r} y1={f.y(0)} y2={f.y(0)} stroke="var(--foreground)" opacity={0.4} />
      <text x={f.m.l - 8} y={f.y(0)} dy="0.32em" textAnchor="end" fontSize={11} className="fill-muted-foreground">0</text>
      {hazards.map((_, i) => {
        const h = i + 1
        let y0 = 0
        const parts = [{ v: base, color: 'var(--reference-line)' },
          ...hazards.slice(0, h).map((v, j) => ({ v, color: j === i ? 'var(--risk-5)' : 'var(--risk-3)' }))]
        return (
          <g key={h}>
            {parts.map((p, j) => {
              const a = y0
              y0 += p.v
              const top = f.y(Math.max(a, y0))
              const height = Math.abs(f.y(a) - f.y(y0))
              return <rect key={j} x={f.x(h) - bw / 2} y={top} width={bw} height={Math.max(height, 0.5)}
                fill={p.color} opacity={0.9} stroke="var(--background)" strokeWidth={0.5} />
            })}
            <text x={f.x(h)} y={f.y(cum[i]) - 6} textAnchor="middle" fontSize={10.5} className="fill-foreground">
              σ→{(100 / (1 + Math.exp(-cum[i]))).toFixed(0)}%
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export const PIPELINE_STEPS = [
  { title: 'Cohort', body: '19,758 NLST participants with three readable screening scans (T0, T1, T2); 458 later diagnosed.' },
  { title: 'Read every scan', body: 'Sybil\'s 5-model ensemble on each scan on its own: three curves per person, F₀, F₁, F₂.' },
  { title: 'One clock', body: 'Rebase each earlier curve on surviving cancer-free to the next scan date.' },
  { title: 'Offsets', body: 'δ₀₁(h) = logit F₁(h) − logit F̃₀→₁(h) for every year both scans cover.' },
  { title: 'Fit', body: 'α_h, λ_h by least squares on training participants only (cross-validated).' },
  { title: 'Evaluate', body: 'Held-out: closeness to T2\'s curve, and AUC / C-index / Brier against real diagnoses.' },
]

/** Slightly fancier than a list: the study as a left-to-right pipeline. */
export function PipelineDiagram() {
  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
      {PIPELINE_STEPS.map((step, i) => (
        <li key={step.title} className="relative rounded-xl border bg-card p-3">
          <span className="mb-2 flex size-7 items-center justify-center rounded-full bg-foreground text-xs font-semibold text-background">
            {i + 1}
          </span>
          <p className="text-sm font-medium">{step.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.body}</p>
          {i < PIPELINE_STEPS.length - 1 && (
            <span aria-hidden className="absolute top-1/2 -right-2.5 z-10 hidden size-5 -translate-y-1/2 items-center justify-center rounded-full border bg-background text-[10px] text-muted-foreground lg:flex">
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  )
}

