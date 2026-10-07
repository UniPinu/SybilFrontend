import { Term } from '@/components/Glossary'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Toggle } from '@/components/ui/toggle'
import { api, type PersonCard, type RiskResult } from '@/lib/api'
import { Crosshair, Pause, Play } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

type Props = {
  person: PersonCard
  result: RiskResult | undefined
  overlayAvailable: boolean
}

const PRELOAD_RADIUS = 10

export function ScanViewer({ person, result, overlayAvailable }: Props) {
  const nSlices = result?.n_slices ?? person.n_slices ?? 0
  // Hooks run before the early return below, so everything that touches the
  // network has to know whether the images exist yet. In live mode they do not
  // until the pipeline has rendered them.
  const available = person.ready || !!result
  const [index, setIndex] = useState(() => Math.floor(nSlices / 2))
  const [playing, setPlaying] = useState(false)
  const [overlay, setOverlay] = useState(false)
  const [opacity, setOpacity] = useState(0.75)
  const [loaded, setLoaded] = useState(false)
  const cache = useRef(new Map<string, HTMLImageElement>())

  useEffect(() => {
    if (overlayAvailable) setOverlay(true)
  }, [overlayAvailable])

  const preload = useCallback(
    (centre: number) => {
      if (!nSlices || !available) return
      for (let offset = -PRELOAD_RADIUS; offset <= PRELOAD_RADIUS; offset += 1) {
        const i = centre + offset
        if (i < 0 || i >= nSlices) continue
        for (const url of [api.sliceUrl(person.patient_id, i), api.overlayUrl(person.patient_id, i)]) {
          if (cache.current.has(url)) continue
          const img = new Image()
          img.src = url
          cache.current.set(url, img)
        }
      }
    },
    [nSlices, available, person.patient_id],
  )

  useEffect(() => preload(index), [index, preload])

  useEffect(() => {
    if (!playing || !nSlices) return
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % nSlices), 60)
    return () => window.clearInterval(timer)
  }, [playing, nSlices])

  const importance = result?.slice_importance ?? []
  const peak = importance.length ? Math.max(...importance) : 1

  if (!available) {
    return (
      <section id="scan" className="section-anchor space-y-4">
        <h2 className="text-2xl font-semibold">Look at the scan</h2>
        <Card className="border-dashed">
          <CardContent className="py-10 text-center text-muted-foreground">
            This person's scan has not been downloaded yet. Start the run below: the scan appears as
            soon as it has been fetched and processed.
          </CardContent>
        </Card>
      </section>
    )
  }

  const jumpToHotspot = () => {
    if (result) {
      setPlaying(false)
      setIndex(result.hotspot_slice)
    }
  }

  return (
    <section id="scan" className="section-anchor space-y-4">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold">Look at the scan</h2>
        <p className="max-w-2xl text-muted-foreground">
          Scrub through the <Term term="slice">slices</Term> the way a radiologist would. This is a{' '}
          <Term term="low-dose CT">low-dose CT</Term>, windowed exactly as Sybil sees it.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_200px]">
        <Card className="overflow-hidden">
          <CardContent className="space-y-4 p-4">
            <div
              className="relative mx-auto aspect-square w-full max-w-[560px] touch-none overflow-hidden rounded-md border border-scan-panel-border bg-scan-panel"
              onWheel={(event) => {
                event.preventDefault()
                setPlaying(false)
                setIndex((i) => Math.min(nSlices - 1, Math.max(0, i + Math.sign(event.deltaY))))
              }}
              role="group"
              aria-label="CT slice viewer"
            >
              {!loaded && <Skeleton className="absolute inset-0" />}
              <img
                key={`${person.patient_id}-slice`}
                src={api.sliceUrl(person.patient_id, index)}
                alt={`CT slice ${index + 1} of ${nSlices}`}
                className="absolute inset-0 size-full object-contain"
                onLoad={() => setLoaded(true)}
                draggable={false}
              />
              {overlay && overlayAvailable && (
                <img
                  src={api.overlayUrl(person.patient_id, index)}
                  alt=""
                  aria-hidden
                  className="pointer-events-none absolute inset-0 size-full object-contain"
                  style={{ opacity }}
                  draggable={false}
                />
              )}
              <div className="absolute right-2 bottom-2 rounded bg-black/60 px-2 py-1 font-mono text-xs text-white">
                slice {index + 1} / {nSlices}
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Toggle
                pressed={playing}
                onPressedChange={setPlaying}
                aria-label={playing ? 'Pause cine' : 'Play cine'}
              >
                {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
              </Toggle>
              <Slider
                value={[index]}
                min={0}
                max={Math.max(0, nSlices - 1)}
                step={1}
                onValueChange={([value]) => {
                  setPlaying(false)
                  setIndex(value)
                }}
                aria-label="Slice"
                className="flex-1"
              />
            </div>

            {result && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">
                    Where Sybil looked, slice by slice
                  </p>
                  <Button variant="outline" size="sm" onClick={jumpToHotspot}>
                    <Crosshair className="size-4" aria-hidden />
                    Jump to hotspot
                  </Button>
                </div>
                <div
                  className="flex h-12 items-end gap-px"
                  role="img"
                  aria-label={`Attention per slice. The peak is at slice ${
                    result.hotspot_slice + 1
                  } of ${nSlices}. Use the slice slider above, or the jump-to-hotspot button, to move.`}
                >
                  {importance.map((value, i) => (
                    <button
                      key={i}
                      type="button"
                      tabIndex={-1}
                      aria-hidden
                      title={`Slice ${i + 1}: ${(100 * value).toFixed(1)}% of the attention`}
                      onClick={() => {
                        setPlaying(false)
                        setIndex(i)
                      }}
                      className="min-w-px flex-1 rounded-t transition-colors"
                      style={{
                        height: `${Math.max(4, (value / peak) * 100)}%`,
                        backgroundColor:
                          i === index ? 'var(--risk-5-text)' : 'var(--risk-3-text)',
                      }}
                    />
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  Brighter and taller = where Sybil paid most <Term term="attention">attention</Term>.
                  During training it was also taught to look where radiologists had marked{' '}
                  <Term term="nodule">nodules</Term>.
                </p>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-4 border-t pt-3">
              <div className="flex items-center gap-2">
                <Switch
                  id="overlay"
                  checked={overlay}
                  disabled={!overlayAvailable}
                  onCheckedChange={setOverlay}
                />
                <Label htmlFor="overlay" className="text-sm">
                  Attention overlay
                  {!overlayAvailable && (
                    <span className="block text-xs text-muted-foreground">
                      available once Sybil has run
                    </span>
                  )}
                </Label>
              </div>
              {overlay && overlayAvailable && (
                <div className="flex min-w-48 flex-1 items-center gap-2">
                  <Label htmlFor="overlay-opacity" className="text-xs text-muted-foreground">
                    opacity
                  </Label>
                  <Slider
                    id="overlay-opacity"
                    value={[opacity]}
                    min={0.1}
                    max={1}
                    step={0.05}
                    onValueChange={([value]) => setOpacity(value)}
                    className="flex-1"
                  />
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="h-fit">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Where you are</CardTitle>
            <CardDescription className="text-xs">
              Coronal view. Click to jump to that height.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <button
              type="button"
              className="relative block w-full overflow-hidden rounded-md border border-scan-panel-border bg-scan-panel"
              onClick={(event) => {
                const box = event.currentTarget.getBoundingClientRect()
                const fraction = (event.clientY - box.top) / box.height
                setPlaying(false)
                // the coronal map is drawn head-up, the slices run feet-first
                setIndex(Math.round((1 - fraction) * (nSlices - 1)))
              }}
              aria-label="Coronal map: click to jump to a height in the chest"
            >
              <img
                src={api.coronalUrl(person.patient_id)}
                alt="Coronal view of the chest"
                className="w-full"
                draggable={false}
              />
              <span
                className="pointer-events-none absolute right-0 left-0 h-0.5"
                style={{
                  backgroundColor: 'var(--risk-5-text)',
                  top: `${(1 - index / Math.max(1, nSlices - 1)) * 100}%`,
                }}
              />
            </button>
            {result && (
              <div className="pt-3 text-xs text-muted-foreground">
                <Badge variant="outline" className="font-normal">
                  hotspot: slice {result.hotspot_slice + 1}
                </Badge>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
