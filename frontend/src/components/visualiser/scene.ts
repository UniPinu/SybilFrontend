/**
 * The Visualiser's three.js stage.
 *
 * One persistent scene holds every "actor" (the raw slice stack, the model's
 * input stack, the sliding kernel, the encoder stages, the attention maps).
 * A step only sets *targets* (opacity, offsets, camera); the render loop eases
 * toward them, so moving between steps is always a smooth morph and nothing
 * is rebuilt. All textures come from the recorded run.
 *
 * Units: 1 = 100 mm, so the stacks keep their real physical proportions.
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js'
import { caseUrl, type Atlas, type VisualiserCase } from '@/lib/visualiser'

const MM = 0.01

// ---------------------------------------------------------------------------
// shaders
// ---------------------------------------------------------------------------
const VERT = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`

/** One tile of an atlas; grey or magma; alpha from intensity so air is see-through. */
const FRAG = /* glsl */ `
uniform sampler2D atlas;
uniform vec2 grid;          // cols, rows
uniform float index;
uniform float opacity;
uniform vec2 alphaRange;    // intensity -> alpha ramp
uniform float floorAlpha;   // minimum alpha for every pixel (1 = fully opaque slice)
uniform int colormap;       // 0 grey, 1 magma
uniform vec3 tint;
uniform float reveal;       // raster reveal 0..1 (sliding-window output)
uniform vec2 texels;        // tile size in texels, for the reveal
varying vec2 vUv;

vec3 magma(float t) {
  const vec3 c0 = vec3(-0.002136485053939582, -0.000749655052795221, -0.005386127855323933);
  const vec3 c1 = vec3(0.2516605407371642, 0.6775232436837668, 2.494026599312351);
  const vec3 c2 = vec3(8.353717279216625, -3.577719514958484, 0.3144679030132573);
  const vec3 c3 = vec3(-27.66873308576866, 14.26473078096533, -13.64921318813922);
  const vec3 c4 = vec3(52.17613981234068, -27.94360607168351, 12.94416944238394);
  const vec3 c5 = vec3(-50.76852536473588, 29.04658282127291, 4.23415299384598);
  const vec3 c6 = vec3(18.65570506591883, -11.48977351997711, -5.601961508734096);
  return c0 + t * (c1 + t * (c2 + t * (c3 + t * (c4 + t * (c5 + t * c6)))));
}

void main() {
  if (reveal < 1.0) {
    vec2 px = floor(vec2(vUv.x, 1.0 - vUv.y) * texels);
    if ((px.y * texels.x + px.x) / (texels.x * texels.y) > reveal) discard;
  }
  float col = mod(index, grid.x);
  float row = floor(index / grid.x);
  vec2 uv = vec2((col + vUv.x) / grid.x, 1.0 - (row + 1.0 - vUv.y) / grid.y);
  float v = texture2D(atlas, uv).r;
  float a = max(smoothstep(alphaRange.x, alphaRange.y, v), floorAlpha) * opacity;
  if (a < 0.004) discard;
  vec3 c = colormap == 1 ? magma(clamp(v, 0.0, 1.0)) : vec3(v) * tint;
  gl_FragColor = vec4(c, a);
}
`

type SliceOpts = {
  /** additive: overlapping planes add up like an X-ray instead of piling into a white block */
  additive?: boolean
  colormap?: 0 | 1
  alphaRange?: [number, number]
  floorAlpha?: number
  tint?: THREE.ColorRepresentation
  opacity?: number
}

function sliceMaterial(tex: THREE.Texture, grid: [number, number], index: number, texels: [number, number],
  o: SliceOpts = {}): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    transparent: true,
    depthWrite: false,
    blending: o.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    side: THREE.DoubleSide,
    uniforms: {
      atlas: { value: tex },
      grid: { value: new THREE.Vector2(...grid) },
      index: { value: index },
      opacity: { value: o.opacity ?? 1 },
      alphaRange: { value: new THREE.Vector2(...(o.alphaRange ?? [0, 0.001])) },
      floorAlpha: { value: o.floorAlpha ?? 0 },
      colormap: { value: o.colormap ?? 0 },
      tint: { value: new THREE.Color(o.tint ?? 0xffffff) },
      reveal: { value: 1 },
      texels: { value: new THREE.Vector2(...texels) },
    },
  })
}

