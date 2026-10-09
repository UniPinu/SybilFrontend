import { Term } from '@/components/Glossary'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import type { PersonCard } from '@/lib/api'
import { Dices, FileDown, Lock, Users } from 'lucide-react'

type Props = {
  person: PersonCard | undefined
  loading: boolean
  liveMode: boolean
  onLiveModeChange: (value: boolean) => void
  onPick: () => void
  onUseDemoScan: () => void
  /** go to Explore and choose someone deliberately */
  onBrowse: () => void
  /** no prepared people and no candidate list: offer the offline demo scan */
  offerDemoScan: boolean
  revealed: boolean
}

export function PersonSection({
  person,
  loading,
  liveMode,
  onLiveModeChange,
  onPick,
  onUseDemoScan,
  onBrowse,
  offerDemoScan,
  revealed,
}: Props) {
  return (
    <section id="person" className="section-anchor space-y-6">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold">Meet a person</h2>
        <p className="max-w-2xl text-muted-foreground">
          Everyone here took part in the National Lung Screening Trial. They were 55 to 74 years old
          and had smoked at least 30 <Term term="pack-years">pack-years</Term>. We know what happened
          to them afterwards - but you will not see it until Sybil has made its prediction.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-4">
        <Button size="lg" onClick={onPick} disabled={loading}>
          <Dices className="size-5" aria-hidden />
          {loading ? 'Picking…' : 'Pick a random person'}
        </Button>
        <Button variant="outline" size="lg" onClick={onBrowse}>
          <Users className="size-5" aria-hidden />
          Choose someone yourself
        </Button>
        {offerDemoScan && (
          <Button variant="outline" size="lg" onClick={onUseDemoScan}>
            <FileDown className="size-5" aria-hidden />
            Use the offline demo scan
          </Button>
        )}
        <div className="flex items-center gap-2">
          <Switch id="live-mode" checked={liveMode} onCheckedChange={onLiveModeChange} />
          <Label htmlFor="live-mode" className="text-sm">
            Live mode
            <span className="block text-xs text-muted-foreground">
              downloads a brand-new scan and runs it; takes a few minutes
            </span>
          </Label>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        {loading && !person ? (
          <Card>
            <CardHeader>
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-64" />
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-6 w-24" />
              ))}
            </CardContent>
          </Card>
        ) : person ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                {person.display_id}
                {person.set !== 'live' && (
                  <Badge variant="secondary" className="font-normal">
                    prepared in advance
                  </Badge>
                )}
                {person.set === 'live' && (
                  <Badge variant="secondary" className="font-normal">
                    live
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>
                {person.round_label}
                {person.manufacturer ? ` · ${person.manufacturer} scanner` : ''}
                {person.n_slices ? ` · ${person.n_slices} slices` : ''}
                {person.thickness_mm ? ` · ${person.thickness_mm} mm thick` : ''}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {person.age && <Badge variant="outline">{person.age} years old at this scan</Badge>}
                {person.sex && <Badge variant="outline">{person.sex}</Badge>}
                {person.smoking_status && <Badge variant="outline">{person.smoking_status}</Badge>}
                {person.screening_round && (
                  <Badge variant="outline">
                    <Term term="screening round">{person.screening_round}</Term>
                  </Badge>
                )}
              </div>
              {person.patient_id === 'demo_offline' ? (
                <p className="text-xs text-muted-foreground">
                  This is the example scan published with the Sybil code, not a trial participant.
                  There is no record of what happened afterwards, so there is nothing to reveal.
                </p>
              ) : (
              <p className="text-xs text-muted-foreground">
                Pack-years, education and the other questionnaire fields are not part of the public
                Imaging Data Commons extract, so they are not shown. No dates are shown either: the
                trial shifted them all before release.
                {person.in_regression_set &&
                  ' This scan is one of the 26 the Sybil authors use in their own regression test.'}
              </p>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed">
            <CardContent className="py-10 text-center text-muted-foreground">
              Press <span className="font-medium text-foreground">Pick a random person</span> to begin.
              {offerDemoScan && (
                <span className="mt-2 block text-sm">
                  Nobody is prepared yet. The offline demo scan - the one the Sybil authors ship with
                  the model - works without any download, but it has no outcome to reveal.
                </span>
              )}
            </CardContent>
          </Card>
        )}

        <Card
          className={
            revealed
              ? 'border-dashed opacity-60'
              : 'relative overflow-hidden border-dashed bg-muted/40'
          }
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Lock className="size-4" aria-hidden />
              What happened?
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {revealed ? (
              <p>Revealed below, next to the prediction.</p>
            ) : (
              <p>
                Sealed. We will open this after Sybil has made its prediction, so the model - and you -
                judge the scan first.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
