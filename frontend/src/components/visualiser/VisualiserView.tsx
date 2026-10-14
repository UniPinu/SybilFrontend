import {
  ConvPanel,
  EnsemblePanel,
  HazardPanel,
  HiddenPanel,
  ImageAttentionPanel,
  PreprocessPanel,
  StagesPanel,
  TensorPanel,
  VolumeAttentionPanel,
  WindowPanel,
  Fact,
  Facts,
} from '@/components/visualiser/panels'
import { VisualiserScene, type StepId } from '@/components/visualiser/scene'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Slider } from '@/components/ui/slider'
import { caseUrl, useVisualiserCase, type VisualiserCase } from '@/lib/visualiser'
import { setParams, useSearchParams } from '@/lib/url'
import { ChevronLeft, ChevronRight, Crosshair, Pause, Play, RotateCcw } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

type Step = {
  id: StepId
  title: string
  /** what the 3D stage shows; 2D steps put their panel in the stage instead */
  mode: '3d' | '2d'
  /** which run-log lines belong to this step */
  log: string[]
  code: string
  intro: (d: VisualiserCase) => ReactNode
}

const STEPS: Step[] = [
  {
    id: 'scan', title: 'A CT scan is a stack of slices', mode: '3d', log: ['person', 'download', 'read'],
    code: 'Serie(dicom_paths)  # sorted by ImagePositionPatient',
    intro: (d) => <>The scanner records {d.dicom.n_slices} cross-sections, each {d.dicom.rows} × {d.dicom.cols} pixels of{' '}
      {d.dicom.pixel_spacing_mm[0].toFixed(3)} mm, {d.dicom.thickness_mm} mm thick and{' '}
      {(d.dicom.extent_mm[2] / d.dicom.n_slices).toFixed(1)} mm apart (they overlap slightly), from feet to head. Drawn here at true scale
      ({d.dicom.extent_mm.map((v) => Math.round(v)).join(' × ')} mm); air is see-through, tissue is not. Drag to orbit; the slider lifts one slice out.</>,
  },
  {
    id: 'window', title: 'Hounsfield units become grey', mode: '2d', log: ['window'],
    code: 'apply_windowing(hu, center=-600, width=1500) // 256',
    intro: (d) => <>Each pixel is a density in Hounsfield units (air −1000, water 0, bone above +400). Sybil keeps only the lung window,
      {' '}{Math.round(d.window.lo_hu)} to {Math.round(d.window.hi_hu)} HU, and maps it to 0–255. Everything denser is white.</>,
  },
  {
    id: 'preprocess', title: 'Resize, resample, pad', mode: '3d', log: ['resize', 'resample', 'pad'],
    code: 'Scale_2d(256) → Normalize → tio.Resample((0.703, 0.703, 2.5)) → tio.CropOrPad((256, 256, 200))',
    intro: (d) => <>Every scan must reach the same shape. Slices shrink to 256 × 256, the stack is resampled to 2.5 mm
      ({d.dicom.n_slices} → {d.preprocess.resampled[0]} slices), and padded with mean-grey slices to exactly 200 (orange).
      The rebuilt volume was checked to be bit-identical to Sybil&rsquo;s own <code>Serie.get_volume()</code>.</>,
  },
  {
    id: 'tensor', title: 'One volume, three channels', mode: '3d', log: ['model'],
    code: 'img.expand(3, *img.size()[1:])',
    intro: () => <>The encoder was pretrained on colour video, so the grey volume is copied into three identical channels:
      a 1 × 3 × 200 × 256 × 256 tensor, about 39 million numbers.</>,
  },
  {
    id: 'conv', title: 'A sliding window: the first convolution', mode: '3d', log: ['stem'],
    code: 'Conv3d(3, 64, kernel=(3, 7, 7), stride=(1, 2, 2), padding=(1, 3, 3)) → BatchNorm3d → ReLU',
    intro: (d) => <>A 3 × 7 × 7 box (3 slices deep, 7 × 7 pixels) slides over every position, two pixels at a time. At each stop
      it multiplies the {3 * 3 * 49} numbers under it by learned weights and adds them up. 64 such filters each paint their own
      map. The teal box is filter {d.stem_voxel.filter} moving over slice {d.stem_voxel.input_slice}; on the right, its output.</>,
  },
  {
    id: 'stages', title: 'Deeper and coarser: four ResNet stages', mode: '3d', log: ['encoder'],
    code: 'r3d_18: stem → layer1 → layer2 → layer3 → layer4  (2 residual blocks each)',
    intro: () => <>Each stage halves the grid in every direction and doubles the channels. The anatomy is the same, the
      description gets coarser and richer: 200 × 256 × 256 grey values become 25 × 16 × 16 positions with 512 numbers each.
      Colour: mean activation over channels. The teal box is everything one final voxel can see.</>,
  },
  {
    id: 'image-attention', title: 'Where to look inside each slab', mode: '3d', log: [],
    code: 'Simple_AttentionPool_MultiImg: softmax over 16 × 16 positions per slab',
    intro: () => <>The 25 slabs each get a 16 × 16 attention map: a learned score per position, softmaxed so the slab&rsquo;s
      weights sum to 1. The slab&rsquo;s summary is the weighted sum of its 512-number features. Pick a slab to pull it out.</>,
  },
  {
    id: 'volume-attention', title: 'Which slabs matter', mode: '3d', log: [],
    code: 'Simple_AttentionPool (25 slabs)  +  PerFrameMaxPool → Conv1d(k=11) → Simple_AttentionPool',
    intro: () => <>Two branches weigh the 25 slabs: one scores the slab summaries directly (right bars), the other takes each
      slab&rsquo;s per-channel maximum, mixes neighbouring slabs with a 1D convolution, then scores those (left bars).
      In-slab × slab weight is the hotspot glowing inside the volume.</>,
  },
  {
    id: 'hidden', title: 'Three summaries become 512 numbers', mode: '2d', log: [],
    code: 'hidden_fc(cat[h1, h2, global_max]) → ReLU  (1536 → 512)',
    intro: () => <>The attention-pooled vector, the max-and-convolve vector and a plain global maximum over all 6,400
      positions are concatenated (1,536 numbers) and projected to 512. This vector is everything the model knows about the scan.</>,
  },
  {
    id: 'hazards', title: 'Six output neurons draw the curve', mode: '2d', log: [],
    code: 'Cumulative_Probability_Layer: base_hazard_fc + cumsum(ReLU(hazard_fc(z))) → sigmoid',
    intro: () => <>Six neurons give a non-negative hazard for each year, a seventh a base level. Year h&rsquo;s logit is the base plus
      the hazards of years 1..h, so risk can never go down with time. A sigmoid turns each logit into a probability.
      For this scan something striking happens: every yearly hazard is negative, so ReLU zeroes them all and each
      model&rsquo;s curve is flat.</>,
  },
  {
    id: 'ensemble', title: 'Five models vote, then calibration', mode: '2d', log: ['ensemble', 'check', 'done'],
    code: 'np.mean(5 × prob) → isotonic calibrator per year',
    intro: (d) => <>All of the above ran five times, once per model. Their curves are averaged
      ({(d.ensemble.raw_mean[0] * 100).toFixed(1)}% for every year here) and each year is passed through its own
      calibration map, giving {(d.ensemble.calibrated[0] * 100).toFixed(1)}% in year 1 rising to{' '}
      {(d.ensemble.calibrated[5] * 100).toFixed(1)}% by year 6. For this scan, the rise over the years comes entirely from calibration.{' '}
      {d.outcome?.cancer_within_6y ? <>This person was diagnosed with {d.outcome.stage ?? 'lung cancer'} within {(d.outcome.years_to_cancer ?? 0) + 1} year of this scan.</> : null}</>,
  },
]

