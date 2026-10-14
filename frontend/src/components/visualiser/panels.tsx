/** The 2D side of the Visualiser: the real numbers behind each step. */
import { HazardStackDiagram } from '@/components/research/diagrams'
import { Tex } from '@/components/Tex'
import { caseUrl, type VisualiserCase } from '@/lib/visualiser'
import { useEffect, useRef, type ReactNode } from 'react'

/** The same magma polynomial as the shader, for SVG and canvas. */
export function magma(t: number): string {
  const c = [
    [-0.002136485053939582, -0.000749655052795221, -0.005386127855323933],
    [0.2516605407371642, 0.6775232436837668, 2.494026599312351],
    [8.353717279216625, -3.577719514958484, 0.3144679030132573],
    [-27.66873308576866, 14.26473078096533, -13.64921318813922],
    [52.17613981234068, -27.94360607168351, 12.94416944238394],
    [-50.76852536473588, 29.04658282127291, 4.23415299384598],
    [18.65570506591883, -11.48977351997711, -5.601961508734096],
  ]
  const x = Math.min(1, Math.max(0, t))
  const ch = [0, 1, 2].map((k) => {
    let v = c[6][k]
    for (let i = 5; i >= 0; i--) v = c[i][k] + x * v
    return Math.round(255 * Math.min(1, Math.max(0, v)))
  })
  return `rgb(${ch[0]},${ch[1]},${ch[2]})`
}

/** Diverging blue-white-orange for signed weights. */
function diverging(v: number, max: number): string {
  const t = Math.max(-1, Math.min(1, v / (max || 1)))
  const a = Math.abs(t)
  const [r, g, b] = t >= 0 ? [234, 120, 40] : [56, 128, 220]
  return `rgb(${Math.round(255 + (r - 255) * a)},${Math.round(255 + (g - 255) * a)},${Math.round(255 + (b - 255) * a)})`
}

export function Fact({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 px-3 py-2">
      <dt className="text-[11px] tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="font-mono text-sm tabular-nums">{value}</dd>
      {hint && <dd className="text-[11px] text-muted-foreground">{hint}</dd>}
    </div>
  )
}

