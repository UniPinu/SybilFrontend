import { RoundDots } from '@/components/explore/RoundDots'
import { participantOutcomeText } from '@/components/explore/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError, READ_ONLY, type Facets, type ParticipantSummary } from '@/lib/api'
import { setParams, useSearchParams } from '@/lib/url'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, RotateCcw, Search } from 'lucide-react'
import { useEffect, useId, useState } from 'react'

/** URL keys the search owns. `participant` and `blind` belong to ExploreView. */
const FILTER_KEYS = [
  'q', 'sex', 'smoking', 'race', 'age_min', 'age_max', 'rounds_min', 'manufacturer',
  'diagnosed', 'has_results', 'sort', 'page',
] as const

const PAGE_SIZE = 25

const QUICK_PICKS: { label: string; blindOk: boolean; set: Record<string, string> }[] = [
  { label: 'Diagnosed, all 3 rounds usable', blindOk: false,
    set: { diagnosed: 'true', rounds_min: '3', sort: 'dx' } },
  { label: 'Already run', blindOk: true, set: { has_results: 'true', sort: '-results' } },
]

function clearedFilters() {
  return Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))
}

function Field({ label, children }: { label: string; children: (id: string) => React.ReactNode }) {
  const id = useId()
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">{label}</Label>
      {children(id)}
    </div>
  )
}

function FacetSelect({
  label, param, counts, value, anyLabel = 'Any',
}: {
  label: string
  param: string
  counts: Record<string, number> | undefined
  value: string | null
  anyLabel?: string
}) {
  return (
    <Field label={label}>
      {(id) => (
        <NativeSelect id={id} value={value ?? ''}
          onChange={(e) => setParams({ [param]: e.target.value, page: null })}>
          <option value="">{anyLabel}</option>
          {Object.entries(counts ?? {}).map(([name, n]) => (
            <option key={name} value={name}>{name} ({n.toLocaleString()})</option>
          ))}
        </NativeSelect>
      )}
    </Field>
  )
}

function Filters({ params, facets, blind }: {
  params: URLSearchParams
  facets: Facets | undefined
  blind: boolean
}) {
  const urlQ = params.get('q') ?? ''
  const [q, setQ] = useState(urlQ)
  const [seenUrlQ, setSeenUrlQ] = useState(urlQ)
  // Follow the URL when it changes elsewhere (clear, back button)...
  if (urlQ !== seenUrlQ) {
    setSeenUrlQ(urlQ)
    setQ(urlQ)
  }
  // ...and debounce typing into it.
  useEffect(() => {
    if (q === urlQ) return
    const timer = window.setTimeout(() => setParams({ q, page: null }, { replace: true }), 300)
    return () => window.clearTimeout(timer)
  }, [q, urlQ])

  const ageRange = facets?.age ?? [54, 75]
  const ages = Array.from({ length: ageRange[1] - ageRange[0] + 1 }, (_, i) => ageRange[0] + i)

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <Field label="Participant ID">
          {(id) => (
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input id={id} inputMode="numeric" placeholder="e.g. 1167" value={q}
                onChange={(e) => setQ(e.target.value.replace(/\D/g, ''))} className="pl-8" />
            </div>
          )}
        </Field>

        {!blind && (
          <Field label="Lung-cancer diagnosis">
            {(id) => (
              <NativeSelect id={id} value={params.get('diagnosed') ?? ''}
                onChange={(e) => setParams({ diagnosed: e.target.value, page: null })}>
                <option value="">Any</option>
                <option value="true">
                  Diagnosed{facets?.diagnosed != null ? ` (${facets.diagnosed.toLocaleString()})` : ''}
                </option>
                <option value="false">Not diagnosed</option>
              </NativeSelect>
            )}
          </Field>
        )}

        <Field label="Usable screening rounds">
          {(id) => (
            <NativeSelect id={id} value={params.get('rounds_min') ?? ''}
              onChange={(e) => setParams({ rounds_min: e.target.value, page: null })}>
              <option value="">Any</option>
              <option value="2">At least 2</option>
              <option value="3">All 3 ({(facets?.rounds['3'] ?? 0).toLocaleString()})</option>
            </NativeSelect>
          )}
        </Field>

        <div className="grid grid-cols-2 gap-2">
          {(['age_min', 'age_max'] as const).map((key) => (
            <Field key={key} label={key === 'age_min' ? 'Age from' : 'Age to'}>
              {(id) => (
                <NativeSelect id={id} value={params.get(key) ?? ''}
                  onChange={(e) => setParams({ [key]: e.target.value, page: null })}>
                  <option value="">Any</option>
                  {ages.map((a) => <option key={a} value={a}>{a}</option>)}
                </NativeSelect>
              )}
            </Field>
          ))}
        </div>

        <FacetSelect label="Sex" param="sex" counts={facets?.sex} value={params.get('sex')} />
        <FacetSelect label="Smoking" param="smoking" counts={facets?.smoking}
          value={params.get('smoking')} />
        <FacetSelect label="Race" param="race" counts={facets?.race} value={params.get('race')} />
        <FacetSelect label="Scanner make" param="manufacturer" counts={facets?.manufacturer}
          value={params.get('manufacturer')} />

        <Field label="Sybil results">
          {(id) => (
            <NativeSelect id={id} value={params.get('has_results') ?? ''}
              onChange={(e) => setParams({ has_results: e.target.value, page: null })}>
              <option value="">Any</option>
              <option value="true">
                At least one round run ({(facets?.with_results ?? 0).toLocaleString()})
              </option>
              <option value="false">Not run yet</option>
            </NativeSelect>
          )}
        </Field>

        <Button variant="ghost" size="sm" className="w-full"
          onClick={() => setParams(clearedFilters())}>
          <RotateCcw aria-hidden /> Clear filters
        </Button>
      </CardContent>
    </Card>
  )
}

