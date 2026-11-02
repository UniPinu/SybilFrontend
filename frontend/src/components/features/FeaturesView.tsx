import {
  DX_COLOR,
  DistanceHistogram,
  FeatureHeatmap,
  FeatureMap,
  MapLegend,
  NO_DX_COLOR,
  StripPlot,
  dxColor,
  type StripValue,
} from '@/components/features/charts'
import { ROUND_COLOR } from '@/components/explore/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { api, READ_ONLY, type FeatureOverview, type FeaturePair, type FeatureParticipant, type FeatureSpace, type GroupComparison, type Quantiles } from '@/lib/api'
import { goTo, setParams, useSearchParams } from '@/lib/url'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Download, Layers } from 'lucide-react'
import { useId, type ReactNode } from 'react'

const SPACE_LABEL: Record<FeatureSpace, string> = {
  hidden: 'Sybil’s embedding (what the risk head reads)',
  encoder: 'Encoder average (before Sybil’s pooling)',
}

const METHOD_LABEL: Record<string, string> = {
  persistence: 'No change',
  drift: 'Everyone’s average change',
  linear: 'Straight-line extrapolation',
  damped: 'Damped extrapolation',
}

const f2 = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d))
const pc = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const signed = (v: number, d = 2) => `${v >= 0 ? '+' : ''}${v.toFixed(d)}`

// --- layout -------------------------------------------------------------------

function Section({ id, kicker, title, lede, children }: {
  id: string; kicker: string; title: string; lede: ReactNode; children: ReactNode
}) {
  return (
    <section id={id} className="section-anchor space-y-5">
      <header className="space-y-2">
        <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">{kicker}</p>
        <h2 className="text-xl font-semibold sm:text-2xl">{title}</h2>
        <div className="max-w-3xl leading-relaxed text-muted-foreground">{lede}</div>
      </header>
      {children}
    </section>
  )
}

