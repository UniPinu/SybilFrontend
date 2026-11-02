import { ExperimentView } from '@/components/experiment/ExperimentView'
import { ExploreView } from '@/components/explore/ExploreView'
import { FeaturesView } from '@/components/features/FeaturesView'
import { SiteFooter } from '@/components/SiteFooter'
import { StoryView } from '@/components/StoryView'
import { VisualiserView } from '@/components/visualiser/VisualiserView'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { goTo, useSearchParams } from '@/lib/url'
import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'

const HOME_SECTIONS = [
  ['align', 'Method'],
  ['question', 'Question'],
  ['person', 'Try it'],
  ['scoreboard', 'Scoreboard'],
] as const

const VIEWS = [
  { view: null, label: 'Homepage' },
  { view: 'explore', label: 'Explore' },
  { view: 'visualiser', label: 'Visualiser' },
  { view: 'experiment', label: 'Experiment' },
  { view: 'features', label: 'Features' },
] as const

/** Five views share one shell: the homepage (research + `?p=` story), Explore, the Visualiser, the Experiment and Features. */
export default function App() {
  const params = useSearchParams()
  const view = params.get('view')
  const home = !['explore', 'visualiser', 'experiment', 'features'].includes(view ?? '')

  return (
    <div className="min-h-dvh bg-background">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <a
            href="/"
            className="flex items-center gap-2 font-semibold"
            onClick={(e) => {
              e.preventDefault()
              goTo({})
            }}
          >
            <Activity className="size-5" aria-hidden />
            <span className="max-sm:sr-only">CTscannr</span>
          </a>
          {/* five views no longer fit beside the logo on a phone, so the switcher scrolls there */}
          <nav className="flex min-w-0 items-center gap-1 overflow-x-auto" aria-label="Main">
            {home &&
              HOME_SECTIONS.map(([id, label]) => (
                <Button key={id} variant="ghost" size="sm" asChild className="hidden lg:inline-flex">
                  <a href={`#${id}`}>{label}</a>
                </Button>
              ))}
            <div className="flex shrink-0 rounded-lg border p-0.5 sm:ml-2">
              {VIEWS.map((v) => {
                const active = (v.view ?? null) === (home ? null : view)
                return (
                  <Button key={v.label} variant={active ? 'secondary' : 'ghost'} size="sm"
                    aria-current={active ? 'page' : undefined}
                    onClick={() => goTo(v.view ? { view: v.view } : {})}>
                    {v.label}
                  </Button>
                )
              })}
            </div>
          </nav>
        </div>
      </header>

      {view === 'explore' ? <ExploreShell /> : view === 'visualiser' ? <VisualiserShell />
        : view === 'experiment' ? <ExperimentShell /> : view === 'features' ? <FeaturesShell /> : <StoryView />}
    </div>
  )
}

function VisualiserShell() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 20_000 })
  return (
    <main className="mx-auto max-w-7xl space-y-16 px-4 pb-10">
      <VisualiserView />
      <SiteFooter health={health.data} />
    </main>
  )
}

function ExperimentShell() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 20_000 })
  return (
    <main className="mx-auto max-w-6xl space-y-16 px-4 pb-10">
      <ExperimentView />
      <SiteFooter health={health.data} />
    </main>
  )
}

function ExploreShell() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 20_000 })
  return (
    <main className="mx-auto max-w-6xl space-y-16 px-4 pb-10">
      <ExploreView />
      <SiteFooter health={health.data} />
    </main>
  )
}

function FeaturesShell() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 20_000 })
  return (
    <main className="mx-auto max-w-6xl space-y-16 px-4 pb-10">
      <FeaturesView />
      <SiteFooter health={health.data} />
    </main>
  )
}