function prepTexture(tex: THREE.Texture): THREE.Texture {
  tex.colorSpace = THREE.NoColorSpace
  tex.minFilter = THREE.LinearFilter
  tex.magFilter = THREE.LinearFilter
  tex.generateMipmaps = false
  tex.needsUpdate = true
  return tex
}

/** Pack N (H x W) arrays into one 8-bit texture laid out like the WebP atlases. */
function dataAtlas(tiles: number[][][], normalise: 'tile' | 'global'): { tex: THREE.DataTexture; grid: [number, number] } {
  const n = tiles.length
  const h = tiles[0].length
  const w = tiles[0][0].length
  const cols = Math.ceil(Math.sqrt(n))
  const rows = Math.ceil(n / cols)
  const W = cols * w
  const H = rows * h
  const data = new Uint8Array(W * H)
  const globalMax = Math.max(...tiles.flat(2))
  tiles.forEach((tile, i) => {
    const max = normalise === 'tile' ? Math.max(...tile.flat()) : globalMax
    const c = i % cols
    const r = Math.floor(i / cols)
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const texRow = H - 1 - (r * h + y) // tile row 0 at the top, like an image
        data[texRow * W + c * w + x] = Math.round(255 * Math.min(1, tile[y][x] / (max || 1)))
      }
    }
  })
  const tex = new THREE.DataTexture(data, W, H, THREE.RedFormat, THREE.UnsignedByteType)
  prepTexture(tex)
  return { tex, grid: [cols, rows] }
}

// ---------------------------------------------------------------------------
// smoothing
// ---------------------------------------------------------------------------
class Eased {
  value: number
  target: number
  constructor(v = 0) { this.value = v; this.target = v }
  step(dt: number, rate = 5) {
    this.value += (this.target - this.value) * (1 - Math.exp(-dt * rate))
    if (Math.abs(this.target - this.value) < 1e-4) this.value = this.target
    return this.value
  }
}

/** A stack of textured planes, one per slice, lying flat and stacked upwards. */
class Stack {
  group = new THREE.Group()
  planes: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>[] = []
  opacity = new Eased(0)
  lift = new Eased(0)        // how far the highlighted slice is pulled out to the side
  highlight = -1
  baseOpacity: number

  constructor(tex: THREE.Texture, atlas: { count: number; cols: number; rows: number; tile: number },
    size: number, spacing: number, opts: SliceOpts & { every?: number; padded?: (i: number) => boolean }) {
    const every = opts.every ?? 1
    const geo = new THREE.PlaneGeometry(size, size)
    const n = atlas.count
    this.baseOpacity = opts.opacity ?? 0.03
    for (let i = 0; i < n; i += every) {
      const pad = opts.padded?.(i) ?? false
      const mat = sliceMaterial(tex, [atlas.cols, atlas.rows], i, [atlas.tile, atlas.tile], {
        ...opts,
        additive: opts.additive ?? true,
        tint: pad ? 0xff9a3c : opts.tint,
        floorAlpha: pad ? 1 : opts.floorAlpha,
      })
      const m = new THREE.Mesh(geo, mat)
      m.rotation.x = -Math.PI / 2
      m.position.y = (i + 0.5) * spacing - (n * spacing) / 2
      m.userData.index = i
      m.userData.floor = mat.uniforms.floorAlpha.value
      m.renderOrder = 1
      this.planes.push(m)
      this.group.add(m)
    }
  }

  update(dt: number) {
    const o = this.opacity.step(dt)
    const lift = this.lift.step(dt)
    this.group.visible = o > 0.005
    for (const p of this.planes) {
      const hi = p.userData.index === this.highlight
      p.material.uniforms.opacity.value = hi ? Math.min(1, o * 3) : o * this.baseOpacity
      p.material.uniforms.floorAlpha.value = hi ? 1 : p.userData.floor
      const blending = hi ? THREE.NormalBlending : THREE.AdditiveBlending
      if (p.material.blending !== blending) { p.material.blending = blending; p.material.needsUpdate = true }
      p.position.x = hi ? lift : 0
      p.renderOrder = hi ? 5 : 1
    }
  }
}

