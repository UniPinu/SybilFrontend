import { ROUND_COLOR } from '@/components/explore/shared'
import type { RoundStatusName, Timeline as TimelineData } from '@/lib/api'

type Props = {
  timeline: TimelineData
  statuses: Record<string, RoundStatusName>
}

/** Years since enrolment, with the three screening rounds and (unless blind) the
 *  diagnosis or the last cancer-free date. The list underneath carries the same
 *  facts in text. */
export function Timeline({ timeline, statuses }: Props) {
  const points = [
    ...timeline.rounds.map((r) => r.years ?? 0),
    timeline.diagnosis_years ?? 0,
    timeline.last_cancer_free_years ?? 0,
  ]
  const span = Math.max(7, Math.ceil(Math.max(...points) + 0.5))
  const left = (years: number) => `${(years / span) * 100}%`
  const ticks = Array.from({ length: span + 1 }, (_, i) => i)
  const undated = timeline.rounds.filter((r) => r.years == null && statuses[r.round] !== 'no_images')

  return (
    <div className="space-y-3">
      <div className="relative mx-2 h-24" aria-hidden>
        {/* axis */}
        <div className="absolute top-12 right-0 left-0 h-px bg-border" />
        {ticks.map((t) => (
          <div key={t} className="absolute top-12" style={{ left: left(t) }}>
            <div className="h-1.5 w-px -translate-x-1/2 bg-border" />
            <span className="absolute top-2 -translate-x-1/2 text-[10px] text-muted-foreground tabular-nums">
              {t}
            </span>
          </div>
        ))}

        {timeline.last_cancer_free_years != null && (
          <div className="absolute top-6 h-12" style={{ left: left(timeline.last_cancer_free_years) }}>
            <div className="h-full w-0 -translate-x-1/2 border-l border-dashed border-outcome-none" />
            <span className="absolute top-[3.6rem] -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground">
              last cancer-free
            </span>
          </div>
        )}
        {timeline.diagnosis_years != null && (
          <div className="absolute top-6 h-12" style={{ left: left(timeline.diagnosis_years) }}>
            <div className="h-full w-0 -translate-x-1/2 border-l-2 border-outcome-cancer" />
            <span className="absolute -top-5 -translate-x-1/2 whitespace-nowrap rounded-sm bg-background px-1 text-[11px] font-medium text-outcome-cancer-text">
              diagnosis
            </span>
          </div>
        )}

        {timeline.rounds.map((r) =>
          r.years == null ? null : (
            <div key={r.round} className="absolute top-12" style={{ left: left(r.years) }}>
              <span
                className="absolute top-0 left-0 block size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background"
                style={{
                  background: statuses[r.round] === 'eligible' || statuses[r.round] === 'excluded'
                    ? ROUND_COLOR[r.round]
                    : 'var(--muted)',
                }}
              />
              <span className="absolute -top-7 -translate-x-1/2 text-xs font-medium"
                style={{ color: ROUND_COLOR[r.round] }}>
                {r.round}
              </span>
            </div>
          ),
        )}
      </div>
      <p className="text-center text-[11px] text-muted-foreground">years since enrolment</p>

      <ul className="sr-only">
        {timeline.rounds.map((r) => (
          <li key={r.round}>
            {r.round}: {r.years != null ? `${r.years.toFixed(1)} years after enrolment` : 'no date recorded'}
          </li>
        ))}
        {timeline.diagnosis_years != null && (
          <li>Diagnosis: {timeline.diagnosis_years.toFixed(1)} years after enrolment</li>
        )}
        {timeline.last_cancer_free_years != null && (
          <li>Last known cancer-free: {timeline.last_cancer_free_years.toFixed(1)} years after enrolment</li>
        )}
      </ul>
      {undated.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {undated.map((r) => r.round).join(', ')}: scan exists but the trial records no screening
          date, so it is not placed on the timeline.
        </p>
      )}
    </div>
  )
}