function Panel({ title, caption, children }: { title: string; caption?: ReactNode; children: ReactNode }) {
  return (
    <figure className="min-w-0 space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      {children}
      {caption && <div className="text-xs leading-relaxed text-muted-foreground">{caption}</div>}
    </figure>
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

function Q({ q }: { q: Quantiles | null }) {
  if (!q) return <span className="text-muted-foreground">—</span>
  return (
    <span className="font-mono tabular-nums">
      {q.median.toFixed(2)} <span className="text-muted-foreground">({q.p25.toFixed(2)}–{q.p75.toFixed(2)})</span>
    </span>
  )
}

// --- the page -------------------------------------------------------------------

export function FeaturesView() {
  const params = useSearchParams()
  const space: FeatureSpace = params.get('space') === 'encoder' ? 'encoder' : 'hidden'
  const modelParam = Number(params.get('model'))
  const model = modelParam >= 1 && modelParam <= 5 ? modelParam : null

  const overview = useQuery({
    queryKey: ['feature-overview', space, model],
    queryFn: () => api.featureOverview(space, model),
    retry: false,
  })
  const o = overview.data
  const ready = o && o.map != null
  const fallback = o?.participants.find((p) => p.rounds.length === 3)?.nlst_pid ?? o?.participants[0]?.nlst_pid ?? null
  const pid = params.get('pid') || fallback

  return (
    <div className="space-y-14 pt-10">
      <Hero space={space} model={model} overview={o} />
      {overview.isPending && <Skeleton className="h-[420px] w-full rounded-xl" />}
      {overview.isError && (
        <Alert><AlertDescription>{overview.error.message}</AlertDescription></Alert>
      )}
      {o && !ready && <NotEnough o={o} />}
      {o && ready && (
        <>
          <MapSection o={o} pid={pid} />
          <StabilitySection o={o} />
          <DriftSection o={o} />
          {o.visibility && <VisibilitySection o={o} />}
          <GroupsSection o={o} />
          {o.forecast && <ForecastSection o={o} />}
          {pid && <ParticipantSection o={o} pid={pid} space={space} model={model} />}
          <Caveats />
        </>
      )}
    </div>
  )
}

function Hero({ space, model, overview }: { space: FeatureSpace; model: number | null; overview?: FeatureOverview }) {
  const spaceId = useId()
  const modelId = useId()
  const c = overview?.counts
  return (
    <section className="space-y-6">
      <div className="space-y-4">
        <Badge variant="outline" className="gap-1.5"><Layers className="size-3.5" aria-hidden /> Features · across screening rounds</Badge>
        <h1 className="max-w-3xl text-4xl leading-tight font-semibold text-balance sm:text-5xl">
          How Sybil’s features change from one scan to the next
        </h1>
        <p className="max-w-3xl text-lg text-muted-foreground">
          Sybil reads one CT scan at a time and remembers nothing. We stop it one step before the risk
          score and keep the features it extracted from each scan, then follow how those features move
          from T0 to T1 to T2. Sybil is not changed or retrained. Only its features are compared.
        </p>
      </div>

      <Pipeline />

      <div className="flex flex-col gap-4 rounded-xl border bg-muted/30 p-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="grid gap-3 sm:grid-cols-2 lg:flex lg:gap-4">
          <div className="space-y-1">
            <Label htmlFor={spaceId} className="text-xs">Feature space</Label>
            <NativeSelect id={spaceId} value={space} className="lg:w-80"
              onChange={(e) => setParams({ space: e.target.value === 'hidden' ? null : e.target.value })}>
              {(['hidden', 'encoder'] as const).map((s) => <option key={s} value={s}>{SPACE_LABEL[s]}</option>)}
            </NativeSelect>
          </div>
          <div className="space-y-1">
            <Label htmlFor={modelId} className="text-xs">Network</Label>
            <NativeSelect id={modelId} value={model ?? ''} className="lg:w-56"
              onChange={(e) => setParams({ model: e.target.value || null })}>
              <option value="">All five, side by side</option>
              {[1, 2, 3, 4, 5].map((m) => <option key={m} value={m}>Network {m} only</option>)}
            </NativeSelect>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {c && (
            <p className="text-sm text-muted-foreground">
              {c.scans} scans · {c.participants} participants · {c.with_3_rounds} with all three rounds
            </p>
          )}
          <Button variant="outline" size="sm" asChild>
            <a href={api.featureExportUrl(space, model)} download>
              <Download aria-hidden /> Features CSV
            </a>
          </Button>
        </div>
      </div>
    </section>
  )
}

function Pipeline() {
  const box = 'rounded-lg border bg-card px-3 py-2 text-center text-xs leading-snug'
  const arrow = <ArrowRight className="size-4 shrink-0 text-muted-foreground max-sm:rotate-90" aria-hidden />
  return (
    <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center" role="img"
      aria-label="CT scan, then the 3D encoder, then attention pooling into 512 features per network, which we keep. Sybil's risk head and its six risks follow but are not used for the comparison.">
      <div className={box}><p className="font-medium">CT scan</p><p className="text-muted-foreground">200 × 256 × 256</p></div>
      {arrow}
      <div className={box}><p className="font-medium">3D ResNet encoder</p><p className="text-muted-foreground">512 × 25 × 16 × 16</p><p className="text-[10px] text-muted-foreground">← “encoder average”</p></div>
      {arrow}
      <div className={box}><p className="font-medium">Attention pooling</p><p className="text-muted-foreground">where to look</p></div>
      {arrow}
      <div className="rounded-lg border-2 border-primary bg-card px-3 py-2 text-center text-xs leading-snug">
        <p className="font-semibold">512 features × 5 networks</p>
        <p className="text-muted-foreground">“Sybil’s embedding”: kept per scan</p>
      </div>
      <span className="text-muted-foreground max-sm:rotate-90 sm:px-1" aria-hidden>┆</span>
      <div className={`${box} opacity-60`}><p className="font-medium">Risk head</p><p className="text-muted-foreground">6 yearly risks</p></div>
    </div>
  )
}

function NotEnough({ o }: { o: FeatureOverview }) {
  return (
    <Alert>
      <AlertDescription className="space-y-2">
        <p>
          Only {o.counts.scans} scan{o.counts.scans === 1 ? ' has' : 's have'} features so far, and at least {o.min_scans} are
          needed. Features are saved for every new Sybil run. To build a longitudinal sample:
        </p>
        <pre className="overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs">cd backend{'\n'}uv run python scripts/build_features.py --n 40 --cancer-share 0.3</pre>
      </AlertDescription>
    </Alert>
  )
}

// --- the population -------------------------------------------------------------------

function MapSection({ o, pid }: { o: FeatureOverview; pid: string | null }) {
  const map = o.map!
  return (
    <Section id="map" kicker="1 · Everyone at once" title="Every scan, every person, in feature space"
      lede={<>
        Each dot is one scan, placed by the two directions along which Sybil’s features vary most across
        all {o.counts.scans} scans (principal components of {o.dims?.kept} standardized features). Lines join a person’s
        rounds in order. Short lines mean the features barely moved between screenings; long ones mean they
        changed a lot. Click any line to open that person below.
      </>}>
      <Panel title="Principal components of the features" caption={<>
        Together the two axes hold {pc(map.explained[0] + map.explained[1])} of the variation, so a long line here is real
        change but a short line can still hide change in the other directions. The distances in the sections below use every
        feature, not just these two.
      </>}>
        <MapLegend />
        <FeatureMap map={map} selected={pid}
          onSelect={(p) => {
            setParams({ pid: p })
            document.getElementById('participant')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }} />
      </Panel>
    </Section>
  )
}

function StabilitySection({ o }: { o: FeatureOverview }) {
  const pairs = o.stability!.pairs
  const t01 = pairs.find((p) => p.from === 'T0' && p.to === 'T1')
  return (
    <Section id="stability" kicker="2 · Signal or noise?" title="A person’s features stay recognisably theirs"
      lede={<>
        Before reading anything into a change, check that the features describe the <em>person</em> and not
        just the day’s scan. If they do, two scans of one person a year apart should be much closer than scans of two
        different people, and a person’s later scan should pick their own earlier scan out of everyone’s.
      </>}>
      <div className="grid gap-3 sm:grid-cols-3">
        {pairs.map((p) => p.reidentification && (
          <Stat key={p.from + p.to} label={`${p.to} finds its own ${p.from} among ${p.reidentification.gallery} scans`}
            value={pc(p.reidentification.top1)}
            hint={<>chance {pc(p.reidentification.chance, 1)} · {p.reidentification.queries} people · median rank {p.reidentification.median_rank}</>} />
        ))}
      </div>
      {t01 && (
        <Panel title="T0 → T1: how far apart are two scans?" caption={<>
          Distance is the root-mean-square difference over every standardized feature. By construction two unrelated scans sit near
          √2 ≈ 1.41, and 0 would be identical. Shares are within each group.
        </>}>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-foreground" /> Same person, T0 vs T1</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: 'var(--reference-line)' }} /> Two different people</span>
          </div>
          <DistanceHistogram bins={o.hist_bins} within={t01.within_hist} between={t01.between_hist} />
        </Panel>
      )}
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">Rounds</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Same person: median (IQR)</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Different people: median (IQR)</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Pairs</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p) => (
              <tr key={p.from + p.to} className="border-t">
                <th scope="row" className="px-3 py-2 text-left font-medium">{p.from} → {p.to}</th>
                <td className="px-3 py-2"><Q q={p.within} /></td>
                <td className="px-3 py-2"><Q q={p.between} /></td>
                <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {p.within?.n ?? 0} / {p.between?.n ?? 0}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  )
}

function DriftSection({ o }: { o: FeatureOverview }) {
  if (!o.drift?.length) return null
  return (
    <Section id="drift" kicker="3 · Shared or personal?" title="How much of the change happens to everyone"
      lede={<>
        Some change is common to every participant: a year of ageing, or the trial’s scanners being upgraded between rounds.
        If we average everyone’s change vector, that average is the shared part. Its share of a typical person’s change
        shows how much of the movement is personal.
      </>}>
      <div className="grid gap-3 sm:grid-cols-3">
        {o.drift.map((d) => (
          <Stat key={d.from + d.to} label={`${d.from} → ${d.to}: shared with everyone`} value={pc(d.shared_share)}
            hint={<>of the squared change, over {d.n} people · typical change {f2(d.mean_change)}, shared part {f2(d.shared_change)}</>} />
        ))}
      </div>
    </Section>
  )
}

function VisibilitySection({ o }: { o: FeatureOverview }) {
  const v = o.visibility!
  return (
    <Section id="visibility" kicker="4 · What the score sees" title="Most of the change is invisible to Sybil’s risk score"
      lede={<>
        Sybil’s risk head is nearly linear in these 512 features. Near any scan, one direction moves the 6-year score and every
        direction perpendicular to it leaves the score unchanged. Here we measure how much of each change between rounds lies along
        that direction, in each network’s own units, averaged over the five networks.
      </>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Share of the change the score can see" value={pc(v.share.median, 1)}
          hint={<>median over {v.share.n} pairs of rounds · IQR {pc(v.share.p25, 1)}–{pc(v.share.p75, 1)}</>} />
        <Stat label="A random direction would get" value={pc(v.random_share.median, 1)} hint="1 / the number of active features" />
        <Stat label="Times a random direction" value={`${f2(v.times_random_median, 1)}×`} hint="median over pairs" />
      </div>
      <p className="max-w-3xl text-sm text-muted-foreground">
        A comparison of risk scores only sees the first number. The rest of the change is still in the features, and it is what
        the following sections measure.
      </p>
    </Section>
  )
}

function groupRows(o: FeatureOverview, which: 'diagnosis' | 'acquisition', g: GroupComparison) {
  const dx = new Map(o.participants.map((p) => [p.nlst_pid, p.diagnosed]))
  const consecutive = o.pairs.filter((p) => !(p.from === 'T0' && p.to === 'T2') && p.per_year != null)
  const key = (p: FeaturePair) => (which === 'diagnosis' ? dx.get(p.nlst_pid) === true : p.acquisition_changed)
  const toValue = (p: FeaturePair): StripValue => ({
    value: p.per_year!,
    label: `${p.nlst_pid} ${p.from}→${p.to}${p.acquisition_changed ? ' (scanner/kernel changed)' : ''}`,
    color: dxColor(dx.get(p.nlst_pid)),
  })
  return [
    { name: g.labels[0], values: consecutive.filter(key).map(toValue) },
    { name: g.labels[1], values: consecutive.filter((p) => !key(p)).map(toValue) },
  ]
}

function TestLine({ g }: { g: GroupComparison }) {
  if (!g.test) return <p className="text-xs text-muted-foreground">Too few pairs in one of the groups for a test.</p>
  return (
    <p className="text-xs text-muted-foreground">
      Difference in mean change per year ({g.labels[0]} − {g.labels[1]}): <span className="font-mono text-foreground">{signed(g.test.difference, 3)}</span>,
      permutation p = <span className="font-mono text-foreground">{g.test.p_value.toFixed(3)}</span>.
    </p>
  )
}

function GroupsSection({ o }: { o: FeatureOverview }) {
  const g = o.groups!
  return (
    <Section id="groups" kicker="5 · Who changes faster" title="Change per year, by later diagnosis and by scanner change"
      lede={<>
        One dot per consecutive pair of rounds (T0 → T1 or T1 → T2): the distance travelled in feature space divided by the years
        between the scans. Changing the scanner or the reconstruction kernel between rounds can move the features without the person
        changing at all, so that comparison is shown next to the one by diagnosis.
      </>}>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="By later lung-cancer diagnosis" caption={<TestLine g={g.diagnosis} />}>
          <StripPlot rows={groupRows(o, 'diagnosis', g.diagnosis)} unit="distance / year" />
        </Panel>
        <Panel title="By whether the scanner or kernel changed" caption={<TestLine g={g.acquisition} />}>
          <StripPlot rows={groupRows(o, 'acquisition', g.acquisition)} unit="distance / year" />
        </Panel>
      </div>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        Dot colour:
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: DX_COLOR }} /> diagnosed later</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: NO_DX_COLOR }} /> not diagnosed</span>
        · hover a dot for the participant
      </p>
    </Section>
  )
}

