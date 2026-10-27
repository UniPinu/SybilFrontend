import { ClockChart, NetworkDiagram, ScanTimeline, SeriesLegend, type Series } from '@/components/experiment/charts'
import { ROUND_COLOR, ROUND_DASH } from '@/components/explore/shared'
import { Tex } from '@/components/Tex'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api, ApiError, READ_ONLY, type TrajectoryGuide } from '@/lib/api'
import { YEARS, riskColor, riskTextColor } from '@/lib/format'
import { goTo, setParams, useSearchParams } from '@/lib/url'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Check, Code2, FlaskConical, Lightbulb, X } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'

const DEFAULT_PID = '217203'
const CURVE_COLOR = 'var(--foreground)'

const STEPS = [
  'Run Sybil three times',
  'Each scan has its own clock',
  'Move T1 onto T0’s clock',
  'One continuous curve',
  'Read T2 off the curve',
  'The 13-input network',
  'Train and compare',
  'What one person tells us',
]

const pp = (v: number) => `${v.toFixed(1)} pp`
const pc = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`

// --- layout -------------------------------------------------------------------

function Step({ n, title, lede, code, children }: {
  n: number
  title: string
  lede: ReactNode
  code?: { file: string; text: string }
  children: ReactNode
}) {
  return (
    <li id={`exp-${n}`} className="section-anchor relative grid grid-cols-[2.5rem_1fr] gap-x-4 sm:grid-cols-[3rem_1fr] sm:gap-x-6">
      <div className="flex flex-col items-center">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full border-2 border-primary bg-background text-sm font-semibold tabular-nums sm:size-12 sm:text-base">
          {n}
        </span>
        {n < STEPS.length && <span className="w-0.5 flex-1 bg-border" aria-hidden />}
      </div>
      <div className="min-w-0 space-y-5 pb-16">
        <header className="space-y-2 pt-1.5 sm:pt-2.5">
          <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">Step {n}</p>
          <h2 className="text-xl font-semibold sm:text-2xl">{title}</h2>
          <div className="max-w-3xl leading-relaxed text-muted-foreground">{lede}</div>
        </header>
        {children}
        {code && (
          <div className="flex flex-col gap-1.5 rounded-lg border bg-muted/40 px-3 py-2 sm:flex-row sm:items-start sm:gap-3">
            <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
              <Code2 className="size-3.5" aria-hidden /> {code.file}
            </span>
            <pre className="min-w-0 overflow-x-auto font-mono text-[11px] whitespace-pre text-foreground/80">{code.text}</pre>
          </div>
        )}
      </div>
    </li>
  )
}

function Panel({ title, caption, children }: { title: string; caption?: ReactNode; children: ReactNode }) {
  return (
    <figure className="min-w-0 space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      {children}
      {caption && <p className="text-xs leading-relaxed text-muted-foreground">{caption}</p>}
    </figure>
  )
}

function Equation({ tex, children }: { tex: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border bg-muted/30 px-4 py-3">
      <Tex tex={tex} block />
      {children && <div className="pt-1 text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

// --- the page -------------------------------------------------------------------

export function ExperimentView() {
  const params = useSearchParams()
  const pid = params.get('pid') || DEFAULT_PID
  const query = useQuery({
    queryKey: ['trajectory-guide', pid],
    queryFn: () => api.trajectoryGuide(pid),
    retry: false,
  })

  return (
    <div className="space-y-12 pt-10">
      <Hero pid={pid} guide={query.data} />
      {query.isPending && <Skeleton className="h-[480px] w-full rounded-xl" />}
      {query.isError && <NotAvailable pid={pid} error={query.error} />}
      {query.data && (
        <ol className="list-none">
          <StepScans g={query.data} />
          <StepOwnClocks g={query.data} />
          <StepAlign g={query.data} />
          <StepCurve g={query.data} />
          <StepForecast g={query.data} />
          <StepNetwork g={query.data} />
          <StepTrain g={query.data} />
          <StepFindings g={query.data} />
        </ol>
      )}
    </div>
  )
}

function Hero({ pid, guide }: { pid: string; guide?: TrajectoryGuide }) {
  const inputId = useId()
  const [draft, setDraft] = useState(pid)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const next = draft.trim()
    if (next) setParams({ pid: next === DEFAULT_PID ? null : next })
  }
  const o = guide?.outcome
  return (
    <section className="space-y-6">
      <div className="space-y-4">
        <Badge variant="outline" className="gap-1.5"><FlaskConical className="size-3.5" aria-hidden /> Experiment · worked example</Badge>
        <h1 className="max-w-3xl text-4xl leading-tight font-semibold text-balance sm:text-5xl">
          From two scans to a forecast of the third
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          This is how the T0 + T1 → T2 experiment works, step by step, on one real NLST participant. Every
          number and curve below is computed live by the same code the experiment scripts use
          (<code className="text-sm">backend/app/trajectory.py</code>), so the page and the scripts cannot disagree.
        </p>
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-muted/30 p-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Participant</p>
          <p className="text-xl font-semibold tabular-nums">{pid}</p>
          {o && (
            <p className="text-sm text-muted-foreground">
              {o.diagnosed
                ? `Diagnosed with lung cancer ${o.years_rand_to_dx?.toFixed(2)} years after enrolment${o.stage ? `, ${o.stage}` : ''}.`
                : 'No lung-cancer diagnosis during follow-up.'}
            </p>
          )}
        </div>
        <form onSubmit={submit} className="flex items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor={inputId} className="text-xs">Another participant with T0, T1 and T2 run</Label>
            <Input id={inputId} value={draft} onChange={(e) => setDraft(e.target.value)} inputMode="numeric" className="w-40" />
          </div>
          <Button type="submit" variant="outline">Show</Button>
        </form>
      </div>

      <nav aria-label="Steps" className="flex flex-wrap gap-2">
        {STEPS.map((title, i) => (
          <a key={title} href={`#exp-${i + 1}`}
            className="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-muted">
            <span className="font-semibold tabular-nums">{i + 1}</span> {title}
          </a>
        ))}
      </nav>
    </section>
  )
}