export function Facts({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-2 gap-2">{children}</dl>
}

function Img({ file, alt, data, pixelated = false }: { file: string; alt: string; data: VisualiserCase; pixelated?: boolean }) {
  return <img src={caseUrl(file, data.case)} alt={alt} className="w-full rounded-md border bg-black"
    style={pixelated ? { imageRendering: 'pixelated' } : undefined} />
}

/** A small grid of numbers as coloured cells (optionally with the values written in). */
export function Grid({ values, color, cell = 18, text = false, title }: {
  values: number[][]
  color: (v: number) => string
  cell?: number
  text?: boolean
  title?: string
}) {
  const h = values.length
  const w = values[0]?.length ?? 0
  return (
    <svg viewBox={`0 0 ${w * cell} ${h * cell}`} className="w-full" role="img" aria-label={title}>
      {values.map((row, y) => row.map((v, x) => (
        <g key={`${y}-${x}`}>
          <rect x={x * cell} y={y * cell} width={cell - 1} height={cell - 1} fill={color(v)} />
          {text && (
            <text x={x * cell + cell / 2} y={y * cell + cell / 2} dy="0.33em" textAnchor="middle"
              fontSize={cell * 0.3} fill="#111">{v.toFixed(1)}</text>
          )}
        </g>
      )))}
    </svg>
  )
}

// ---------------------------------------------------------------------------
export function WindowPanel({ data }: { data: VisualiserCase }) {
  const w = data.window
  const max = Math.max(...w.hist)
  const lo = w.hist_edges[0]
  const hi = w.hist_edges[w.hist_edges.length - 1]
  const X = (v: number) => ((v - lo) / (hi - lo)) * 600
  return (
    <div className="space-y-5">
      <svg viewBox="0 0 600 190" className="w-full" role="img" aria-label="Histogram of Hounsfield units with the lung window marked">
        <rect x={X(w.lo_hu)} width={X(w.hi_hu) - X(w.lo_hu)} y={0} height={160} fill="var(--risk-3)" opacity={0.18} />
        {w.hist.map((c, i) => {
          const x0 = X(w.hist_edges[i])
          const x1 = X(w.hist_edges[i + 1])
          const hgt = (Math.sqrt(c) / Math.sqrt(max)) * 150
          return <rect key={i} x={x0} width={Math.max(1, x1 - x0 - 0.5)} y={160 - hgt} height={hgt} fill="var(--foreground)" opacity={0.75} />
        })}
        {[-1000, -500, 0, 500, 1000].map((v) => (
          <text key={v} x={X(v)} y={178} textAnchor="middle" fontSize={11} className="fill-muted-foreground">{v}</text>
        ))}
        <text x={X(w.lo_hu) + 4} y={14} fontSize={11} className="fill-foreground">lung window {Math.round(w.lo_hu)} … {Math.round(w.hi_hu)} HU</text>
      </svg>
      <p className="-mt-3 text-[11px] text-muted-foreground">Hounsfield units of every pixel on slice {w.slice + 1} (bar height: square root of the count).</p>
      <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
        <figure className="space-y-1"><Img data={data} file={w.hu_image} alt="Raw slice in Hounsfield units" />
          <figcaption>Raw HU, −1024 … 1500 shown linearly: the lungs are a flat dark mass.</figcaption></figure>
        <figure className="space-y-1"><Img data={data} file={w.windowed_image} alt="The same slice after windowing" />
          <figcaption>After the lung window: vessels, airways and the lesion stand out.</figcaption></figure>
      </div>
      <Tex block tex={String.raw`y = \operatorname{clip}\!\left(\frac{\mathrm{HU} - (c - \tfrac12)}{w - 1} + \tfrac12,\ 0,\ 1\right)\cdot 65535,\quad \text{then } \lfloor y/256 \rfloor`} />
      <p className="text-xs text-muted-foreground">With <Tex tex={`c=${w.center},\\ w=${w.width}`} />. This slice spans {w.hu_range[0]} … {w.hu_range[1]} HU before windowing.</p>
    </div>
  )
}

export function PreprocessPanel({ data }: { data: VisualiserCase }) {
  const p = data.preprocess
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
        <figure className="space-y-1"><Img data={data} file={p.images.resized} alt="Resized slice" /><figcaption>resized 256×256</figcaption></figure>
        <figure className="space-y-1"><Img data={data} file={p.images.resampled} alt="Resampled slice" /><figcaption>resampled {p.resampled[1]}×{p.resampled[2]}</figcaption></figure>
        <figure className="space-y-1"><Img data={data} file={p.images.padded} alt="Padded slice" /><figcaption>padded 256×256</figcaption></figure>
      </div>
      <Facts>
        <Fact label="slices" value={`${data.dicom.n_slices} → ${p.resampled[0]} → ${p.input[0]}`} hint={`${data.dicom.thickness_mm} mm → ${p.voxel_spacing_target[2]} mm, then ${p.pad_slices_before} + ${p.pad_slices_after} padding`} />
        <Fact label="in-plane" value={`512 → 256 → ${p.resampled[1]} → 256`} hint={`${p.pad_pixels[0]} px of padding each side`} />
        <Fact label="normalise" value={<Tex tex={String.raw`(x - ${p.img_mean})/${p.img_std}`} />} hint={`range ${p.value_range[0]} … ${p.value_range[1]}`} />
        <Fact label="padding value" value="0" hint="the mean grey after normalising (orange in 3D)" />
      </Facts>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Sybil resizes each slice to 256 first and then resamples with the spacing read from the DICOM
        ({data.dicom.pixel_spacing_mm[0].toFixed(3)} mm). So the network&rsquo;s nominal 0.703 mm pixels really
        cover {(data.dicom.extent_mm[0] / p.resampled[1]).toFixed(2)} mm. That is what this pinned version of Sybil
        does; the 3D view draws the stack at its true physical size.
      </p>
    </div>
  )
}

export function TensorPanel({ data }: { data: VisualiserCase }) {
  const n = 3 * 200 * 256 * 256
  return (
    <div className="space-y-4">
      <Tex block tex={String.raw`x \in \mathbb{R}^{1 \times 3 \times 200 \times 256 \times 256}`} />
      <Facts>
        <Fact label="numbers" value={n.toLocaleString()} hint="batch × channels × slices × rows × cols" />
        <Fact label="channels" value="3 identical copies" hint="the encoder was pretrained on colour video" />
        <Fact label="per model" value={`${(data.architecture.params_per_model / 1e6).toFixed(1)} M weights`} hint="3D ResNet-18 + pooling + hazard head" />
        <Fact label="ensemble" value="5 models" hint="same architecture, different training runs" />
      </Facts>
      <p className="text-xs leading-relaxed text-muted-foreground">
        The encoder is torchvision&rsquo;s <code>r3d_18</code>, a ResNet-18 with 3D convolutions, first
        trained on the Kinetics action-recognition videos. A CT stack is treated like a 200-frame grey video.
      </p>
    </div>
  )
}