function ForecastSection({ o }: { o: FeatureOverview }) {
  const f = o.forecast!
  const best = Math.min(...f.methods.map((m) => m.rms_error.median))
  return (
    <Section id="forecast" kicker="6 · Does the past predict the next scan?" title="Forecasting T2’s features from T0 and T1"
      lede={<>
        If features develop smoothly, T0 and T1 should say where T2 lands. Each method below predicts a person’s T2 feature
        vector without ever seeing it, using only their own T0 and T1 and everyone else’s data. In the embedding space the
        prediction can then be scored by Sybil’s own risk head and calibration, as if it were a real scan.
      </>}>
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">Method</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Feature error: median (IQR)</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Error in Sybil’s T2 risks</th>
            </tr>
          </thead>
          <tbody>
            {f.methods.map((m) => (
              <tr key={m.method} className="border-t">
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <p className="font-medium">{METHOD_LABEL[m.method] ?? m.method}{m.rms_error.median === best && <Badge variant="secondary" className="ml-2">lowest</Badge>}</p>
                  <p className="text-xs text-muted-foreground">{m.description}</p>
                </th>
                <td className="px-3 py-2"><Q q={m.rms_error} /></td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{m.risk_mae_pp == null ? '—' : `${m.risk_mae_pp.toFixed(2)} pp`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="max-w-3xl text-xs text-muted-foreground">
        {f.n} people with all three rounds; each is left out of anything fitted to them. The damped method’s α averaged {f2(f.alpha)} (0 = no
        change, 1 = full straight line). “Error in Sybil’s T2 risks” is the mean absolute difference, over the six years, between the
        forecast vector scored by Sybil’s head and Sybil’s real T2 risks, in percentage points. “No change” scores exactly Sybil’s T1 risks.
      </p>
    </Section>
  )
}

// --- one participant -------------------------------------------------------------------

function ParticipantSection({ o, pid, space, model }: { o: FeatureOverview; pid: string; space: FeatureSpace; model: number | null }) {
  const pickId = useId()
  const detail = useQuery({
    queryKey: ['feature-participant', pid, space, model],
    queryFn: () => api.featureParticipant(pid, space, model),
    retry: false,
  })
  const multi = o.participants.filter((p) => p.rounds.length > 1)
  return (
    <Section id="participant" kicker="7 · One person" title={`Participant ${pid}`}
      lede="The same measurements for one person: how far their features moved between each pair of rounds, compared with the gap between two different people, and which individual features moved most.">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor={pickId} className="text-xs">Participant</Label>
          <NativeSelect id={pickId} value={pid} className="w-72" onChange={(e) => setParams({ pid: e.target.value })}>
            {(multi.some((p) => p.nlst_pid === pid) ? multi : [...multi, ...o.participants.filter((p) => p.nlst_pid === pid)]).map((p) => (
              <option key={p.nlst_pid} value={p.nlst_pid}>
                {p.nlst_pid} · {p.rounds.map((r) => `T${r}`).join(' ')}{p.diagnosed ? ' · diagnosed' : ''}
              </option>
            ))}
          </NativeSelect>
        </div>
        <Button variant="outline" size="sm" onClick={() => goTo({ view: 'explore', participant: pid })}>
          Open in Explore <ArrowRight aria-hidden />
        </Button>
      </div>
      {detail.isPending && <Skeleton className="h-64 w-full rounded-xl" />}
      {detail.isError && <Alert><AlertDescription>{detail.error.message}</AlertDescription></Alert>}
      {detail.data && <ParticipantDetail d={detail.data} />}
    </Section>
  )
}

function ParticipantDetail({ d }: { d: FeatureParticipant }) {
  const o = d.outcome
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        {o.diagnosed
          ? `Diagnosed with lung cancer ${o.years_rand_to_dx != null ? `${o.years_rand_to_dx.toFixed(1)} years after enrolment` : 'during the trial'}.`
          : 'No lung-cancer diagnosis during follow-up.'}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        {d.rounds.map((r) => (
          <div key={r.round} className="rounded-xl border bg-card px-4 py-3" style={{ borderTopColor: ROUND_COLOR[r.round], borderTopWidth: 3 }}>
            <p className="text-xs text-muted-foreground">{r.round} · {r.years.toFixed(2)} y after enrolment</p>
            <p className="text-2xl font-semibold tabular-nums">{(r.risk_by_year[5] * 100).toFixed(1)}%</p>
            <p className="text-xs text-muted-foreground">Sybil’s 6-year risk, for reference</p>
            <p className="pt-1 text-xs text-muted-foreground">
              {[r.acquisition.manufacturer, r.acquisition.kernel, r.acquisition.thickness_mm && `${r.acquisition.thickness_mm} mm`].filter(Boolean).join(' · ')}
              {' · '}{pc(r.active_share)} of features active
            </p>
          </div>
        ))}
      </div>

      {d.pairs.length > 0 && (
        <div className="overflow-x-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">Rounds</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Years</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Distance</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Per year</th>
                <th scope="col" className="px-3 py-2 text-right font-medium" title="Share of different-person pairs that are closer than this change">Closer stranger pairs</th>
                {d.pairs[0].risk_visible_share != null && <th scope="col" className="px-3 py-2 text-right font-medium">Seen by score</th>}
                <th scope="col" className="px-3 py-2 text-right font-medium">Δ 6-y risk</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">Scanner / kernel</th>
              </tr>
            </thead>
            <tbody>
              {d.pairs.map((p) => (
                <tr key={p.from + p.to} className="border-t">
                  <th scope="row" className="px-3 py-2 text-left font-medium">{p.from} → {p.to}</th>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{f2(p.years_apart)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{f2(p.distance)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{f2(p.per_year, 3)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{pc(p.percentile_vs_between, 1)}</td>
                  {p.risk_visible_share != null && (
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{pc(p.risk_visible_share, 1)}</td>
                  )}
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{signed(p.delta_risk_6y * 100, 1)} pp</td>
                  <td className="px-3 py-2 text-xs">{p.acquisition_changed ? 'changed' : 'same'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Panel title={`The ${d.top_features.length} features that moved most between consecutive rounds`} caption={<>
        Labels are network·feature (N3·117 is feature 117 of network 3). The features have no names: Sybil learned them for
        predicting cancer, not to match anything a radiologist would label. “Risk weight / SD” is how much Sybil’s 6-year logit would
        move if this feature alone rose by one standard deviation at this person’s scans.
      </>}>
        <FeatureHeatmap detail={d} />
      </Panel>

      {d.forecast && (
        <Panel title="This person’s T2, forecast from T0 and T1" caption="Feature error uses the same units as above. The 6-year risk comes from scoring the forecast vector with Sybil’s own head.">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="py-1 pr-3 text-left font-medium">Method</th>
                  <th scope="col" className="px-3 py-1 text-right font-medium">Feature error</th>
                  <th scope="col" className="px-3 py-1 text-right font-medium">Forecast 6-y risk</th>
                </tr>
              </thead>
              <tbody>
                {d.forecast.methods.map((m) => (
                  <tr key={m.method} className="border-t">
                    <th scope="row" className="py-1.5 pr-3 text-left font-normal">{METHOD_LABEL[m.method] ?? m.method}</th>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums">{f2(m.rms_error)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums">{m.risk_by_year ? `${(m.risk_by_year[5] * 100).toFixed(1)}%` : '—'}</td>
                  </tr>
                ))}
                <tr className="border-t">
                  <th scope="row" className="py-1.5 pr-3 text-left font-medium">Sybil on the real T2 scan</th>
                  <td className="px-3 py-1.5 text-right font-mono">0</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">{(d.forecast.sybil_t2[5] * 100).toFixed(1)}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}

function Caveats() {
  return (
    <section className="space-y-3 rounded-xl border bg-muted/30 p-5 text-sm leading-relaxed text-muted-foreground">
      <h2 className="text-base font-semibold text-foreground">Reading these numbers honestly</h2>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>The five networks were trained separately, so feature 117 of network 1 has nothing to do with feature 117 of network 2. They are
          standardized and placed side by side, never averaged.</li>
        <li>Sybil’s embedding pools over the whole scan with learned attention, so it does not depend on where the patient lay. That is why
          scans can be compared without registering them, but it also means a change cannot be pinned to a place in the lung.</li>
        <li>A change of scanner, kernel or slice thickness between rounds can move the features by itself. Section 5 shows how much.</li>
        <li>Scans of people diagnosed later are over-sampled (about 30% of the sample vs ~2% in NLST), so the population numbers do
          not describe a typical screening population.</li>
        <li>About 45% of NLST CT participants were in Sybil’s training or development data, and the split is not public.</li>
        <li>{READ_ONLY ? 'This read-only site shows features that were already extracted.' : 'Every new Sybil run, from any page, adds its features here.'} Research demonstration, not for medical decisions.</li>
      </ul>
    </section>
  )
}