function label(text: string, className = ''): CSS2DObject {
  const div = document.createElement('div')
  div.className = `pointer-events-none rounded-md bg-black/70 px-2 py-1 font-mono text-[11px] leading-tight text-white whitespace-pre ${className}`
  div.textContent = text
  return new CSS2DObject(div)
}

export type StepId =
  | 'scan' | 'window' | 'preprocess' | 'tensor' | 'conv' | 'stages'
  | 'image-attention' | 'volume-attention' | 'hidden' | 'hazards' | 'ensemble'

const CAMERAS: Partial<Record<StepId, { pos: [number, number, number]; target: [number, number, number] }>> = {
  scan: { pos: [5.6, 3.4, 8.2], target: [0.9, 0, 0] },
  preprocess: { pos: [3.2, 4.4, 13.5], target: [1.9, 0, 0] },
  tensor: { pos: [0.5, 3.4, 19.5], target: [0, 0, 0] },
  conv: { pos: [2.1, 0.4, 13.2], target: [2.1, 0, 0] },
  stages: { pos: [0, 2.6, 12.5], target: [0, 0.1, 0] },
  'image-attention': { pos: [4.6, 4.4, 10.2], target: [1.3, 0.2, 0] },
  'volume-attention': { pos: [5.2, 3.4, 12.5], target: [0, 0, 0] },
}

// ---------------------------------------------------------------------------
export class VisualiserScene {
  private renderer: THREE.WebGLRenderer
  private labels: CSS2DRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(40, 1, 0.05, 200)
  private controls: OrbitControls
  private clock = new THREE.Clock()
  private raf = 0
  private resize: ResizeObserver
  private camPos = new THREE.Vector3(5, 3, 6)
  private camTarget = new THREE.Vector3()
  private camMoving = 0
  private disposables: { dispose(): void }[] = []

  private raw!: Stack
  private input!: Stack
  private copies: Stack[] = []
  private copiesSpread = new Eased(0)
  private conv = new THREE.Group()
  private convOpacity = new Eased(0)
  private kernel!: THREE.LineSegments
  private outPlane!: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>
  private convLine!: THREE.Line
  private convProgress = 0
  private convPlaying = true
  private blocks = new THREE.Group()
  private blockStacks: Stack[] = []
  private blocksOpacity = new Eased(0)
  private rfBox!: THREE.LineSegments
  private attn = new THREE.Group()
  private attnPlanes: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>[] = []
  private attnOpacity = new Eased(0)
  private slabSlice!: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>
  private slabY: (t: number) => number = () => 0
  private combined = new THREE.Group()
  private combinedOpacity = new Eased(0)
  private bars = new THREE.Group()
  private barsGrow = new Eased(0)
  private padLabels: CSS2DObject[] = []
  private selectedSlab = -1
  private reducedMotion: boolean
  private host: HTMLElement
  private data: VisualiserCase

  constructor(host: HTMLElement, data: VisualiserCase) {
    this.host = host
    this.data = data
    this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace
    this.renderer.setClearColor(0x000000, 0)
    host.appendChild(this.renderer.domElement)
    this.renderer.domElement.style.display = 'block'

    this.labels = new CSS2DRenderer()
    Object.assign(this.labels.domElement.style, { position: 'absolute', inset: '0', pointerEvents: 'none' })
    host.appendChild(this.labels.domElement)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.addEventListener('start', () => { this.camMoving = 0 })

    this.camera.position.copy(this.camPos)
    this.build()

    this.resize = new ResizeObserver(() => this.fit())
    this.resize.observe(host)
    this.fit()
    this.loop()
  }

  // --- construction ---------------------------------------------------------
  private texture(file: string) {
    const tex = prepTexture(new THREE.TextureLoader().load(caseUrl(file, this.data.case)))
    this.disposables.push(tex)
    return tex
  }

