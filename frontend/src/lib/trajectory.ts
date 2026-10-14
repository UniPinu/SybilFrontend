/**
 * Putting Sybil predictions from successive scans on one clock.
 *
 * Sybil returns, for a scan taken at time t, the cumulative risk F(h) of a
 * diagnosis within h = 1..6 years of that scan. A later scan at t' > t is only
 * taken if the person is still cancer-free, so the earlier curve has to be
 * conditioned on surviving to t' before the two can be compared:
 *
 *   F~(h) = (F(h + d) - F(d)) / (1 - F(d)),   d = t' - t
 *
 * with F(0) = 0 and straight lines between the six yearly points.
 */

export type ScanCurve = {
  round: 'T0' | 'T1' | 'T2'
  /** years since enrolment */
  t: number
  /** Sybil's calibrated cumulative risk at 1..6 years after the scan */
  risk: number[]
}

export const HORIZONS = [1, 2, 3, 4, 5, 6]

export const logit = (p: number) => Math.log(p / (1 - p))
export const sigmoid = (x: number) => 1 / (1 + Math.exp(-x))

/** F(h) for any h in [0, 6]: F(0) = 0, linear between the yearly points. */
export function cumulativeAt(risk: number[], h: number): number {
  if (h <= 0) return 0
  if (h >= 6) return risk[5]
  const lo = Math.floor(h)
  const below = lo === 0 ? 0 : risk[lo - 1]
  return below + (risk[lo] - below) * (h - lo)
}

/** The earlier curve, conditioned on being cancer-free `d` years after its scan. */
export function rebase(risk: number[], d: number, h: number): number | null {
  if (h + d > 6) return null
  const atD = cumulativeAt(risk, d)
  return (cumulativeAt(risk, h + d) - atD) / (1 - atD)
}

export type OffsetPoint = {
  h: number
  /** earlier scan, rebased onto the later scan's clock */
  rebased: number
  /** what the later scan itself says */
  fresh: number
  /** logit(fresh) - logit(rebased) */
  delta: number
}

/** delta(h) for every horizon both scans cover. */
export function offsets(earlier: ScanCurve, later: ScanCurve): OffsetPoint[] {
  const d = later.t - earlier.t
  return HORIZONS.flatMap((h) => {
    const rebased = rebase(earlier.risk, d, h)
    if (rebased == null || rebased <= 0) return []
    const fresh = later.risk[h - 1]
    return [{ h, rebased, fresh, delta: logit(fresh) - logit(rebased) }]
  })
}

/**
 * Carry T1 forward to T2's clock and push it along the T0 -> T1 drift:
 *   logit F^(h) = logit F~_{1->2}(h) + alpha + lambda * delta_01(h)
 */
export function nudged(
  t0: ScanCurve,
  t1: ScanCurve,
  t2: ScanCurve,
  lambda: number,
  alpha = 0,
): { h: number; carried: number; nudged: number; actual: number }[] {
  const drift = new Map(offsets(t0, t1).map((p) => [p.h, p.delta]))
  return offsets(t1, t2).flatMap(({ h, rebased, fresh }) => {
    const delta = drift.get(h)
    if (delta == null) return []
    return [{ h, carried: rebased, nudged: sigmoid(logit(rebased) + alpha + lambda * delta), actual: fresh }]
  })
}

/** Mean squared error in logit space, e.g. a carried-forward curve against T2's own. */
export function logitMse(pairs: { predicted: number; actual: number }[]): number {
  if (!pairs.length) return 0
  return pairs.reduce((acc, p) => acc + (logit(p.predicted) - logit(p.actual)) ** 2, 0) / pairs.length
}

/** The least-squares lambda for one person (alpha fixed): sum(r * delta) / sum(delta^2). */
export function bestLambda(t0: ScanCurve, t1: ScanCurve, t2: ScanCurve, alpha = 0): number {
  const drift = new Map(offsets(t0, t1).map((p) => [p.h, p.delta]))
  let num = 0
  let den = 0
  for (const { h, rebased, fresh } of offsets(t1, t2)) {
    const delta = drift.get(h)
    if (delta == null) continue
    num += (logit(fresh) - logit(rebased) - alpha) * delta
    den += delta * delta
  }
  return den ? num / den : 0
}

/**
 * Participant 217203 (NLST), as Sybil scored their three screening scans on
 * this site. Diagnosed with stage IA lung cancer 2.28 years after enrolment.
 */
export const EXAMPLE = {
  pid: '217203',
  diagnosisYears: 2.28,
  stage: 'stage IA',
  scans: [
    { round: 'T0', t: 0.03, risk: [0.196761, 0.27827, 0.300763, 0.333692, 0.362623, 0.401879] },
    { round: 'T1', t: 0.95, risk: [0.351667, 0.463217, 0.508478, 0.530231, 0.573024, 0.652839] },
    { round: 'T2', t: 2.08, risk: [0.401667, 0.56875, 0.627222, 0.645079, 0.65619, 0.714978] },
  ] as ScanCurve[],
}

/** NLST, as indexed by backend/scripts/build_candidates.py. */
export const COHORT = {
  participants: 24_163,
  threeRounds: 19_758,
  threeRoundsDiagnosed: 458,
  diagnosedAfterT2: 452,
}