function NotAvailable({ pid, error }: { pid: string; error: Error }) {
  const notRun = error instanceof ApiError && error.status === 409
  return (
    <Alert>
      <AlertDescription className="space-y-3">
        <p>{error.message}</p>
        <div className="flex flex-wrap gap-2">
          {notRun && !READ_ONLY && (
            <Button size="sm" onClick={() => goTo({ view: 'explore', participant: pid })}>
              Open {pid} in Explore <ArrowRight aria-hidden />
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setParams({ pid: null })}>
            Back to participant {DEFAULT_PID}
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  )
}

// --- step 1 -------------------------------------------------------------------

function RiskGrid({ g }: { g: TrajectoryGuide }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <caption className="sr-only">Sybil's six risks for each of the three scans</caption>
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">Scan</th>
            {YEARS.map((y) => <th key={y} scope="col" className="px-2 py-2 text-right font-medium">{y} y</th>)}
          </tr>
        </thead>
        <tbody>
          {g.scans.map((s) => (
            <tr key={s.round} className="border-t">
              <th scope="row" className="px-3 py-2 text-left font-medium whitespace-nowrap">
                <span className="mr-1.5 inline-block size-2.5 rounded-full" style={{ background: ROUND_COLOR[s.round] }} aria-hidden />
                {s.round}
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">{s.round === 'T2' ? 'target' : 'input'}</span>
              </th>
              {s.risk_by_year.map((r, i) => (
                <td key={i} className="px-1 py-1 text-right">
                  <span className="inline-block min-w-14 rounded-md px-1.5 py-1 font-mono text-xs tabular-nums"
                    style={{ background: `color-mix(in oklab, ${riskColor(r)} 22%, transparent)`, color: riskTextColor(r) }}>
                    {pc(r)}
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StepScans({ g }: { g: TrajectoryGuide }) {
  return (
    <Step n={1} title="Run Sybil on three consecutive screening scans"
      lede={<>Sybil reads one CT scan and returns six numbers: the chance of a lung-cancer diagnosis within 1, 2, … 6 years
        of <em>that</em> scan. We ran it on this person&rsquo;s three yearly screens, T0, T1 and T2: 18 numbers in all.
        T0 and T1 are what the models get to see; T2 is what they try to predict.</>}
      code={{ file: 'backend/scripts/build_trajectories.py', text: 'for r in (0, 1, 2):\n    risks = process_patient(f"{pid}_T{r}").risk_by_year   # 6 numbers per scan\nappend(out, row)                                        # → data/trajectories.csv' }}>
      <Panel title="When the scans were taken"
        caption={<>The gap between the first two scans, <strong>Δ</strong>, is the 13th input of the network in step 6. It
          is never exactly one year: here it is {g.offset.toFixed(2)} years, and T2 came {g.t2_offset.toFixed(2)} years after T0.</>}>
        <ScanTimeline guide={g} />
      </Panel>
      <Panel title="The 18 numbers" caption="Cumulative risk, so each row only goes up. The colour follows the risk band used across the site.">
        <RiskGrid g={g} />
      </Panel>
    </Step>
  )
}

// --- step 2 -------------------------------------------------------------------

function StepOwnClocks({ g }: { g: TrajectoryGuide }) {
  const series: Series[] = g.scans.map((s) => ({
    key: s.round, label: `${s.round} (from its own date)`, color: ROUND_COLOR[s.round], dash: ROUND_DASH[s.round], dots: true,
    data: s.risk_by_year.map((r, i) => ({ x: i + 1, y: r * 100 })),
  }))
  return (
    <Step n={2} title="Each scan speaks on its own clock"
      lede={<>Drawn the way Sybil reports them, all three curves start at &ldquo;year 1&rdquo;. But year 1 of T1 is
        about year 2 of T0. Comparing the curves point by point like this mixes up different stretches of time,
        which is why the next step moves them onto one shared clock.</>}
      code={{ file: 'Sybil output', text: 'risk_by_year[k] = P(diagnosis within k + 1 years of this scan | cancer-free at this scan)' }}>
      <Panel title="As Sybil reports them: years after each scan">
        <ClockChart series={series} xMin={1} xMax={6} xLabel="years after that scan" />
        <SeriesLegend series={series} />
      </Panel>
    </Step>
  )
}

// --- step 3 -------------------------------------------------------------------

function StepAlign({ g }: { g: TrajectoryGuide }) {
  const { align } = g
  const series: Series[] = [
    { key: 't0', label: 'T0, as reported', color: ROUND_COLOR.T0, dots: true,
      data: [{ x: 0, y: 0 }, ...align.t0.map((p) => ({ x: p.t, y: p.risk * 100 }))] },
    { key: 'shift', label: 'T1, only shifted by Δ', color: ROUND_COLOR.T1, dash: '3 4', opacity: 0.4, width: 1.5, dots: true,
      data: align.t1_shifted.map((p) => ({ x: p.t, y: p.risk * 100 })) },
    { key: 't1', label: 'T1, on T0’s clock', color: ROUND_COLOR.T1, dash: ROUND_DASH.T1, dots: true,
      data: [{ x: g.offset, y: align.base * 100 }, ...align.t1_on_t0_clock.map((p) => ({ x: p.t, y: p.risk * 100 }))] },
  ]
  return (
    <Step n={3} title="Move T1 onto T0’s clock"
      lede={<>Shifting T1 right by Δ is not enough. T1&rsquo;s numbers are risks <em>given</em> that the person was still
        cancer-free at T1, but T0&rsquo;s curve already counts the risk up to that point. So T1&rsquo;s risk is added on top
        of what T0 says had built up by then, F<sub>0</sub>(Δ), and only applied to the share still cancer-free.</>}
      code={{ file: 'backend/app/trajectory.py', text: 'f0, f1, base = curve_parts(r0, r1, offset)   # base = F0(Δ), read off T0’s curve\n# T1 points:  base + (1 - base) * r1[k]' }}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.3fr]">
        <div className="space-y-4">
          <Equation tex={String.raw`F(\Delta + k) \;=\; F_0(\Delta) \;+\; \big(1 - F_0(\Delta)\big)\, r_1(k), \qquad k = 1,\dots,6`}>
            <Tex tex="r_1(k)" /> is T1&rsquo;s k-year risk; <Tex tex={String.raw`F_0(\Delta)`} /> is T0&rsquo;s curve read at T1&rsquo;s date.
          </Equation>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Δ, T0 → T1" value={`${g.offset.toFixed(2)} y`} />
            <Stat label="F₀(Δ), risk built up by T1" value={pc(align.base)} hint="according to T0" />
          </div>
        </div>
        <Panel title="Both scans on one clock: years after T0"
          caption={<>The faint points are T1 merely shifted; the solid ones are T1 after the conversion, which lifts them by{' '}
            {pc(align.t1_on_t0_clock[5].risk - align.t1_shifted[5].risk)} to {pc(align.t1_on_t0_clock[0].risk - align.t1_shifted[0].risk)}.
            Between T1 and year 6 there are now two estimates, one from each scan.</>}>
          <ClockChart series={series} xMax={Math.ceil(g.offset + 6)} xLabel="years after T0"
            markers={[{ x: g.offset, label: 'T1', color: ROUND_COLOR.T1 }]} />
          <SeriesLegend series={series} />
        </Panel>
      </div>
    </Step>
  )
}

// --- step 4 -------------------------------------------------------------------

function StepCurve({ g }: { g: TrajectoryGuide }) {
  const end = 6 + g.offset
  const pts = g.curve.filter((p) => p.t <= end + 1e-9)
  const series: Series[] = [
    { key: 'f0', label: 'T0 alone', color: ROUND_COLOR.T0, width: 1.5, opacity: 0.55,
      data: pts.flatMap((p) => (p.t0_only == null ? [] : [{ x: p.t, y: p.t0_only * 100 }])) },
    { key: 'f1', label: 'T1 alone (on T0’s clock)', color: ROUND_COLOR.T1, width: 1.5, opacity: 0.55, dash: ROUND_DASH.T1,
      data: pts.flatMap((p) => (p.t1_only == null ? [] : [{ x: p.t, y: p.t1_only * 100 }])) },
    { key: 'combined', label: 'Combined curve', color: CURVE_COLOR, width: 3,
      data: pts.map((p) => ({ x: p.t, y: p.combined * 100 })) },
  ]
  const weight: Series[] = [{ key: 'w', label: 'weight on T1', color: ROUND_COLOR.T1,
    data: pts.map((p) => ({ x: p.t, y: p.weight * 100 })) }]
  return (
    <Step n={4} title="Join the points into one continuous curve"
      lede={<>Each scan&rsquo;s seven points (including 0 at its own date) are joined by a <strong>monotone cubic</strong>{' '}
        (PCHIP). Unlike an ordinary spline it never overshoots, so a rising set of risks gives a rising curve. Where the two
        scans overlap, the combined curve slides gradually from trusting T0 to trusting the newer T1, so it has no jumps.</>}
      code={{ file: 'backend/app/trajectory.py', text: 'w = blend_weight(t, offset)                     # 0 at T1, 1 from year 6\ncurve = (1 - w) * f0(t) + w * f1(t)             # combined_curve(r0, r1, offset)' }}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.3fr_1fr]">
        <Panel title="The continuous risk curve, years after T0"
          caption="Thin lines: each scan on its own. Thick line: the blend that the next step reads from.">
          <ClockChart series={series} xMax={Math.ceil(end)} xLabel="years after T0"
            markers={[{ x: g.offset, label: 'T1', color: ROUND_COLOR.T1 }, { x: 6, label: 'T0 ends' }]} />
          <SeriesLegend series={series} />
        </Panel>
        <div className="space-y-4">
          <Equation tex={String.raw`F(t) = \big(1 - w(t)\big)\,F_{T0}(t) + w(t)\,F_{T1}(t)`}>
            <Tex tex={String.raw`w(t) = \min\!\Big(1, \max\!\big(0, \tfrac{t - \Delta}{6 - \Delta}\big)\Big)`} />: 0 up to T1&rsquo;s date,
            1 from the last year T0 covers.
          </Equation>
          <Panel title="How much the curve trusts T1">
            <ClockChart series={weight} xMax={Math.ceil(end)} xLabel="years after T0" yMax={100} height={150} />
          </Panel>
        </div>
      </div>
    </Step>
  )
}

// --- step 5 -------------------------------------------------------------------

function StepForecast({ g }: { g: TrajectoryGuide }) {
  const f = g.forecast
  const end = f.at + 6
  const curve: Series[] = [{ key: 'c', label: 'Combined curve', color: CURVE_COLOR, width: 3,
    data: g.curve.map((p) => ({ x: p.t, y: p.combined * 100 })) }]
  const onT2: Series[] = [
    { key: 'sybil', label: 'Sybil on T2 (the truth here)', color: ROUND_COLOR.T2, width: 3, dots: true,
      data: f.sybil_t2.map((v, i) => ({ x: i + 1, y: v * 100 })) },
    { key: 'curve', label: 'Read off the curve', color: CURVE_COLOR, dash: '6 3', dots: true,
      data: f.curve.map((v, i) => ({ x: i + 1, y: v * 100 })) },
    { key: 'persist', label: 'Guess “T2 = T1”', color: ROUND_COLOR.T1, dash: ROUND_DASH.T1, dots: true,
      data: f.persistence.map((v, i) => ({ x: i + 1, y: v * 100 })) },
  ]
  const curveWins = f.curve_mae_pp < f.persistence_mae_pp
  return (
    <Step n={5} title="Read T2’s six numbers off the curve"
      lede={<>T2 was taken {f.at.toFixed(2)} years after T0. Sybil on T2 again reports risk <em>given</em> cancer-free at
        T2, so the curve is read the opposite way to step 3: take the rise over the next k years and divide by the share
        still cancer-free. This needs no training at all, so it is the first baseline. The second is simpler still: assume T2
        will say exactly what T1 said.</>}
      code={{ file: 'backend/app/trajectory.py', text: 'curve_forecast(curve, at=t2_offset)   # (F(at + k) - F(at)) / (1 - F(at))\npersistence(traj)                     # T2 = T1' }}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel title="Where T2 sits on the curve"
          caption={<>Shaded: the six years T2 is asked about. By T2&rsquo;s date the curve has already reached {pc(f.curve_at_t2)};
            beyond about year {(g.offset + 6).toFixed(1)} it is extrapolated from T1&rsquo;s last slope.</>}>
          <ClockChart series={curve} xMax={Math.ceil(end)} xLabel="years after T0"
            markers={[{ x: f.at, label: 'T2', color: ROUND_COLOR.T2 }]}
            band={{ from: f.at, to: end, label: 'T2’s six years' }} />
        </Panel>
        <Panel title="On T2’s clock: forecast vs Sybil’s actual T2">
          <ClockChart series={onT2} xMin={1} xMax={6} xLabel="years after T2" />
          <SeriesLegend series={onT2} />
        </Panel>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <caption className="sr-only">Forecast errors per year</caption>
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">Prediction of T2</th>
              {YEARS.map((y) => <th key={y} scope="col" className="px-2 py-2 text-right font-medium">{y} y</th>)}
              <th scope="col" className="px-3 py-2 text-right font-medium">Mean error</th>
            </tr>
          </thead>
          <tbody className="font-mono text-xs tabular-nums">
            <tr className="border-t">
              <th scope="row" className="px-3 py-2 text-left font-sans text-sm font-medium">Sybil on T2</th>
              {f.sybil_t2.map((v, i) => <td key={i} className="px-2 py-2 text-right">{pc(v)}</td>)}
              <td className="px-3 py-2 text-right text-muted-foreground">target</td>
            </tr>
            {([['Curve', f.curve, f.curve_mae_pp, curveWins], ['T2 = T1', f.persistence, f.persistence_mae_pp, !curveWins]] as const).map(
              ([name, pred, mae, best]) => (
                <tr key={name} className="border-t">
                  <th scope="row" className="px-3 py-2 text-left font-sans text-sm font-medium">{name}</th>
                  {pred.map((v, i) => {
                    const err = Number(((v - f.sybil_t2[i]) * 100).toFixed(1)) || 0  // no "-0.0"
                    return (
                      <td key={i} className="px-2 py-2 text-right">
                        {pc(v)}
                        <span className={`block text-[10px] ${Math.abs(err) > 10 ? 'text-[var(--outcome-cancer-text)]' : 'text-muted-foreground'}`}>
                          {err > 0 ? '+' : ''}{err.toFixed(1)}
                        </span>
                      </td>
                    )
                  })}
                  <td className={`px-3 py-2 text-right ${best ? 'font-semibold' : ''}`}>
                    {pp(mae)} {best && <Check className="inline size-3.5" aria-label="better" />}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Step>
  )
}

// --- step 6 -------------------------------------------------------------------

function StepNetwork({ g }: { g: TrajectoryGuide }) {
  const switchId = useId()
  const [withOffset, setWithOffset] = useState(true)
  return (
    <Step n={6} title="Let a small network learn the correction"
      lede={<>The curve encodes one fixed assumption about how risk carries over. A model can instead <em>learn</em> how
        T0 and T1 relate to T2 across many people. The inputs are the 12 risks plus Δ; the outputs are T2&rsquo;s six risks.
        To answer &ldquo;does the offset help?&rdquo;, every model is trained twice: with all 13 inputs and with Δ removed.</>}
      code={{ file: 'backend/app/trajectory.py', text: 'X, Y = design(traj, with_offset=True)   # logit(T0) ×6, logit(T1) ×6, Δ  →  logit(T2) ×6\nMLP(hidden=8).fit(X, Y)                 # tanh layer, Adam, hand-written backprop in numpy\nLinearRegression().fit(X, Y)            # the same without a hidden layer' }}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Panel title={`The network, with participant ${g.nlst_pid}’s inputs`}
          caption="Left: the values as Sybil reported them. The network actually sees their logits, standardised over the training set, so 1% → 2% counts as much as 33% → 50%.">
          <div className="flex items-center gap-2">
            <Switch id={switchId} checked={withOffset} onCheckedChange={setWithOffset} />
            <Label htmlFor={switchId} className="text-sm">Include Δ (the 13th input)</Label>
          </div>
          <NetworkDiagram guide={g} withOffset={withOffset} />
        </Panel>
        <div className="space-y-4">
          <Equation tex={String.raw`\hat{\mathbf y} = \sigma\!\big(W_2 \tanh(W_1 \mathbf x + \mathbf b_1) + \mathbf b_2\big)`}>
            <Tex tex={String.raw`\mathbf x = \big[\operatorname{logit} r_0(1..6),\ \operatorname{logit} r_1(1..6),\ \Delta\big]`} />,{' '}
            <Tex tex={String.raw`\hat{\mathbf y}`} /> = T2&rsquo;s six risks.
          </Equation>
          <ul className="space-y-2 text-sm text-muted-foreground">
            <li className="flex gap-2"><Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <span><strong className="text-foreground">13 → 8 → 6:</strong> 166 weights. Small on purpose: with tens of people, anything bigger memorises them.</span></li>
            <li className="flex gap-2"><Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <span><strong className="text-foreground">Regularised:</strong> 500 full-batch Adam steps with weight decay 0.01. Longer training overfitted in tests on synthetic people.</span></li>
            <li className="flex gap-2"><Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <span><strong className="text-foreground">Rising outputs:</strong> predictions are forced to be non-decreasing over the six years, like any cumulative risk.</span></li>
          </ul>
        </div>
      </div>
    </Step>
  )
}

// --- step 7 -------------------------------------------------------------------

function StepTrain({ g }: { g: TrajectoryGuide }) {
  const d = g.dataset
  const ready = d.metrics != null
  return (
    <Step n={7} title="Train on many people, test on people the model never saw"
      lede={<>One person can show <em>how</em> the method works, but not whether it works. The models are scored with
        repeated 5-fold cross-validation: each person&rsquo;s T2 is predicted by a model trained only on the others. A
        paired bootstrap then says whether &ldquo;with Δ&rdquo; beats &ldquo;without Δ&rdquo; by more than chance.</>}
      code={{ file: 'backend', text: 'uv run python scripts/build_trajectories.py --n 100 --cancer-share 0.3   # ~4.5 min of Sybil per person\nuv run python scripts/fit_trajectory.py                                  # the comparison table' }}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_1.4fr]">
        <Panel title="Training data so far">
          <div className="flex items-baseline justify-between">
            <span className="text-3xl font-semibold tabular-nums">{d.n_participants}</span>
            <span className="text-sm text-muted-foreground">of at least {d.min_needed} participants</span>
          </div>
          <Progress value={Math.min(100, (d.n_participants / d.min_needed) * 100)} aria-label="training participants collected" />
          <p className="text-xs text-muted-foreground">
            In <code>{d.file}</code>. {d.includes_this_participant ? `Participant ${g.nlst_pid} is one of them.` : `Participant ${g.nlst_pid} is not in it yet.`}
            {' '}Ten is the bare minimum for 5-fold cross-validation; a meaningful answer needs a hundred or more.
          </p>
        </Panel>
        {ready ? <Results g={g} /> : (
          <Panel title="Results appear here once the data is in">
            <p className="text-sm text-muted-foreground">
              Building the dataset means running Sybil on three scans per person, about 4.5 minutes each on a 16-thread CPU.
              That is an overnight job, which is what the university PC is for. When <code>trajectories.csv</code> has
              enough rows, this step shows each model&rsquo;s cross-validated error and the with/without-Δ verdict,
              without any change to the page.
            </p>
            <ul className="grid gap-2 text-sm sm:grid-cols-2">
              {['T2 = T1', 'Curve (step 5)', 'Linear, 12 vs 13 inputs', 'MLP, 12 vs 13 inputs'].map((m) => (
                <li key={m} className="rounded-lg border border-dashed px-3 py-2 text-muted-foreground">{m}</li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </Step>
  )
}

function Results({ g }: { g: TrajectoryGuide }) {
  const d = g.dataset
  const metrics = Object.entries(d.metrics ?? {})
  const best = Math.min(...metrics.map(([, m]) => m.mae_pp))
  return (
    <Panel title={`Cross-validated error on ${d.n_participants} participants`}
      caption="Mean absolute difference from Sybil’s real T2, in percentage points, averaged over the six years. Lower is better.">
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">Model</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">MAE</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">6-year MAE</th>
              {d.this_participant && <th scope="col" className="px-3 py-2 text-right font-medium">{g.nlst_pid}, 6 y</th>}
            </tr>
          </thead>
          <tbody className="font-mono text-xs tabular-nums">
            {metrics.map(([name, m]) => (
              <tr key={name} className="border-t">
                <th scope="row" className="px-3 py-2 text-left font-sans text-sm font-medium">{name}</th>
                <td className={`px-3 py-2 text-right ${m.mae_pp === best ? 'font-semibold' : ''}`}>{pp(m.mae_pp)}</td>
                <td className="px-3 py-2 text-right">{pp(m.mae_6y_pp)}</td>
                {d.this_participant && (
                  <td className="px-3 py-2 text-right">{d.this_participant[name] ? pc(d.this_participant[name][5]) : '—'}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-2">
        {(d.offset_effect ?? []).map((e) => {
          const verdict = e.hi < 0 ? 'Δ helps' : e.lo > 0 ? 'Δ hurts' : 'no clear difference'
          return (
            <li key={e.with} className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm">
              <span className="font-medium">{e.with}</span>
              <span className="text-muted-foreground">vs without Δ:</span>
              <span className="font-mono text-xs tabular-nums">{e.mean > 0 ? '+' : ''}{e.mean.toFixed(2)} pp [{e.lo.toFixed(2)}, {e.hi.toFixed(2)}]</span>
              <Badge variant={verdict === 'Δ helps' ? 'default' : 'outline'}>{verdict}</Badge>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

// --- step 8 -------------------------------------------------------------------

function StepFindings({ g }: { g: TrajectoryGuide }) {
  const f = g.forecast
  const early = f.curve[0] - f.sybil_t2[0]
  const persistenceBetter = f.persistence_mae_pp < f.curve_mae_pp
  const findings = [
    early < -0.02
      ? {
          kind: 'miss' as const,
          title: 'The curve misses T2’s year-1 jump',
          text: <>Sybil reports a high year-1 risk for T2 ({pc(f.sybil_t2[0])}), probably because a new scan can see disease that
            is already there. The curve spreads risk smoothly over time and predicts {pc(f.curve[0])}, which is {Math.abs(early * 100).toFixed(1)} points
            too low. Consecutive scans do not lie on one shared curve.</>,
        }
      : {
          kind: 'hit' as const,
          title: 'The curve gets T2’s first year about right',
          text: <>Sybil says {pc(f.sybil_t2[0])} for T2&rsquo;s first year and the curve predicts {pc(f.curve[0])}. For this person,
            consecutive scans are consistent with one shared curve.</>,
        },
    {
      kind: persistenceBetter ? ('miss' as const) : ('hit' as const),
      title: persistenceBetter ? '“T2 = T1” is the better guess here' : 'The curve beats “T2 = T1” here',
      text: <>Mean error {pp(f.persistence_mae_pp)} for &ldquo;T2 = T1&rdquo; against {pp(f.curve_mae_pp)} for the curve. Any
        learned model has to beat the better of the two before Δ even matters.</>,
    },
    {
      kind: 'idea' as const,
      title: 'What the models must learn',
      text: <>If the gap between curve and Sybil is systematic across people, a trained model can correct it. Whether Δ adds
        anything on top is what step 7 answers, once enough people are in. Δ only ranges from about 0.86 to 1.25 years
        across NLST (5th to 95th percentile; {g.offset.toFixed(2)} here), so any effect is likely small.</>,
    },
  ]
  return (
    <Step n={8} title="What this one person already tells us"
      lede="Not a result, since it is one person, but useful for knowing what to look for in the full run.">
      <div className="grid gap-4 md:grid-cols-3">
        {findings.map((x) => (
          <div key={x.title} className="space-y-2 rounded-xl border bg-card p-4">
            <p className="flex items-center gap-2 font-medium">
              <span className={`flex size-6 shrink-0 items-center justify-center rounded-full ${x.kind === 'hit' ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
                {x.kind === 'hit' ? <Check className="size-3.5" aria-hidden />
                  : x.kind === 'miss' ? <X className="size-3.5" aria-hidden /> : <Lightbulb className="size-3.5" aria-hidden />}
              </span>
              {x.title}
            </p>
            <p className="text-sm leading-relaxed text-muted-foreground">{x.text}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" onClick={() => goTo({})}>The research question, on the homepage</Button>
        <Button variant="outline" onClick={() => goTo({ view: 'explore', participant: g.nlst_pid })}>
          See {g.nlst_pid}&rsquo;s scans in Explore <ArrowRight aria-hidden />
        </Button>
      </div>
    </Step>
  )
}