function ResultsTable({ items, blind, onOpen }: {
  items: ParticipantSummary[]
  blind: boolean
  onOpen: (pid: string) => void
}) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <caption className="sr-only">Matching participants</caption>
        <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Participant</th>
            <th scope="col" className="px-3 py-2 font-medium">Age</th>
            <th scope="col" className="px-3 py-2 font-medium">Sex</th>
            <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">Smoking</th>
            <th scope="col" className="px-3 py-2 font-medium">Rounds</th>
            <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">Scanner</th>
            <th scope="col" className="px-3 py-2 font-medium">Run</th>
            {!blind && <th scope="col" className="px-3 py-2 font-medium">Outcome</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((p) => (
            <tr key={p.nlst_pid} className="border-t transition-colors hover:bg-muted/40">
              <th scope="row" className="px-3 py-2 text-left font-medium">
                <a
                  href={`?view=explore&participant=${p.nlst_pid}`}
                  className="rounded-sm font-mono underline-offset-4 hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey) return
                    e.preventDefault()
                    onOpen(p.nlst_pid)
                  }}
                >
                  {p.nlst_pid}
                </a>
              </th>
              <td className="px-3 py-2 tabular-nums">{p.age_at_randomization ?? '—'}</td>
              <td className="px-3 py-2">{p.sex ?? '—'}</td>
              <td className="hidden px-3 py-2 md:table-cell">
                {p.smoking_status?.replace(' smoker', '') ?? '—'}
              </td>
              <td className="px-3 py-2"><RoundDots rounds={p.rounds} /></td>
              <td className="hidden px-3 py-2 text-xs lg:table-cell">
                {p.manufacturers.join(', ') || '—'}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {p.results_ready > 0 ? (
                  <Badge variant="secondary">{p.results_ready} of {p.n_rounds}</Badge>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
              {!blind && (
                <td className="px-3 py-2">
                  {p.outcome?.diagnosed ? (
                    <span className="text-outcome-cancer-text" title={participantOutcomeText(p.outcome)}>
                      Diagnosed
                      {p.outcome.years_rand_to_dx != null && (
                        <span className="text-xs"> · yr {p.outcome.years_rand_to_dx.toFixed(1)}</span>
                      )}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">No diagnosis</span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ExploreSearch({ blind, onOpen }: { blind: boolean; onOpen: (pid: string) => void }) {
  const params = useSearchParams()
  const page = Number(params.get('page') ?? 1)
  const query = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k)]))
  if (blind) {
    // outcome filters are refused by the API in blind mode
    query.diagnosed = null
    if (query.sort?.replace('-', '') === 'dx') query.sort = null
  }

  const search = useQuery({
    queryKey: ['participants', query, blind],
    queryFn: () => api.searchParticipants({ ...query, blind: blind || null, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const data = search.data
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const first = data ? (data.page - 1) * data.page_size + 1 : 0
  const last = data ? Math.min(data.total, data.page * data.page_size) : 0
  const sortId = useId()

  return (
    <section className="space-y-6 pt-8" aria-labelledby="explore-heading">
      <header className="space-y-2">
        <h1 id="explore-heading" className="text-3xl font-semibold">Explore participants</h1>
        <p className="max-w-3xl text-muted-foreground">
          {READ_ONLY
            ? `Every NLST participant whose scans have already been through Sybil. Pick someone and
               see how Sybil's prediction changes from one yearly screening scan to the next.`
            : `Every NLST participant with at least one scan Sybil can read. Pick someone, choose
               which of their yearly screening scans to run, and see how Sybil's prediction changes
               from one scan to the next.`}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Quick picks:</span>
        {QUICK_PICKS.filter((pick) => !blind || pick.blindOk).map((pick) => (
          <Button key={pick.label} variant="outline" size="sm"
            onClick={() => setParams({ ...clearedFilters(), ...pick.set })}>
            {pick.label}
          </Button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Filters params={params} facets={data?.facets} blind={blind} />

        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground" aria-live="polite">
              {data
                ? data.total === 0
                  ? 'No participants match these filters.'
                  : `Showing ${first.toLocaleString()}–${last.toLocaleString()} of ${data.total.toLocaleString()} participants`
                : 'Loading participants…'}
            </p>
            <div className="flex items-center gap-2">
              <Label htmlFor={sortId} className="text-sm text-muted-foreground">Sort</Label>
              <div className="w-48">
                <NativeSelect id={sortId} value={params.get('sort') ?? 'id'}
                  onChange={(e) => setParams({ sort: e.target.value === 'id' ? null : e.target.value, page: null })}>
                  <option value="id">Participant ID</option>
                  <option value="age">Youngest first</option>
                  <option value="-age">Oldest first</option>
                  <option value="rounds">Most usable rounds</option>
                  <option value="-results">Most rounds run</option>
                  {!blind && <option value="dx">Earliest diagnosis</option>}
                </NativeSelect>
              </div>
            </div>
          </div>

          {search.isError ? (
            <Alert variant="destructive">
              <AlertDescription>
                {search.error instanceof ApiError
                  ? search.error.message
                  : 'Could not reach the backend. Is it running?'}
              </AlertDescription>
            </Alert>
          ) : !data ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-9" />)}
            </div>
          ) : (
            <div className={search.isPlaceholderData ? 'opacity-60 transition-opacity' : ''}>
              {data.items.length > 0 && <ResultsTable items={data.items} blind={blind} onOpen={onOpen} />}
            </div>
          )}

          {data && data.total > data.page_size && (
            <nav className="flex items-center justify-end gap-2" aria-label="Pages">
              <Button variant="outline" size="sm" disabled={page <= 1}
                onClick={() => setParams({ page: page - 1 > 1 ? page - 1 : null })}>
                <ChevronLeft aria-hidden /> Previous
              </Button>
              <span className="text-sm tabular-nums text-muted-foreground">
                Page {data.page} of {pages.toLocaleString()}
              </span>
              <Button variant="outline" size="sm" disabled={page >= pages}
                onClick={() => setParams({ page: page + 1 })}>
                Next <ChevronRight aria-hidden />
              </Button>
            </nav>
          )}

          <p className="text-xs text-muted-foreground">
            Rounds: <RoundDots rounds={[{ round: 'T0', status: 'eligible' }]} /> usable,{' '}
            <RoundDots rounds={[{ round: 'T0', status: 'excluded' }]} /> usable but outside
            Sybil's evaluation rules,{' '}
            <RoundDots rounds={[{ round: 'T0', status: 'no_usable_series' }]} /> imaged without a
            usable series, <RoundDots rounds={[{ round: 'T0', status: 'no_images' }]} /> no scan.
          </p>
        </div>
      </div>
    </section>
  )
}