export function ConvPanel({ data }: { data: VisualiserCase }) {
  const v = data.stem_voxel
  const wmax = Math.max(...v.weights_summed.flat(2).map(Math.abs))
  const pmax = Math.max(...v.patch.flat(2).map(Math.abs))
  const match = Math.abs(v.after_relu - v.hooked_value) < 1e-3
  return (
    <div className="space-y-4">
      <p className="text-sm">
        Output voxel <span className="font-mono">({v.input_slice}, {v.out_yx[0]}, {v.out_yx[1]})</span> of filter{' '}
        <span className="font-mono">{v.filter}</span>, the most active of all 64 filters at the hotspot, computed by hand:
      </p>
      <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-[11px] text-muted-foreground">
        <span>input patch<br />3 × 7 × 7</span>
        <div className="grid grid-cols-3 gap-1">
          {v.patch.map((s, i) => <Grid key={i} values={s} cell={12} color={(x) => diverging(x, pmax)} title={`patch slice ${i}`} />)}
        </div>
        <span>weights<br />3 × 7 × 7</span>
        <div className="grid grid-cols-3 gap-1">
          {v.weights_summed.map((s, i) => <Grid key={i} values={s} cell={12} color={(x) => diverging(x, wmax)} title={`weights slice ${i}`} />)}
        </div>
      </div>
      <div className="space-y-1 rounded-lg border bg-muted/30 p-3 text-sm">
        <Tex block tex={String.raw`\textstyle\sum w \cdot x = ${v.dot.toFixed(3)}`} />
        <Tex block tex={String.raw`\textstyle\mathrm{BN}: \frac{${v.dot.toFixed(2)} - (${v.bn.mean.toFixed(2)})}{\sqrt{${v.bn.var.toFixed(2)} + \epsilon}} \cdot ${v.bn.gamma.toFixed(2)} + (${v.bn.beta.toFixed(2)}) = ${v.after_bn.toFixed(3)}`} />
        <Tex block tex={String.raw`\textstyle\mathrm{ReLU} \Rightarrow ${v.after_relu.toFixed(4)}`} />
        <p className={`text-xs ${match ? 'text-risk-2-text' : 'text-destructive'}`}>
          {match ? '✓' : '✗'} the network itself produced {v.hooked_value.toFixed(4)} at this voxel (read with a hook)
        </p>
      </div>
      <p className="text-[11px] text-muted-foreground">Weights shown summed over the 3 identical input channels; blue negative, orange positive.</p>
      <figure className="space-y-1">
        <Img data={data} file={data.stem_maps.file} alt="All 64 first-layer filter responses" />
        <figcaption className="text-[11px] text-muted-foreground">All 64 filters on input slice {v.input_slice}, after BatchNorm and ReLU.</figcaption>
      </figure>
    </div>
  )
}

