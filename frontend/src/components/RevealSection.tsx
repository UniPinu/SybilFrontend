import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { Outcome, RiskResult } from '@/lib/api'
import { Lock, Unlock } from 'lucide-react'

type Props = {
  outcome: Outcome | null
  result: RiskResult | undefined
  revealed: boolean
  canReveal: boolean
  onReveal: () => void
}

export function RevealSection({ outcome, result, revealed, canReveal, onReveal }: Props) {
  if (!canReveal) return null

  const cancer = outcome?.cancer_within_6y === true
  const accent = cancer ? 'var(--outcome-cancer)' : 'var(--outcome-none)'
  // the same hue, dark enough for small text and hairline borders
  const accentText = cancer ? 'var(--outcome-cancer-text)' : 'var(--outcome-none-text)'

  return (
    <section id="reveal" className="section-anchor space-y-4">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold">What actually happened</h2>
        <p className="max-w-2xl text-muted-foreground">
          The trial followed these people for years afterwards. Now that Sybil has committed to a
          number, here is the record.
        </p>
      </header>

      {/* Both faces share one grid cell, so the container is as tall as the
          taller of the two and the revealed card never overlaps what follows. */}
      <div className="[perspective:1600px]">
        <div className="flip-card grid" data-flipped={revealed}>
          {/* the face turned away is hidden from the camera, so hide it from
              the keyboard and screen readers too */}
          <Card
            className="flip-face col-start-1 row-start-1 border-dashed bg-muted/40"
            aria-hidden={revealed}
            inert={revealed || undefined}
          >
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Lock className="size-4" aria-hidden />
                Sealed
              </CardTitle>
              <CardDescription>
                Opening this does not change the prediction - it was made from the scan alone.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={onReveal} size="lg">
                <Unlock className="size-4" aria-hidden />
                Reveal what happened
              </Button>
            </CardContent>
          </Card>

          {revealed && outcome && (
            <Card
              className="flip-face flip-face-back col-start-1 row-start-1"
              style={{ borderColor: accent }}
              aria-hidden={!revealed}
              inert={!revealed || undefined}
            >
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant="outline"
                    style={{ borderColor: accentText, color: accentText }}
                    className="font-normal"
                  >
                    {outcome.available
                      ? cancer
                        ? 'diagnosed with lung cancer'
                        : 'no lung-cancer diagnosis'
                      : 'no outcome on record'}
                  </Badge>
                  {outcome.stage && <Badge variant="secondary">{outcome.stage}</Badge>}
                </div>
                <CardTitle className="pt-2 text-xl leading-snug text-balance">
                  {outcome.headline}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {outcome.detail && <p>{outcome.detail}</p>}
                {cancer && result && outcome.diagnosis_year && (
                  <p className="text-muted-foreground">
                    On the chart above, the dashed marker sits at year {outcome.diagnosis_year}, where
                    Sybil had put the risk at{' '}
                    {result.risk_pct_by_year[Math.min(outcome.diagnosis_year - 1, 5)]}%.
                  </p>
                )}
                {!cancer && outcome.available && (
                  <p className="text-muted-foreground">
                    Cancer-free through {outcome.years_followed} year
                    {outcome.years_followed === 1 ? '' : 's'} of follow-up. The trial's records stop
                    there; it is not a promise about the years after.
                  </p>
                )}
                <p className="border-t pt-3 text-xs text-muted-foreground">{outcome.reminder}</p>
                {outcome.source && (
                  <p className="text-xs text-muted-foreground">Source: {outcome.source}</p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </section>
  )
}
