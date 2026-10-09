import type { RoundStatusName } from '@/lib/api'

const STATUS_SHORT: Record<RoundStatusName, string> = {
  eligible: 'usable',
  excluded: 'usable but excluded',
  no_usable_series: 'no usable series',
  no_images: 'no scan',
}

/** Three marks, one per round: filled = usable, half = usable but excluded,
 *  dashed ring = imaged but unusable, empty = nothing. Labelled for screen readers. */
export function RoundDots({ rounds }: { rounds: { round: string; status: RoundStatusName }[] }) {
  const label = rounds.map((r) => `${r.round} ${STATUS_SHORT[r.status]}`).join(', ')
  return (
    <span className="inline-flex items-center gap-1" role="img" aria-label={label} title={label}>
      {rounds.map((r) => (
        <svg key={r.round} viewBox="0 0 12 12" className="size-3" aria-hidden>
          {r.status === 'eligible' && <circle cx="6" cy="6" r="5" fill="currentColor" />}
          {r.status === 'excluded' && (
            <>
              <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1" />
              <path d="M6 1.5a4.5 4.5 0 0 1 0 9z" fill="currentColor" />
            </>
          )}
          {r.status === 'no_usable_series' && (
            <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1"
              strokeDasharray="2 1.5" />
          )}
          {r.status === 'no_images' && (
            <circle cx="6" cy="6" r="4.5" fill="none" stroke="var(--border)" strokeWidth="1" />
          )}
        </svg>
      ))}
    </span>
  )
}