function StepPanel({ step, data, slab }: { step: Step; data: VisualiserCase; slab: number }) {
  switch (step.id) {
    case 'scan':
      return (
        <Facts>
          <Fact label="slices" value={data.dicom.n_slices} hint={`${data.dicom.thickness_mm} mm thick, ${(data.dicom.extent_mm[2] / data.dicom.n_slices).toFixed(1)} mm apart`} />
          <Fact label="slice size" value={`${data.dicom.rows} × ${data.dicom.cols}`} hint={`${data.dicom.pixel_spacing_mm[0].toFixed(3)} mm pixels`} />
          <Fact label="scanner" value={data.person.manufacturer ?? data.dicom.manufacturer} hint={`${data.person.scanner_model ?? ''} · kernel ${data.person.kernel ?? '—'}`} />
          <Fact label="person" value={`${data.person.age ?? '—'}, ${data.person.sex ?? ''}`} hint={data.person.smoking_status ?? undefined} />
        </Facts>
      )
    case 'window': return <WindowPanel data={data} />
    case 'preprocess': return <PreprocessPanel data={data} />
    case 'tensor': return <TensorPanel data={data} />
    case 'conv': return <ConvPanel data={data} />
    case 'stages': return <StagesPanel data={data} />
    case 'image-attention': return <ImageAttentionPanel data={data} slab={slab} />
    case 'volume-attention': return <VolumeAttentionPanel data={data} />
    case 'hidden': return <HiddenPanel data={data} />
    case 'hazards': return <HazardPanel data={data} />
    case 'ensemble': return <EnsemblePanel data={data} />
  }
}