  private build() {
    const d = this.data
    const rawSize = d.dicom.extent_mm[0] * MM
    // slices can overlap: their spacing is the z extent over the count, not the thickness
    const rawSpacing = (d.dicom.extent_mm[2] / d.dicom.n_slices) * MM

    // 1. the raw stack, at its real size. In the lung window air is grey 0.22 and lung 0.33,
    //    so only fat, soft tissue and bone (above ~0.5) light up.
    this.raw = new Stack(this.texture(d.raw_atlas.file), d.raw_atlas, rawSize, rawSpacing, {
      alphaRange: [0.5, 1.0], opacity: 0.035,
    })
    this.scene.add(this.raw.group)

    // 2. the model's input: 200 slices at 2.5 mm, 256 px that really span 330/235 mm each
    const pxMm = d.dicom.extent_mm[0] / (d.preprocess.resampled[1] || 235)
    const inSize = 256 * pxMm * MM
    const inSpacing = d.preprocess.voxel_spacing_target[2] * MM
    const inTex = this.texture(d.input_atlas.file)
    const padded = (i: number) => i < d.preprocess.pad_slices_before || i > 199 - d.preprocess.pad_slices_after
    this.input = new Stack(inTex, d.input_atlas, inSize, inSpacing, {
      alphaRange: [0.5, 1.0], opacity: 0.035, padded,
    })
    this.scene.add(this.input.group)
    const h = 200 * inSpacing
    const before = label(`${d.preprocess.pad_slices_before} padding slices`)
    before.position.set(inSize / 2 - 0.5, -h / 2 + (d.preprocess.pad_slices_before * inSpacing) / 2, 0)
    const after = label(`${d.preprocess.pad_slices_after} padding slices`)
    after.position.set(inSize / 2 - 0.5, h / 2 - (d.preprocess.pad_slices_after * inSpacing) / 2, 0)
    this.padLabels = [before, after]
    this.input.group.add(before, after)

    // 3. three identical channels
    for (const [k, tint] of [[0, 0xff7b7b], [1, 0x7bff9a], [2, 0x7bb4ff]] as const) {
      const s = new Stack(inTex, d.input_atlas, inSize, inSpacing, { alphaRange: [0.5, 1.0], opacity: 0.06, tint, every: 2 })
      s.group.userData.k = k
      const l = label(`channel ${k}`)
      l.position.set(0, h / 2 + 0.25, 0)
      s.group.add(l)
      this.copies.push(s)
      this.scene.add(s.group)
    }

    this.buildConv(inTex, inSize)
    this.buildStages(inTex, inSize, inSpacing)
    this.buildAttention(inSize, inSpacing)
  }