export function StagesPanel({ data }: { data: VisualiserCase }) {
  const rf = new Map(data.receptive_field.map((r) => [r.stage, r.rf]))
  return (
    <div className="space-y-4">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr><th className="py-1 text-left font-normal">stage</th><th className="text-left font-normal">C × T × H × W</th><th className="text-right font-normal">zeroed</th><th className="text-right font-normal">sees</th></tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {data.stages.map((s) => (
            <tr key={s.name} className="border-t">
              <td className="py-1">{s.name}</td>
              <td>{s.shape.join(' × ')}</td>
              <td className="text-right">{Math.round(s.zeroed_by_relu * 100)}%</td>
              <td className="text-right">{rf.get(s.name)?.join('×')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-muted-foreground">
        &ldquo;Zeroed&rdquo;: share of values ReLU set to 0. &ldquo;Sees&rdquo;: receptive field in input voxels (slices × rows × cols),
        computed from the real kernel sizes and strides.
      </p>
      <div className="grid grid-cols-2 gap-2">
        {data.stages.filter((s) => s.name !== 'stem').map((s) => (
          <figure key={s.name} className="space-y-1">
            <Img data={data} file={s.channel_atlas.file} alt={`${s.name}: 16 most active channels`} pixelated={s.shape[2] <= 32} />
            <figcaption className="text-[11px] text-muted-foreground">{s.name}: 16 most active of {s.shape[0]} channels, depth {s.z} of {s.shape[1]}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  )
}

/** One slab's 16x16 attention over the CT slice at its centre. */
export function SlabOverlay({ data, slab }: { data: VisualiserCase; slab: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const img = new Image()
    img.src = caseUrl(data.input_atlas.file, data.case)
    img.onload = () => {
      const a = data.input_atlas
      const i = slab * 8 + 4
      const sx = (i % a.cols) * a.tile
      const sy = Math.floor(i / a.cols) * a.tile
      ctx.clearRect(0, 0, 256, 256)
      ctx.drawImage(img, sx, sy, a.tile, a.tile, 0, 0, 256, 256)
      const att = data.models.map((m) => m.image_attention[slab])
      const mean = att[0].map((_, p) => att.reduce((acc, row) => acc + row[p], 0) / att.length)
      const max = Math.max(...mean)
      mean.forEach((v, p) => {
        ctx.globalAlpha = Math.min(0.85, (v / max) * 0.9)
        ctx.fillStyle = magma(v / max)
        ctx.fillRect((p % 16) * 16, Math.floor(p / 16) * 16, 16, 16)
      })
      ctx.globalAlpha = 1
    }
  }, [data, slab])
  return <canvas ref={ref} width={256} height={256} className="w-full rounded-md border bg-black" style={{ imageRendering: 'pixelated' }} />
}

export function ImageAttentionPanel({ data, slab }: { data: VisualiserCase; slab: number }) {
  const att = data.models.map((m) => m.image_attention[slab])
  const mean = att[0].map((_, p) => att.reduce((acc, row) => acc + row[p], 0) / att.length)
  const peak = Math.max(...mean)
  return (
    <div className="space-y-4">
      <SlabOverlay data={data} slab={slab} />
      <Tex block tex={String.raw`a_{t,p} = \frac{\exp(u^{\top} v_{t,p})}{\sum_{q=1}^{256} \exp(u^{\top} v_{t,q})}, \qquad s_t = \sum_{p} a_{t,p}\, v_{t,p}`} />
      <Facts>
        <Fact label="slab" value={`${slab} of 25`} hint={`input slices ${slab * 8}–${slab * 8 + 7}`} />
        <Fact label="peak weight" value={`${(peak * 100).toFixed(1)}%`} hint={`uniform would be ${(100 / 256).toFixed(2)}%`} />
      </Facts>
      <p className="text-xs text-muted-foreground">
        <Tex tex="v_{t,p}" /> is the 512-number layer4 feature at position <Tex tex="p" /> of slab <Tex tex="t" />. One learned
        vector <Tex tex="u" /> scores every position; a softmax per slab turns the scores into weights that sum to 1.
        Shown: the mean of the five models.
      </p>
    </div>
  )
}

export function VolumeAttentionPanel({ data }: { data: VisualiserCase }) {
  const mean = (key: 'volume_attention' | 'volume_attention_2') =>
    Array.from({ length: 25 }, (_, t) => data.models.reduce((a, m) => a + m[key][t], 0) / data.models.length)
  const b1 = mean('volume_attention')
  const b2 = mean('volume_attention_2')
  const max = Math.max(...b1, ...b2)
  const hot = data.hotspot.slab
  return (
    <div className="space-y-4">
      <svg viewBox="0 0 500 200" className="w-full" role="img" aria-label="Attention weight of each of the 25 slabs in both branches">
        {b1.map((v, t) => (
          <g key={t}>
            <rect x={t * 20 + 2} y={95 - (v / max) * 85} width={7} height={(v / max) * 85} fill="#5eead4" />
            <rect x={t * 20 + 10} y={95 - (b2[t] / max) * 85} width={7} height={(b2[t] / max) * 85} fill="#f0abfc" />
            {t === hot && <rect x={t * 20} y={2} width={19} height={95} fill="none" stroke="var(--foreground)" strokeDasharray="3 2" />}
            {t % 4 === 0 && <text x={t * 20 + 10} y={112} textAnchor="middle" fontSize={10} className="fill-muted-foreground">{t}</text>}
          </g>
        ))}
        <text x={250} y={128} textAnchor="middle" fontSize={11} className="fill-muted-foreground">slab (8 input slices each), head ↔ feet</text>
        <rect x={60} y={150} width={10} height={10} fill="#5eead4" /><text x={76} y={159} fontSize={11} className="fill-foreground">branch 1: attention over slab summaries</text>
        <rect x={60} y={170} width={10} height={10} fill="#f0abfc" /><text x={76} y={179} fontSize={11} className="fill-foreground">branch 2: per-slab max → conv1d (k = 11) → attention</text>
      </svg>
      <Facts>
        <Fact label="hotspot slab" value={hot} hint={`branch 1 gives it ${(b1[hot] * 100).toFixed(1)}%`} />
        <Fact label="hotspot position" value={`row ${data.hotspot.y}, col ${data.hotspot.x}`} hint="of the 16 × 16 grid" />
      </Facts>
      <p className="text-xs text-muted-foreground">
        The app&rsquo;s heatmap is the in-slab weight times the slab weight of branch 1, averaged over the five
        models: <Tex tex={String.raw`A_{t,p} = \tfrac15\sum_m a^{(m)}_{t,p}\,\beta^{(m)}_t`} />. In 3D it glows where the lesion is.
      </p>
    </div>
  )
}

function Strip({ values, label, max }: { values: number[]; label: string; max: number }) {
  const cols = 32
  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${cols * 6} ${Math.ceil(values.length / cols) * 6}`} className="w-full" role="img" aria-label={label}>
        {values.map((v, i) => (
          <rect key={i} x={(i % cols) * 6} y={Math.floor(i / cols) * 6} width={5.4} height={5.4}
            fill={v <= 0 ? 'var(--muted)' : magma(0.18 + 0.82 * Math.min(1, v / max))} />
        ))}
      </svg>
      <figcaption className="text-[11px] text-muted-foreground">{label}</figcaption>
    </figure>
  )
}

export function HiddenPanel({ data }: { data: VisualiserCase }) {
  const m = data.models[0]
  const pos = (xs: number[]) => xs.map((x) => Math.max(0, x))
  const max = (xs: number[]) => Math.max(...pos(xs)) || 1
  const zero = m.hidden.filter((x) => x <= 0).length
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <Strip values={m.hidden_1} max={max(m.hidden_1)} label="attention-pooled (512)" />
        <Strip values={m.hidden_2} max={max(m.hidden_2)} label="max → conv1d → attention (512)" />
        <Strip values={m.maxpool_hidden} max={max(m.maxpool_hidden)} label="global max (512)" />
      </div>
      <Tex block tex={String.raw`z = \operatorname{ReLU}\!\big(W\,[\,h_1;\ h_2;\ h_{\max}\,] + b\big),\quad W \in \mathbb{R}^{512 \times 1536}`} />
      <Strip values={m.hidden} max={max(m.hidden)} label={`z: the 512-number summary of the whole scan (model 1). ${zero} of 512 are 0 after ReLU (grey).`} />
    </div>
  )
}

export function HazardPanel({ data }: { data: VisualiserCase }) {
  const m = data.models[0]
  const pos = m.raw_hazard.map((v) => Math.max(0, v))
  const contrib = m.hazard_contrib_top ?? []
  const cmax = Math.max(...contrib.flat().map(Math.abs)) || 1
  return (
    <div className="space-y-4">
      <HazardStackDiagram base={m.base_hazard} hazards={pos} />
      <table className="w-full text-xs">
        <thead className="text-muted-foreground"><tr>
          <th className="text-left font-normal">year</th>{[1, 2, 3, 4, 5, 6].map((h) => <th key={h} className="text-right font-normal">{h}</th>)}
        </tr></thead>
        <tbody className="font-mono tabular-nums">
          <tr className="border-t"><td>w·z + c</td>{m.raw_hazard.map((v, i) => <td key={i} className="text-right">{v.toFixed(2)}</td>)}</tr>
          <tr className="border-t"><td>ReLU</td>{pos.map((v, i) => <td key={i} className="text-right">{v.toFixed(2)}</td>)}</tr>
          <tr className="border-t"><td>+ base Σ</td>{m.cum_logit.map((v, i) => <td key={i} className="text-right">{v.toFixed(2)}</td>)}</tr>
          <tr className="border-t font-semibold"><td>σ</td>{m.prob.map((v, i) => <td key={i} className="text-right">{(v * 100).toFixed(1)}%</td>)}</tr>
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">Base hazard <span className="font-mono">{m.base_hazard.toFixed(3)}</span>. Model 1 alone, before averaging and calibration.</p>
      <div className="rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed">
        <p className="font-medium">All five models do the same on this scan</p>
        <table className="mt-2 w-full font-mono tabular-nums">
          <thead className="text-muted-foreground"><tr><th className="text-left font-normal">model</th><th className="text-right font-normal">base</th><th className="text-right font-normal">largest yearly w·z+c</th><th className="text-right font-normal">every year</th></tr></thead>
          <tbody>{data.models.map((mm, k) => (
            <tr key={k} className="border-t"><td>{k + 1}</td><td className="text-right">{mm.base_hazard.toFixed(2)}</td>
              <td className="text-right">{Math.max(...mm.raw_hazard).toFixed(2)}</td><td className="text-right">{(mm.prob[0] * 100).toFixed(1)}%</td></tr>
          ))}</tbody>
        </table>
        <p className="mt-2 text-muted-foreground">Every yearly hazard is below zero before the ReLU, so all the risk sits in the base
          hazard: the scan reads as high-risk <em>now</em>, with nothing added for later years. The year-by-year shape of the
          final curve comes from the next step.</p>
      </div>
      {contrib.length > 0 && (
        <figure className="space-y-1">
          <Grid values={contrib} cell={14} color={(v) => diverging(v, cmax)} title="Contribution of the 24 most influential hidden units to each year's hazard" />
          <figcaption className="text-[11px] text-muted-foreground">Rows: years 1–6. Columns: the 24 hidden units that push the hazards hardest (<Tex tex="w_{j,i} z_i" />; orange raises risk).</figcaption>
        </figure>
      )}
    </div>
  )
}

export function EnsemblePanel({ data }: { data: VisualiserCase }) {
  const e = data.ensemble
  const W = 520
  const H = 220
  const x = (h: number) => 40 + ((h - 1) / 5) * (W - 70)
  const y = (p: number) => H - 30 - p * (H - 50)
  const line = (ps: number[]) => ps.map((p, i) => `${i ? 'L' : 'M'}${x(i + 1)},${y(p)}`).join('')
  return (
    <div className="space-y-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Five model curves, their mean and the calibrated result">
        {[0, 0.25, 0.5, 0.75, 1].map((p) => (
          <g key={p}><line x1={40} x2={W - 30} y1={y(p)} y2={y(p)} stroke="var(--border)" />
            <text x={34} y={y(p)} dy="0.32em" textAnchor="end" fontSize={10} className="fill-muted-foreground">{p * 100}%</text></g>
        ))}
        {[1, 2, 3, 4, 5, 6].map((h) => <text key={h} x={x(h)} y={H - 12} textAnchor="middle" fontSize={10} className="fill-muted-foreground">year {h}</text>)}
        {data.models.map((m, k) => <path key={k} d={line(m.prob)} fill="none" stroke="var(--reference-line)" strokeWidth={1.2} opacity={0.8} />)}
        <path d={line(e.raw_mean)} fill="none" stroke="var(--foreground)" strokeWidth={2} strokeDasharray="5 4" />
        <path d={line(e.calibrated)} fill="none" stroke="var(--risk-5)" strokeWidth={3} />
        {e.calibrated.map((p, i) => <circle key={i} cx={x(i + 1)} cy={y(p)} r={3.5} fill="var(--risk-5)" />)}
      </svg>
      <p className="text-xs text-muted-foreground">Grey: the five models. Dashed: their mean. Orange: after calibration, the number the app shows.</p>
      <div className="grid grid-cols-3 gap-2">
        {e.calibration_curves.map((curve, yr) => {
          const s = 70
          const px = (v: number) => 4 + v * (s - 8)
          const py = (v: number) => s - 4 - v * (s - 8)
          const d = curve.map((v, i) => `${i ? 'L' : 'M'}${px(e.calibration_x[i])},${py(v)}`).join('')
          return (
            <figure key={yr} className="rounded-md border p-1">
              <svg viewBox={`0 0 ${s} ${s}`} className="w-full" role="img" aria-label={`Year ${yr + 1} calibration map`}>
                <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} stroke="var(--border)" />
                <path d={d} fill="none" stroke="var(--foreground)" strokeWidth={1.2} />
                <circle cx={px(e.raw_mean[yr])} cy={py(e.calibrated[yr])} r={2.6} fill="var(--risk-5)" />
              </svg>
              <figcaption className="text-center font-mono text-[10px] text-muted-foreground">
                y{yr + 1}: {(e.raw_mean[yr] * 100).toFixed(0)}% → {(e.calibrated[yr] * 100).toFixed(1)}%
              </figcaption>
            </figure>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        Each year has its own isotonic map from raw mean to calibrated risk (axes 0–100%), fitted by the Sybil
        authors on held-out data.{' '}
        {data.matches_cached_run && 'This recorded run reproduces the app’s cached result for the same scan.'}
      </p>
    </div>
  )
}