function RunLog({ data, step }: { data: VisualiserCase; step: Step }) {
  const box = useRef<HTMLOListElement>(null)
  useEffect(() => {
    // scroll the log box only, never the page
    const list = box.current
    const line = list?.querySelector<HTMLElement>('[data-active="true"]')
    if (list && line) list.scrollTo({ top: line.offsetTop - list.offsetTop - 8, behavior: 'smooth' })
  }, [step])
  return (
    <section aria-labelledby="runlog" className="space-y-2">
      <h2 id="runlog" className="text-sm font-medium">Run log <span className="font-normal text-muted-foreground">· recorded on a MacBook Pro, CPU only</span></h2>
      <ol ref={box} className="max-h-56 overflow-y-auto rounded-xl border bg-[var(--scan-panel)] p-3 font-mono text-[11px] leading-relaxed text-slate-300">
        {data.log.map((line, i) => {
          const active = step.log.includes(line.step)
          const facts = Object.entries(line).filter(([k]) => !['t', 'step', 'message'].includes(k))
          return (
            <li key={i} data-active={active} className={active ? 'text-teal-300' : 'opacity-60'}>
              <span className="text-slate-500">[{line.t.toFixed(2).padStart(7, ' ')}s]</span> {line.step.padEnd(9, ' ')} {line.message}
              {facts.length > 0 && <span className="text-slate-500"> {facts.map(([k, v]) => `${k}=${Array.isArray(v) ? `[${v.join(',')}]` : String(v)}`).join(' ')}</span>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

export function VisualiserView() {
  const data = useVisualiserCase()
  const params = useSearchParams()
  const index = Math.max(0, Math.min(STEPS.length - 1, Number(params.get('step') ?? 1) - 1))
  const step = STEPS[index]
  const host = useRef<HTMLDivElement>(null)
  const scene = useRef<VisualiserScene | null>(null)
  const [playing, setPlaying] = useState(false)
  const [rawSlice, setRawSlice] = useState<number | null>(null)
  const [slab, setSlab] = useState<number | null>(null)
  const [convPlaying, setConvPlaying] = useState(true)
  const sliceId = useId()
  const slabId = useId()

  const go = (i: number) => setParams({ step: i === 0 ? null : String(i + 1) }, { replace: true })

  useEffect(() => {
    if (!data.data || !host.current) return
    const s = new VisualiserScene(host.current, data.data)
    scene.current = s
    return () => { s.dispose(); scene.current = null }
  }, [data.data])

  const d = data.data
  const slice = rawSlice ?? d?.window.slice ?? 0
  const slabNow = slab ?? d?.hotspot.slab ?? 0
  useEffect(() => { scene.current?.setStep(step.id) }, [step.id, d])
  useEffect(() => { scene.current?.setRawSlice(slice) }, [slice, d])
  useEffect(() => { scene.current?.setSlab(step.id === 'image-attention' ? slabNow : -1) }, [slabNow, step.id, d])
  useEffect(() => { scene.current?.setConvPlaying(convPlaying) }, [convPlaying, d])

  useEffect(() => {
    if (!playing) return
    const t = window.setTimeout(() => {
      if (index < STEPS.length - 1) go(index + 1)
      else setPlaying(false)
    }, step.id === 'conv' ? 11000 : 7000)
    return () => window.clearTimeout(t)
  }, [playing, index, step.id])

  return (
    <div className="space-y-8 pt-8">
      <header className="space-y-3">
        <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">Visualiser</p>
        <h1 className="text-3xl font-semibold text-balance sm:text-4xl">Inside Sybil, one real scan at a time</h1>
        <p className="max-w-3xl text-muted-foreground">
          Every picture and number below comes from one recorded run of the real five-model ensemble on one
          screening CT{d ? <> of NLST participant <span className="font-mono">{d.person.nlst_pid}</span> ({d.person.screening_round}),
          who was diagnosed with {d.outcome?.stage ?? 'lung cancer'} shortly after. Sybil gave a {(d.ensemble.calibrated[5] * 100).toFixed(1)}% six-year risk</> : ''}.
          The same run replays every time.
        </p>
      </header>

      {data.isError && (
        <Alert variant="destructive"><AlertDescription>
          The recorded run is missing. Create it with <code>uv run python scripts/capture_visualiser.py</code> in the backend folder.
        </AlertDescription></Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_380px]">
        <nav aria-label="Steps" className="lg:sticky lg:top-20 lg:self-start">
          <ol className="flex gap-1 overflow-x-auto pb-2 lg:flex-col lg:overflow-visible lg:pb-0">
            {STEPS.map((s, i) => (
              <li key={s.id} className="shrink-0">
                <button type="button" onClick={() => { setPlaying(false); go(i) }}
                  aria-current={i === index ? 'step' : undefined}
                  className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                    i === index ? 'bg-foreground text-background' : 'hover:bg-muted'}`}>
                  <span className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                    i === index ? 'bg-background text-foreground' : i < index ? 'bg-foreground/80 text-background' : 'border'}`}>{i + 1}</span>
                  <span className="hidden lg:inline">{s.title}</span>
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <div className="min-w-0 space-y-3">
          <div className="relative overflow-hidden rounded-2xl border border-[var(--scan-panel-border)] bg-[var(--scan-panel)]">
            <div ref={host} className={`relative h-[min(68vh,620px)] w-full ${step.mode === '2d' ? 'hidden' : ''}`}
              aria-label={`3D view: ${step.title}`} role="img" />
            {step.mode === '2d' && d && (
              <div className="h-[min(68vh,620px)] overflow-y-auto bg-card p-5">
                <h2 className="mb-4 text-lg font-semibold">{step.title}</h2>
                <StepPanel step={step} data={d} slab={slabNow} />
              </div>
            )}
            {!d && <Skeleton className="absolute inset-0 rounded-none" />}
            {step.mode === '3d' && (
              <p className="pointer-events-none absolute top-3 left-4 text-xs text-slate-400">
                {index + 1} / {STEPS.length} · drag to orbit, scroll to zoom
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" disabled={index === 0} onClick={() => { setPlaying(false); go(index - 1) }}>
              <ChevronLeft aria-hidden /> Back
            </Button>
            <Button size="sm" onClick={() => { if (!playing && index === STEPS.length - 1) go(0); setPlaying((p) => !p) }}>
              {playing ? <Pause aria-hidden /> : <Play aria-hidden />} {playing ? 'Pause' : 'Play all'}
            </Button>
            <Button variant="outline" size="sm" disabled={index === STEPS.length - 1} onClick={() => { setPlaying(false); go(index + 1) }}>
              Next <ChevronRight aria-hidden />
            </Button>
            {step.id === 'scan' && d && (
              <div className="flex min-w-60 flex-1 items-center gap-3 pl-2">
                <Label htmlFor={sliceId} className="shrink-0 text-xs text-muted-foreground">slice {slice + 1} / {d.dicom.n_slices}</Label>
                <Slider id={sliceId} min={0} max={d.dicom.n_slices - 1} step={1} value={[slice]} onValueChange={([v]) => setRawSlice(v)} aria-label="slice" />
              </div>
            )}
            {step.id === 'conv' && (
              <Button variant="ghost" size="sm" onClick={() => { setConvPlaying(true); scene.current?.setStep('conv') }}>
                <RotateCcw aria-hidden /> Replay the sweep
              </Button>
            )}
            {step.id === 'image-attention' && d && (
              <div className="flex min-w-60 flex-1 items-center gap-3 pl-2">
                <Label htmlFor={slabId} className="shrink-0 text-xs text-muted-foreground">slab {slabNow}</Label>
                <Slider id={slabId} min={0} max={24} step={1} value={[slabNow]} onValueChange={([v]) => setSlab(v)} aria-label="slab" />
                <Button variant="ghost" size="sm" onClick={() => setSlab(d.hotspot.slab)}><Crosshair aria-hidden /> hotspot</Button>
              </div>
            )}
          </div>
        </div>

        <aside className="space-y-4 lg:col-span-2 xl:col-span-1">
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">Step {index + 1}</p>
            <h2 className="text-xl font-semibold">{step.title}</h2>
            {d ? <p className="text-sm leading-relaxed">{step.intro(d)}</p> : <Skeleton className="h-24" />}
          </div>
          <pre className="overflow-x-auto rounded-lg border bg-muted/40 px-3 py-2 font-mono text-[11px] whitespace-pre-wrap text-muted-foreground">{step.code}</pre>
          {d && step.mode === '3d' && <StepPanel step={step} data={d} slab={slabNow} />}
        </aside>
      </div>

      {d && <RunLog data={d} step={step} />}
      {d && (
        <p className="text-xs text-muted-foreground">
          Recorded by <code>backend/scripts/capture_visualiser.py</code>; raw stack {Math.round(d.raw_atlas.bytes / 1024)} KB,
          model input {Math.round(d.input_atlas.bytes / 1024)} KB. <a className="underline" href={caseUrl('case.json', d.case)}>case.json</a>
        </p>
      )}
    </div>
  )
}