  private buildConv(inTex: THREE.Texture, inSize: number) {
    const d = this.data
    const z = d.stem_voxel.input_slice
    const sep = 0.18 // exaggerated so the 3-slice depth of the kernel is visible
    const a = d.input_atlas
    const geo = new THREE.PlaneGeometry(inSize, inSize)
    const mid = this.texture(d.stem_voxel.input_slice_image)
    ;[-1, 0, 1].forEach((dz) => {
      const mat = dz === 0
        ? sliceMaterial(mid, [1, 1], 0, [256, 256], { floorAlpha: 1 })
        : sliceMaterial(inTex, [a.cols, a.rows], z + dz, [a.tile, a.tile], { floorAlpha: 1, opacity: 0.35 })
      const m = new THREE.Mesh(geo, mat)
      m.position.z = dz * sep
      m.renderOrder = 2 - dz
      this.conv.add(m)
    })
    const l = label(`input slices ${z - 1}–${z + 1}\n256 × 256`)
    l.position.set(0, inSize / 2 + 0.3, 0)
    this.conv.add(l)

    // the 3 x 7 x 7 kernel, at true scale on the 256 grid
    const k = d.architecture.stem.kernel
    const box = new THREE.BoxGeometry((k[2] / 256) * inSize, (k[1] / 256) * inSize, sep * (k[0] - 1) + 0.04)
    this.kernel = new THREE.LineSegments(new THREE.EdgesGeometry(box),
      new THREE.LineBasicMaterial({ color: 0x5eead4, transparent: true }))
    this.kernel.renderOrder = 10
    this.conv.add(this.kernel)

    // the filter's output map (128 x 128), revealed as the kernel moves
    const outTex = this.texture(d.stem_voxel.map)
    this.outPlane = new THREE.Mesh(geo, sliceMaterial(outTex, [1, 1], 0, [128, 128], { colormap: 1, floorAlpha: 1 }))
    this.outPlane.position.x = inSize + 0.6
    this.conv.add(this.outPlane)
    const ol = label(`filter ${d.stem_voxel.filter} of 64, after BN + ReLU\n128 × 128 (stride 2)`)
    ol.position.set(this.outPlane.position.x, inSize / 2 + 0.3, 0)
    this.conv.add(ol)

    const lineGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()])
    this.convLine = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: 0x5eead4, transparent: true, opacity: 0.8 }))
    this.conv.add(this.convLine)
    this.conv.position.x = 0
    this.scene.add(this.conv)
  }

  private buildStages(inTex: THREE.Texture, inSize: number, inSpacing: number) {
    const d = this.data
    const scale = 0.5
    const size = inSize * scale
    const height = 200 * inSpacing * scale
    const specs: { name: string; tex: THREE.Texture; atlas: Atlas; T: number; C: number; HW: number; colormap: 0 | 1 }[] = [
      { name: 'input', tex: inTex, atlas: d.input_atlas, T: 200, C: 3, HW: 256, colormap: 0 },
      ...d.stages.map((s) => ({
        name: s.name, tex: this.texture(s.mean_atlas.file), atlas: s.mean_atlas,
        T: s.shape[1], C: s.shape[0], HW: s.shape[2], colormap: 1 as const,
      })),
    ]
    const gapX = size + 1.1
    const gapY = height + 1.0
    specs.forEach((s, i) => {
      const every = Math.max(1, Math.ceil(s.T / 50))
      const planes = Math.ceil(s.T / every)
      const st = new Stack(s.tex, s.atlas, size, height / s.T, {
        colormap: s.colormap, alphaRange: s.colormap ? [0.04, 0.6] : [0.5, 1.0],
        // fewer planes would read dimmer; keep the summed brightness comparable
        opacity: (s.colormap ? 0.17 : 0.13) * Math.max(1, 50 / planes) * Math.min(1, 50 / planes + 0.5), every,
      })
      st.group.position.set(((i % 3) - 1) * gapX, i < 3 ? gapY / 2 : -gapY / 2, 0)
      const l = label(`${s.name}\n${s.C} × ${s.T} × ${s.HW} × ${s.HW}`)
      l.position.set(0, -height / 2 - 0.35, 0)
      st.group.add(l)
      // channel depth: a thin bar whose length grows with log2(channels)
      const bar = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.12 * Math.log2(s.C) + 0.05),
        new THREE.MeshBasicMaterial({ color: 0x94a3b8, transparent: true, opacity: 0.7 }))
      bar.position.set(-size / 2 - 0.12, -height / 2, 0)
      st.group.add(bar)
      this.blockStacks.push(st)
      this.blocks.add(st.group)
    })

    // receptive field of the hotspot layer4 voxel, drawn on the input block
    const rf = d.receptive_field.find((r) => r.stage === 'layer4')?.rf ?? [1, 1, 1]
    const hs = d.hotspot
    const zc = hs.slab * 8 + 4
    const yc = hs.y * 16 + 8
    const xc = hs.x * 16 + 8
    const clampSpan = (c: number, span: number, max: number) => {
      const lo = Math.max(0, c - span / 2)
      const hi = Math.min(max, c + span / 2)
      return [lo, hi]
    }
    const [z0, z1] = clampSpan(zc, rf[0], 200)
    const [y0, y1] = clampSpan(yc, rf[1], 256)
    const [x0, x1] = clampSpan(xc, rf[2], 256)
    const toX = (px: number) => (px / 256 - 0.5) * size
    const toY = (sl: number) => (sl / 200 - 0.5) * height
    const box = new THREE.BoxGeometry(toX(x1) - toX(x0), toY(z1) - toY(z0), toX(y1) - toX(y0))
    this.rfBox = new THREE.LineSegments(new THREE.EdgesGeometry(box),
      new THREE.LineBasicMaterial({ color: 0x5eead4, transparent: true }))
    this.rfBox.position.set((toX(x0) + toX(x1)) / 2, (toY(z0) + toY(z1)) / 2, (toX(y0) + toX(y1)) / 2)
    this.blockStacks[0].group.add(this.rfBox)
    const rfl = label(`receptive field of one\nlayer4 voxel: ${rf[0]} × ${rf[1]} × ${rf[2]}`)
    rfl.position.copy(this.rfBox.position).add(new THREE.Vector3(0, (toY(z1) - toY(z0)) / 2 + 0.25, 0))
    this.blockStacks[0].group.add(rfl)
    // ...and that voxel itself, on the last block
    const last = this.blockStacks[this.blockStacks.length - 1]
    const vox = new THREE.Mesh(new THREE.BoxGeometry(size / 16, height / 25, size / 16),
      new THREE.MeshBasicMaterial({ color: 0x5eead4, transparent: true, opacity: 0.9 }))
    vox.position.set(toX(xc), toY(zc), toX(yc))
    last.group.add(vox)
    this.scene.add(this.blocks)
  }

  private buildAttention(inSize: number, inSpacing: number) {
    const d = this.data
    const h = 200 * inSpacing
    const slabH = 8 * inSpacing
    const geo = new THREE.PlaneGeometry(inSize, inSize)
    const slabY = (t: number) => -h / 2 + (t * 8 + 4) * inSpacing
    this.slabY = slabY
    // the CT slice at the centre of the selected slab, lifted out beneath its attention map
    const a = d.input_atlas
    this.slabSlice = new THREE.Mesh(geo, sliceMaterial(this.input.planes[0].material.uniforms.atlas.value,
      [a.cols, a.rows], 0, [a.tile, a.tile], { floorAlpha: 1 }))
    this.slabSlice.rotation.x = -Math.PI / 2
    this.slabSlice.renderOrder = 2
    this.attn.add(this.slabSlice)

    // in-slab attention, mean of the five models, each slab scaled to its own peak
    const per = Array.from({ length: 25 }, (_, t) => {
      const mean = Array.from({ length: 256 }, (_, p) =>
        d.models.reduce((acc, m) => acc + m.image_attention[t][p], 0) / d.models.length)
      return Array.from({ length: 16 }, (_, y) => mean.slice(y * 16, y * 16 + 16))
    })
    const pa = dataAtlas(per, 'tile')
    this.disposables.push(pa.tex)
    for (let t = 0; t < 25; t++) {
      const m = new THREE.Mesh(geo, sliceMaterial(pa.tex, pa.grid, t, [16, 16], { colormap: 1, alphaRange: [0.2, 1.0], additive: true }))
      m.rotation.x = -Math.PI / 2
      m.position.y = slabY(t)
      m.renderOrder = 3
      m.userData.t = t
      this.attnPlanes.push(m)
      this.attn.add(m)
    }
    this.scene.add(this.attn)

    // the combined grid (in-slab x slab weight), scaled to the global peak: the 3D hotspot
    const ca = dataAtlas(d.attention_grid, 'global')
    this.disposables.push(ca.tex)
    for (let t = 0; t < 25; t++) {
      for (const dy of [-0.33, 0, 0.33]) {
        const m = new THREE.Mesh(geo, sliceMaterial(ca.tex, ca.grid, t, [16, 16], { colormap: 1, alphaRange: [0.05, 0.9], additive: true }))
        m.rotation.x = -Math.PI / 2
        m.position.y = slabY(t) + dy * slabH
        m.renderOrder = 3
        this.combined.add(m)
      }
    }
    this.scene.add(this.combined)

    // slab weights as bars: branch 1 on the right, branch 2 on the left
    const branches: [number[], number, number][] = [
      [d.models.map((m) => m.volume_attention).reduce((a, b) => a.map((v, i) => v + b[i] / d.models.length), Array(25).fill(0)), 1, 0x5eead4],
      [d.models.map((m) => m.volume_attention_2).reduce((a, b) => a.map((v, i) => v + b[i] / d.models.length), Array(25).fill(0)), -1, 0xf0abfc],
    ]
    const peak = Math.max(...branches.flatMap(([w]) => w))
    for (const [weights, side, color] of branches) {
      weights.forEach((w, t) => {
        const len = Math.max(0.01, (w / peak) * 1.8)
        const bar = new THREE.Mesh(new THREE.BoxGeometry(len, slabH * 0.8, 0.12),
          new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 }))
        bar.position.set(side * (inSize / 2 + 0.15 + len / 2), slabY(t), 0)
        bar.userData = { len, side, x: inSize / 2 + 0.15 }
        this.bars.add(bar)
      })
      const l = label(side > 0 ? 'branch 1: attention over slabs' : 'branch 2: max → conv1d → attention')
      l.position.set(side * (inSize / 2 + 1.0), h / 2 + 0.25, 0)
      this.bars.add(l)
    }
    this.scene.add(this.bars)
  }

  // --- control ----------------------------------------------------------------
  setStep(step: StepId) {
    const is = (...s: StepId[]) => s.includes(step)
    this.raw.opacity.target = is('scan') ? 1 : is('preprocess') ? 0.25 : 0
    this.raw.lift.target = is('scan') ? this.data.dicom.extent_mm[0] * MM * 0.75 : 0
    this.input.opacity.target = is('preprocess') ? 1 : is('image-attention', 'volume-attention') ? 0.35 : 0
    this.input.group.position.x = is('preprocess') ? 3.8 : 0
    this.padLabels.forEach((l) => { l.visible = is('preprocess') })
    for (const c of this.copies) c.opacity.target = is('tensor') ? 1 : 0
    this.copiesSpread.target = is('tensor') ? 1 : 0
    this.convOpacity.target = is('conv') ? 1 : 0
    this.blocksOpacity.target = is('stages') ? 1 : 0
    for (const s of this.blockStacks) s.opacity.target = this.blocksOpacity.target
    this.attnOpacity.target = is('image-attention') ? 1 : 0
    this.combinedOpacity.target = is('volume-attention') ? 1 : 0
    this.barsGrow.target = is('volume-attention') ? 1 : 0
    if (step === 'conv') this.convProgress = 0
    const cam = CAMERAS[step]
    if (cam) {
      this.camPos.set(...cam.pos)
      this.camTarget.set(...cam.target)
      this.camMoving = this.reducedMotion ? 0.001 : 1.6
      if (this.reducedMotion) {
        this.camera.position.copy(this.camPos)
        this.controls.target.copy(this.camTarget)
      }
    }
    if (this.reducedMotion) this.snap()
  }

  /** Lift one raw slice out of the stack (step 1). */
  setRawSlice(i: number) { this.raw.highlight = i }
  /** Raise one attention slab (step 7). */
  setSlab(t: number) { this.selectedSlab = t }
  setConvPlaying(on: boolean) { this.convPlaying = on }

  private snap() {
    const all = [this.raw, this.input, ...this.copies, ...this.blockStacks]
    for (const s of all) { s.opacity.value = s.opacity.target; s.lift.value = s.lift.target }
    for (const e of [this.copiesSpread, this.convOpacity, this.blocksOpacity, this.attnOpacity, this.combinedOpacity, this.barsGrow]) {
      e.value = e.target
    }
  }

  private fit() {
    const { clientWidth: w, clientHeight: h } = this.host
    if (!w || !h) return
    this.renderer.setSize(w, h)
    this.labels.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(0.05, this.clock.getDelta())

    if (this.camMoving > 0) {
      const k = 1 - Math.exp(-dt * 3.2)
      this.camera.position.lerp(this.camPos, k)
      this.controls.target.lerp(this.camTarget, k)
      this.camMoving -= dt
    }
    this.controls.update()

    this.raw.update(dt)
    this.input.update(dt)
    const spread = this.copiesSpread.step(dt)
    this.copies.forEach((c, k) => {
      c.update(dt)
      c.group.position.x = (k - 1) * 4.0 * spread
    })

    const co = this.convOpacity.step(dt)
    this.conv.visible = co > 0.005
    if (this.conv.visible) this.updateConv(dt, co)

    const bo = this.blocksOpacity.step(dt)
    this.blocks.visible = bo > 0.005
    for (const s of this.blockStacks) s.update(dt)
    ;(this.rfBox.material as THREE.LineBasicMaterial).opacity = bo

    const ao = this.attnOpacity.step(dt)
    this.attn.visible = ao > 0.005
    for (const p of this.attnPlanes) {
      const sel = p.userData.t === this.selectedSlab
      p.material.uniforms.opacity.value = ao * (this.selectedSlab < 0 || sel ? 0.9 : 0.25)
      p.position.x = sel ? 2.8 * ao : 0
      if (sel) p.position.y = this.slabY(p.userData.t) + 0.01
    }
    this.slabSlice.visible = this.selectedSlab >= 0
    if (this.slabSlice.visible) {
      this.slabSlice.material.uniforms.index.value = this.selectedSlab * 8 + 4
      this.slabSlice.material.uniforms.opacity.value = ao
      this.slabSlice.position.set(2.8 * ao, this.slabY(this.selectedSlab) - 0.01, 0)
    }

    const cmb = this.combinedOpacity.step(dt)
    this.combined.visible = cmb > 0.005
    this.combined.children.forEach((m) => {
      ((m as THREE.Mesh).material as THREE.ShaderMaterial).uniforms.opacity.value = cmb * 0.5
    })
    const g = this.barsGrow.step(dt, 3)
    this.bars.visible = g > 0.005
    this.bars.children.forEach((b) => {
      if (!(b as THREE.Mesh).isMesh) { b.visible = g > 0.5; return }
      const { len, side, x } = b.userData as { len: number; side: number; x: number }
      b.scale.x = Math.max(0.001, g)
      b.position.x = side * (x + (len * g) / 2)
    })

    this.renderer.render(this.scene, this.camera)
    this.labels.render(this.scene, this.camera)
  }

  private updateConv(dt: number, opacity: number) {
    const d = this.data
    const N = 128 * 128
    const target = d.stem_voxel.out_yx[0] * 128 + d.stem_voxel.out_yx[1]
    if (this.convPlaying && !this.reducedMotion) {
      // one full sweep in ~9 s, then park on the recorded voxel
      this.convProgress = Math.min(1, this.convProgress + dt / 9)
    } else {
      this.convProgress = 1
    }
    const idx = this.convProgress >= 1 ? target : Math.floor(this.convProgress * (N - 1))
    const oy = Math.floor(idx / 128)
    const ox = idx % 128
    const size = (this.outPlane.geometry as THREE.PlaneGeometry).parameters.width
    const inX = ((ox * 2 + 0.5) / 256 - 0.5) * size
    const inY = (0.5 - (oy * 2 + 0.5) / 256) * size
    this.kernel.position.set(inX, inY, 0)
    const outX = this.outPlane.position.x + ((ox + 0.5) / 128 - 0.5) * size
    const outY = (0.5 - (oy + 0.5) / 128) * size
    const pos = this.convLine.geometry.attributes.position as THREE.BufferAttribute
    pos.setXYZ(0, inX, inY, 0.12)
    pos.setXYZ(1, outX, outY, 0.01)
    pos.needsUpdate = true
    this.outPlane.material.uniforms.reveal.value = this.convProgress >= 1 ? 1 : idx / N
    this.conv.children.forEach((c) => {
      const m = (c as THREE.Mesh).material as THREE.Material & { uniforms?: Record<string, { value: number }> }
      if (m?.uniforms?.opacity) m.uniforms.opacity.value = opacity * (c.position.z === 0 ? 1 : 0.35)
      else if (m) (m as THREE.LineBasicMaterial).opacity = opacity
    })
  }

  dispose() {
    cancelAnimationFrame(this.raf)
    this.resize.disconnect()
    this.controls.dispose()
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh
      m.geometry?.dispose?.()
      const mat = m.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
      else mat?.dispose?.()
    })
    this.disposables.forEach((x) => x.dispose())
    this.renderer.dispose()
    this.renderer.domElement.remove()
    this.labels.domElement.remove()
  }
}
