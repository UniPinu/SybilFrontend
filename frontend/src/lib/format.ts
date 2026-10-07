/** Numbers, colours and wording shared across the page (MVP.md sections 7.4, 8). */

export const YEARS = [1, 2, 3, 4, 5, 6]

export function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function inHundred(value: number): number {
  return Math.round(value * 100)
}

/** Calm sequential scale: teal -> amber -> deep orange. Never pure red, and
 *  never the only cue -- every use is paired with a number or a label. */
export const RISK_STOPS = [
  { upto: 0.02, color: 'var(--risk-1)', text: 'var(--risk-1-text)', label: 'low' },
  { upto: 0.05, color: 'var(--risk-2)', text: 'var(--risk-2-text)', label: 'modest' },
  { upto: 0.1, color: 'var(--risk-3)', text: 'var(--risk-3-text)', label: 'moderate' },
  { upto: 0.2, color: 'var(--risk-4)', text: 'var(--risk-4-text)', label: 'raised' },
  { upto: 1, color: 'var(--risk-5)', text: 'var(--risk-5-text)', label: 'high' },
]

function stopFor(risk: number) {
  return RISK_STOPS.find((stop) => risk <= stop.upto) ?? RISK_STOPS[RISK_STOPS.length - 1]
}

/** Fill colour: areas, dots, icon arrays. */
export function riskColor(risk: number): string {
  return stopFor(risk).color
}

/** Text and hairline-border colour: the same hue, dark enough to read. */
export function riskTextColor(risk: number): string {
  return stopFor(risk).text
}

export function riskWord(risk: number): string {
  return stopFor(risk).label
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

export function formatMb(bytes: number): string {
  return `${Math.round(bytes / 1e6)} MB`
}

/** "about 3 years after this scan" style helpers for the reveal. */
export function ordinalYear(index: number): string {
  return `year ${index + 1}`
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
