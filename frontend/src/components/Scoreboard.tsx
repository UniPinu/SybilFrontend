import { Term } from '@/components/Glossary'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { Cohort } from '@/lib/api'
import { Info } from 'lucide-react'

type Props = {
  cohort: Cohort | undefined
  loading: boolean
  currentId: string | null
  onSelect: (patientId: string) => void
}

export function Scoreboard({ cohort, loading, currentId, onSelect }: Props) {
  const people = cohort?.people ?? []
  const maxRisk = Math.max(0.2, ...people.map((p) => p.risk_6y))

  return (
    <section id="scoreboard" className="section-anchor space-y-4">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold">How good is Sybil, really?</h2>
        <p className="max-w-2xl text-muted-foreground">
          Two different things: what the published study measured on thousands of unseen people, and
          what this handful of demo people happens to show.
        </p>
      </header>

      <Tabs defaultValue="published">
        <TabsList>
          <TabsTrigger value="published">Published results</TabsTrigger>
          <TabsTrigger value="demo">This demo's people</TabsTrigger>
        </TabsList>

        <TabsContent value="published" className="space-y-4 pt-4">
          <div className="grid gap-4 md:grid-cols-3">
            {loading && !cohort
              ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-48" />)
              : (cohort?.published ?? []).map((metric) => (
                  <Card key={metric.dataset} className="h-full">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">{metric.dataset}</CardTitle>
                      <CardDescription>{metric.detail}</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex gap-6">
                        <div>
                          <p className="text-3xl font-semibold tabular-nums">{metric.auc_1y}</p>
                          <p className="text-xs text-muted-foreground">
                            1-year <Term term="AUC">AUC</Term>
                          </p>
                        </div>
                        <div>
                          <p className="text-3xl font-semibold tabular-nums">{metric.c_index_6y}</p>
                          <p className="text-xs text-muted-foreground">
                            6-year <Term term="C-index">C-index</Term>
                          </p>
                        </div>
                      </div>
                      <p className="text-sm text-muted-foreground">{metric.plain}</p>
                    </CardContent>
                  </Card>
                ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Numbers from Mikhael et al., "Sybil: a validated deep learning model to predict future
            lung cancer risk from a single low-dose chest computed tomography", Journal of Clinical
            Oncology, 2023.
          </p>
        </TabsContent>

        <TabsContent value="demo" className="space-y-4 pt-4">
          <Alert>
            <Info className="size-4" />
            <AlertDescription>{cohort?.caveat}</AlertDescription>
          </Alert>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                Every person prepared on this machine ({people.length})
              </CardTitle>
              <CardDescription>
                Each dot is one scan, placed by its 6-year risk. Colour and shape both carry the
                outcome, so neither is doing the work alone.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {loading && !cohort ? (
                <Skeleton className="h-28" />
              ) : (
                <>
                  <div className="relative h-28 rounded-md border bg-muted/30 px-3">
                    {people.map((person) => {
                      const left = (person.risk_6y / maxRisk) * 100
                      const cancer = person.cancer_within_6y === true
                      return (
                        <Tooltip key={person.patient_id}>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              onClick={() => onSelect(person.patient_id)}
                              className={`absolute size-3.5 -translate-x-1/2 border-2 transition-transform hover:scale-150 focus-visible:scale-150 ${
                                cancer ? 'rounded-none rotate-45' : 'rounded-full'
                              } ${
                                person.patient_id === currentId
                                  ? 'ring-2 ring-foreground ring-offset-2 ring-offset-background'
                                  : ''
                              }`}
                              style={{
                                left: `${Math.min(97, Math.max(3, left))}%`,
                                top: `${20 + ((person.risk_6y * 997) % 55)}%`,
                                backgroundColor: cancer
                                  ? 'var(--outcome-cancer)'
                                  : 'var(--outcome-none)',
                                borderColor: 'var(--background)',
                              }}
                              aria-label={`${person.display_id}, 6-year risk ${(
                                person.risk_6y * 100
                              ).toFixed(1)} percent, ${
                                cancer ? 'was diagnosed' : 'no diagnosis'
                              }`}
                            />
                          </TooltipTrigger>
                          <TooltipContent>
                            <p className="font-medium">{person.display_id}</p>
                            <p>6-year risk {(person.risk_6y * 100).toFixed(1)}%</p>
                            <p>
                              {cancer
                                ? `diagnosed in year ${(person.years_to_cancer ?? 0) + 1}`
                                : `cancer-free through ${person.years_followed} years`}
                            </p>
                          </TooltipContent>
                        </Tooltip>
                      )
                    })}
                    <span className="absolute bottom-1 left-3 text-xs text-muted-foreground">0%</span>
                    <span className="absolute right-3 bottom-1 text-xs text-muted-foreground">
                      {(maxRisk * 100).toFixed(0)}%
                    </span>
                  </div>

                  <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                    <span className="flex items-center gap-2">
                      <span
                        className="size-3 rounded-full"
                        style={{ backgroundColor: 'var(--outcome-none)' }}
                      />
                      no diagnosis within 6 years
                    </span>
                    <span className="flex items-center gap-2">
                      <span
                        className="size-3 rotate-45"
                        style={{ backgroundColor: 'var(--outcome-cancer)' }}
                      />
                      diagnosed within 6 years
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge variant="outline" className="h-5 font-normal">
                        click a dot to load that person
                      </Badge>
                    </span>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    With this few people the ordering is illustrative only - one person moving would
                    change it. The published numbers above are the ones to trust.
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </section>
  )
}
