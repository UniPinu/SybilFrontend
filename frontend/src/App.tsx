import { ExploreView } from '@/components/explore/ExploreView'
import { SiteFooter } from '@/components/SiteFooter'
import { StoryView } from '@/components/StoryView'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { goTo, useSearchParams } from '@/lib/url'
import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'

const STORY_SECTIONS = [
  ['person', 'Person'],
  ['scan', 'Scan'],
  ['run', 'Run'],
  ['prediction', 'Prediction'],
  ['scoreboard', 'Scoreboard'],
  ['about', 'About'],
] as const

/** Two views share one shell: the guided story (`?p=`) and Explore (`?view=explore`). */
export default function App() {
  const params = useSearchParams()
  const explore = params.get('view') === 'explore'

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
            Sybil Explorer
          </a>
          <nav className="flex items-center gap-1" aria-label="Main">
            {!explore &&
              STORY_SECTIONS.map(([id, label]) => (
                <Button key={id} variant="ghost" size="sm" asChild className="hidden lg:inline-flex">
                  <a href={`#${id}`}>{label}</a>
                </Button>
              ))}
            <div className="ml-2 flex rounded-lg border p-0.5">
              <Button variant={explore ? 'ghost' : 'secondary'} size="sm"
                aria-current={!explore ? 'page' : undefined} onClick={() => goTo({})}>
                Story
              </Button>
              <Button variant={explore ? 'secondary' : 'ghost'} size="sm"
                aria-current={explore ? 'page' : undefined} onClick={() => goTo({ view: 'explore' })}>
                Explore
              </Button>
            </div>
          </nav>
        </div>
      </header>

      {explore ? <ExploreShell /> : <StoryView />}
    </div>
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
