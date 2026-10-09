/** Labels, colours and wording shared by the Explore components. */
import type { ExamOutcome, ParticipantOutcome, RoundStatusName } from '@/lib/api'

export const ROUND_COLOR: Record<string, string> = {
  T0: 'var(--round-0)',
  T1: 'var(--round-1)',
  T2: 'var(--round-2)',
}

/** Second cue next to colour on the chart, so rounds survive greyscale. */
export const ROUND_DASH: Record<string, string | undefined> = {
  T0: undefined,
  T1: '6 3',
  T2: '2 3',
}

export const ROUND_NAME: Record<string, string> = {
  T0: 'First scan (T0)',
  T1: 'Second scan (T1)',
  T2: 'Third scan (T2)',
}

export const STATUS_LABEL: Record<RoundStatusName, string> = {
  eligible: 'Usable',
  excluded: 'Excluded',
  no_usable_series: 'No usable series',
  no_images: 'No scan',
}

export function years(value: number | null | undefined, digits = 1): string {
  return value == null ? '—' : `${value.toFixed(digits)} y`
}

/** "Diagnosed 1.4 years after enrolment, stage IB" / "No diagnosis …". */
export function participantOutcomeText(outcome: ParticipantOutcome): string {
  if (outcome.diagnosed) {
    const when =
      outcome.years_rand_to_dx != null
        ? `${outcome.years_rand_to_dx.toFixed(1)} years after enrolment`
        : 'during the trial'
    const stage = outcome.stage?.startsWith('stage ') ? `, ${outcome.stage}` : ''
    return `Diagnosed with lung cancer ${when}${stage}`
  }
  const free = outcome.years_rand_to_last_free
  return free != null
    ? `No lung-cancer diagnosis; last known cancer-free ${free.toFixed(1)} years after enrolment`
    : 'No lung-cancer diagnosis on record'
}

/** What happened after one particular scan. */
export function examOutcomeText(outcome: ExamOutcome | null): string | null {
  if (!outcome) return null
  const ytc = outcome.years_to_cancer
  if (ytc != null && ytc < 0) return 'Taken after the diagnosis'
  if (outcome.cancer_within_6y) {
    return ytc === 0 ? 'Diagnosed within a year of this scan' : `Diagnosed in year ${(ytc ?? 0) + 1} after this scan`
  }
  if (ytc != null) return `Diagnosed in year ${ytc + 1} after this scan`
  if (outcome.years_followed != null) {
    const n = outcome.years_followed
    return `No diagnosis in ${n} year${n === 1 ? '' : 's'} of follow-up`
  }
  return null
}

/** Rough run-time estimate the UI quotes: ~90 s per round, one at a time. */
export function estimateMinutes(rounds: number): string {
  const minutes = Math.max(1, Math.round((rounds * 95) / 60))
  return `about ${minutes} minute${minutes === 1 ? '' : 's'}`
}
