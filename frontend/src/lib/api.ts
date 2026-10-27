/** Typed access to the backend in MVP.md section 6.5. */

export type PersonCard = {
  patient_id: string
  display_id: string
  age: number | null
  age_at_randomization: number | null
  sex: string | null
  smoking_status: string | null
  race: string | null
  screening_round: string | null
  round_label: string | null
  manufacturer: string | null
  scanner_model: string | null
  n_slices: number | null
  thickness_mm: number | null
  series_size_mb: number | null
  kernel: string | null
  in_regression_set: boolean
  set: 'pool' | 'reference' | 'live'
  ready: boolean
  mode?: 'curated' | 'live'
}

export type ReferenceCurve = {
  n: number
  median: number[]
  p25: number[]
  p75: number[]
  p95: number[]
  note: string
}

export type RiskResult = {
  patient_id: string
  risk_by_year: number[]
  risk_pct_by_year: number[]
  headline_pct: number
  people_in_100: number
  raw_mean: number[] | null
  raw_per_model: number[][] | null
  n_slices: number
  width: number
  height: number
  slice_importance: number[]
  hotspot_slice: number
  coronal_size: number[]
  geometry: Record<string, unknown>
  timings: Record<string, number>
  model: Record<string, unknown>
  reference: ReferenceCurve | null
  band: {
    band?: string | null
    reference_median_6y?: number
    times_typical?: number | null
    note?: string
  }
  created_at: string | null
}

export type Outcome = {
  patient_id: string
  available: boolean
  cancer_within_6y: boolean | null
  eligible: boolean | null
  exclusion_reason: string | null
  years_to_cancer: number | null
  diagnosis_year: number | null
  years_followed: number | null
  stage: string | null
  lesion_size_mm: number | null
  headline: string | null
  detail: string | null
  reminder: string | null
  note: string | null
  source: string | null
}

export type CohortEntry = {
  patient_id: string
  display_id: string
  risk_6y: number
  risk_1y: number
  cancer_within_6y: boolean | null
  years_to_cancer: number | null
  years_followed: number | null
  set: 'pool' | 'reference' | 'live'
  in_regression_set: boolean
  age: number | null
  sex: string | null
  screening_round: string | null
}

export type PublishedMetric = {
  dataset: string
  detail: string
  auc_1y: number
  c_index_6y: number
  plain: string
}

export type Cohort = {
  people: CohortEntry[]
  caveat: string
  published: PublishedMetric[]
}

export type Health = {
  status: string
  model_loaded: boolean
  model_name: string
  device: string
  threads: number
  weights_present: boolean
  candidates: { available: boolean; exams?: number; participants?: number; cancer_within_6y?: number }
  cache: { cache_mb: number; patients_ready: number; pool: number; reference: number }
  jobs: { running: string | null; queued: string[] }
}

export type RunStarted = {
  job_id: string | null
  patient_id: string
  ready: boolean
  state: string | null
}

// --- Explore ------------------------------------------------------------------

export type RoundStatusName = 'eligible' | 'excluded' | 'no_usable_series' | 'no_images'

export type ParticipantOutcome = {
  diagnosed: boolean
  years_rand_to_dx: number | null
  years_rand_to_last_free?: number | null
  stage: string | null
  cancer_within_6y_any?: boolean
}

export type ParticipantSummary = {
  nlst_pid: string
  display_id: string
  age_at_randomization: number | null
  sex: string | null
  smoking_status: string | null
  race: string | null
  rounds: { round: string; status: RoundStatusName }[]
  n_rounds: number
  n_eligible: number
  manufacturers: string[]
  in_regression_set: boolean
  results_ready: number
  /** null in blind mode */
  outcome: ParticipantOutcome | null
}

export type Facets = {
  sex: Record<string, number>
  smoking: Record<string, number>
  race: Record<string, number>
  manufacturer: Record<string, number>
  rounds: Record<string, number>
  age: [number, number]
  with_results: number
  diagnosed?: number
}

export type ParticipantPage = {
  total: number
  page: number
  page_size: number
  blind: boolean
  items: ParticipantSummary[]
  facets: Facets
}

export type ExamOutcome = {
  cancer_within_6y: boolean | null
  years_to_cancer: number | null
  years_followed: number | null
}

export type RoundDetail = {
  round: string
  study_yr: number
  status: RoundStatusName
  reason: string | null
  runnable: boolean
  years_since_rand: number | null
  exam_id: string | null
  age_at_scan: number | null
  series: {
    manufacturer: string | null
    kernel: string | null
    thickness_mm: number | null
    n_instances: number | null
    series_size_mb: number | null
    in_regression_set: boolean
  } | null
  ready: boolean
  job: { job_id: string; state: string; position: number | null } | null
  outcome: ExamOutcome | null
}

export type Timeline = {
  rounds: { round: string; years: number | null }[]
  diagnosis_years: number | null
  last_cancer_free_years: number | null
}

export type ParticipantDetail = Omit<ParticipantSummary, 'rounds'> & {
  blind: boolean
  timeline: Timeline
  rounds: RoundDetail[]
}

export type RoundRun = {
  exam_id: string
  round: string
  job_id: string | null
  ready: boolean
  state: string | null
}

export type ExamResult = {
  exam_id: string
  round: string
  study_yr: number
  eligible: boolean
  years_since_rand: number | null
  age_at_scan: number | null
  manufacturer: string | null
  kernel: string | null
  risk_by_year: number[]
  risk_pct_by_year: number[]
  band: string | null
  hotspot_slice: number | null
  n_slices: number | null
  slice_importance: number[]
  created_at: string | null
  sybil_commit: string | null
  change_from_previous: { from_round: string; risk_by_year: number[] } | null
  outcome: ExamOutcome | null
}

export type ParticipantResults = {
  nlst_pid: string
  blind: boolean
  timeline: Timeline
  exams: ExamResult[]
  reference: ReferenceCurve | null
  outcome: ParticipantOutcome | null
}

export type SearchQuery = Record<string, string | number | boolean | null | undefined>

/** One point of the T0 + T1 -> T2 experiment, on T0's clock (backend/app/experiment.py). */
export type ClockPoint = { t: number; risk: number }

export type ModelMetrics = {
  mae_pp: number
  rmse_pp: number
  mae_6y_pp: number
  mae_by_year_pp: number[]
}

export type TrajectoryGuide = {
  nlst_pid: string
  outcome: { diagnosed: boolean; years_rand_to_dx: number | null; stage: string | null } | null
  scans: { round: 'T0' | 'T1' | 'T2'; years: number; risk_by_year: number[] }[]
  /** years from T0 to T1, the 13th input */
  offset: number
  /** years from T0 to T2 */
  t2_offset: number
  align: { base: number; t0: ClockPoint[]; t1_shifted: ClockPoint[]; t1_on_t0_clock: ClockPoint[] }
  curve: { t: number; combined: number; t0_only: number | null; t1_only: number | null; weight: number }[]
  forecast: {
    at: number
    curve_at_t2: number
    sybil_t2: number[]
    curve: number[]
    persistence: number[]
    curve_mae_pp: number
    persistence_mae_pp: number
  }
  network: { inputs: { name: string; value: number; x: number }[]; hidden: number; outputs: string[] }
  dataset: {
    file: string
    n_participants: number
    min_needed: number
    includes_this_participant: boolean
    metrics: Record<string, ModelMetrics> | null
    offset_effect:
      | { with: string; without: string; mean: number; lo: number; hi: number; a_better: number; n: number }[]
      | null
    this_participant: Record<string, number[]> | null
  }
}

function queryString(query: SearchQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/** Where the backend lives. Empty means same origin: Vite's proxy in dev, or FastAPI
 *  serving `dist`. Set VITE_API_BASE when the API is on another host. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

/** A read-only deploy answers from the static snapshot that
 *  backend/scripts/export_static.py writes, and never runs Sybil. */
export const READ_ONLY = import.meta.env.VITE_READ_ONLY === '1'

export const OFFLINE_MESSAGE =
  'Running Sybil is switched off on this site for now. It shows results that were already computed.'

async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(API_BASE + path))
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return parse<T>(
    await fetch(API_BASE + path, {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (READ_ONLY && response.status === 404) {
      throw new ApiError('Not part of this read-only version of the site.', 404)
    }
    let detail = response.statusText
    try {
      detail = (await response.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

// --- read-only snapshot ---------------------------------------------------------

/** The snapshot keeps the answer to `/api/x` (or `/api/x?blind=true`) at this path. */
function snap<T>(path: string, blind = false): Promise<T> {
  return get<T>(`${path}/index${blind ? '.blind' : ''}.json`)
}

let preparedIds: Promise<string[]> | null = null

function prepared(): Promise<string[]> {
  preparedIds ??= get<{ patient_ids: string[] }>('/api/patients/index.json').then(
    (body) => body.patient_ids,
    (error) => {
      preparedIds = null
      throw error
    },
  )
  return preparedIds
}

const SORTS: Record<string, (p: ParticipantSummary) => number | string | null> = {
  id: (p) => p.nlst_pid,
  age: (p) => p.age_at_randomization,
  rounds: (p) => -p.n_rounds,
  results: (p) => -p.results_ready,
  dx: (p) => p.outcome?.years_rand_to_dx ?? null,
}

function countBy(values: (string | null)[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const value of values) if (value != null) out[value] = (out[value] ?? 0) + 1
  return out
}

type ParticipantTable = {
  columns: string[]
  status: Record<string, RoundStatusName>
  dicts: { sex: string[]; smoking: string[]; race: string[]; manufacturer: string[]; stage: string[] }
  rows: [string, number | null, number | null, number | null, number | null, string, number, number,
    number[], number, number, number, number | null, number | null, number][]
}

let everyoneCache: Promise<ParticipantSummary[]> | null = null

/** Every participant, decoded from the snapshot's compact table (outcomes included). */
function everyone(): Promise<ParticipantSummary[]> {
  everyoneCache ??= get<ParticipantTable>('/api/participants/all.json').then(
    ({ status, dicts, rows }) => rows.map(([pid, age, sex, smoking, race, rounds, nRounds, nEligible,
      makes, inReg, ready, diagnosed, yearsToDx, stage, within6]) => ({
      nlst_pid: pid,
      display_id: `Participant ${pid}`,
      age_at_randomization: age,
      sex: sex == null ? null : dicts.sex[sex],
      smoking_status: smoking == null ? null : dicts.smoking[smoking],
      race: race == null ? null : dicts.race[race],
      rounds: [...rounds].map((c, k) => ({ round: `T${k}`, status: status[c] })),
      n_rounds: nRounds,
      n_eligible: nEligible,
      manufacturers: makes.map((m) => dicts.manufacturer[m]),
      in_regression_set: inReg === 1,
      results_ready: ready,
      outcome: {
        diagnosed: diagnosed === 1,
        years_rand_to_dx: yearsToDx,
        stage: stage == null ? null : dicts.stage[stage],
        cancer_within_6y_any: within6 === 1,
      },
    })),
    (error) => {
      everyoneCache = null
      throw error
    },
  )
  return everyoneCache
}

type Bundle = {
  detail: ParticipantDetail
  detail_blind: ParticipantDetail
  results: ParticipantResults
  results_blind: ParticipantResults
}

const bundles = new Map<string, Promise<Bundle>>()

/** One file per participant holds everything their page needs, normal and blind. */
function bundle(pid: string): Promise<Bundle> {
  let b = bundles.get(pid)
  if (!b) {
    b = get<Bundle>(`/api/participants/${pid}/bundle.json`)
    b.catch(() => bundles.delete(pid))
    bundles.set(pid, b)
  }
  return b
}

/** What `GET /api/participants` does on the server, over every participant in the snapshot. */
async function searchSnapshot(query: SearchQuery): Promise<ParticipantPage> {
  const blind = query.blind === true || query.blind === 'true'
  const all = await everyone()
  const text = (key: string) => (query[key] == null || query[key] === '' ? null : String(query[key]))
  const num = (key: string) => (text(key) == null ? null : Number(text(key)))

  const q = text('q')?.trim()
  const hits = all.filter((p) => {
    if (q && !p.nlst_pid.startsWith(q)) return false
    if (text('sex') && p.sex !== text('sex')) return false
    if (text('smoking') && p.smoking_status !== text('smoking')) return false
    if (text('race') && p.race !== text('race')) return false
    const age = p.age_at_randomization
    if (num('age_min') != null && (age == null || age < num('age_min')!)) return false
    if (num('age_max') != null && (age == null || age > num('age_max')!)) return false
    if (num('rounds_min') != null && p.n_rounds < num('rounds_min')!) return false
    if (text('manufacturer') && !p.manufacturers.includes(text('manufacturer')!)) return false
    if (text('diagnosed') != null && !blind
        && (p.outcome?.diagnosed ?? false) !== (text('diagnosed') === 'true')) return false
    if (text('has_results') != null && (p.results_ready > 0) !== (text('has_results') === 'true')) return false
    return true
  })

  const sort = text('sort') ?? 'id'
  const keyOf = SORTS[sort.replace(/^-/, '')] ?? SORTS.id
  const flip = sort.startsWith('-') ? -1 : 1
  hits.sort((a, b) => {
    const x = keyOf(a)
    const y = keyOf(b)
    if (x !== y) {
      if (x == null) return 1 // missing values last, either direction
      if (y == null) return -1
      return (x < y ? -1 : 1) * flip
    }
    return a.nlst_pid < b.nlst_pid ? -1 : 1
  })

  const pageSize = Math.max(1, Math.min(num('page_size') ?? 25, 100))
  const page = Math.max(1, num('page') ?? 1)
  facetsCache ??= facetsOf(all)
  const facets: Facets = { ...facetsCache }
  if (blind) delete facets.diagnosed
  return {
    total: hits.length,
    page,
    page_size: pageSize,
    blind,
    // blind mode hides every outcome, exactly as the server does
    items: hits.slice((page - 1) * pageSize, page * pageSize)
      .map((p) => (blind ? { ...p, outcome: null } : p)),
    facets,
  }
}

let facetsCache: Facets | null = null

/** The filter counts, computed once over everyone (the same numbers the server reports). */
function facetsOf(all: ParticipantSummary[]): Facets {
  let lo = Infinity
  let hi = -Infinity
  for (const p of all) {
    if (p.age_at_randomization == null) continue
    lo = Math.min(lo, p.age_at_randomization)
    hi = Math.max(hi, p.age_at_randomization)
  }
  const makes: Record<string, number> = {}
  for (const p of all) for (const m of p.manufacturers) makes[m] = (makes[m] ?? 0) + 1
  return {
    sex: countBy(all.map((p) => p.sex)),
    smoking: countBy(all.map((p) => p.smoking_status)),
    race: countBy(all.map((p) => p.race)),
    manufacturer: Object.fromEntries(Object.entries(makes).sort((a, b) => b[1] - a[1])),
    rounds: countBy(all.map((p) => String(p.n_rounds))),
    age: [lo, hi],
    with_results: all.filter((p) => p.results_ready > 0).length,
    diagnosed: all.filter((p) => p.outcome?.diagnosed).length,
  }
}

const readOnlyApi = {
  health: () => snap<Health>('/api/health'),
  randomPatient: async (_mode: 'curated' | 'live', exclude?: string) => {
    const ids = (await prepared()).filter((id) => id !== exclude)
    const id = ids[Math.floor(Math.random() * ids.length)]
    return { ...(await snap<PersonCard>(`/api/patients/${id}`)), mode: 'curated' as const }
  },
  patient: (id: string) => snap<PersonCard>(`/api/patients/${id}`),
  result: (id: string) => snap<RiskResult>(`/api/patients/${id}/result`),
  outcome: (id: string) => snap<Outcome>(`/api/patients/${id}/outcome`),
  cohort: () => snap<Cohort>('/api/cohort'),
  /** Prepared people replay their cached run, exactly as the live backend does. */
  run: async (id: string): Promise<RunStarted> => {
    if (!(await prepared()).includes(id)) throw new ApiError(OFFLINE_MESSAGE, 503)
    return { job_id: null, patient_id: id, ready: true, state: 'done' }
  },
  searchParticipants: searchSnapshot,
  participant: async (pid: string, blind: boolean) => {
    const b = await bundle(pid)
    return blind ? b.detail_blind : b.detail
  },
  runParticipant: async (_pid: string, _examIds: string[]): Promise<{ nlst_pid: string; runs: RoundRun[] }> => {
    throw new ApiError(OFFLINE_MESSAGE, 503)
  },
  participantResults: async (pid: string, blind: boolean) => {
    const b = await bundle(pid)
    return blind ? b.results_blind : b.results
  },
  exportUrl: (pid: string, blind: boolean) =>
    `${API_BASE}/api/participants/${pid}/export${blind ? '.blind' : ''}.csv`,
  trajectoryGuide: (pid: string) => snap<TrajectoryGuide>(`/api/experiments/trajectory/${pid}`),
}

// --- the API --------------------------------------------------------------------

const liveApi = {
  health: () => get<Health>('/api/health'),
  randomPatient: (mode: 'curated' | 'live', exclude?: string) =>
    get<PersonCard>(`/api/patients/random?mode=${mode}${exclude ? `&exclude=${exclude}` : ''}`),
  patient: (id: string) => get<PersonCard>(`/api/patients/${id}`),
  result: (id: string) => get<RiskResult>(`/api/patients/${id}/result`),
  outcome: (id: string) => get<Outcome>(`/api/patients/${id}/outcome`),
  cohort: () => get<Cohort>('/api/cohort'),
  run: (id: string) => post<RunStarted>(`/api/patients/${id}/run`),
  searchParticipants: (query: SearchQuery) =>
    get<ParticipantPage>(`/api/participants${queryString(query)}`),
  participant: (pid: string, blind: boolean) =>
    get<ParticipantDetail>(`/api/participants/${pid}${queryString({ blind: blind || null })}`),
  runParticipant: (pid: string, examIds: string[]) =>
    post<{ nlst_pid: string; runs: RoundRun[] }>(`/api/participants/${pid}/runs`, {
      exam_ids: examIds,
    }),
  participantResults: (pid: string, blind: boolean) =>
    get<ParticipantResults>(
      `/api/participants/${pid}/results${queryString({ blind: blind || null })}`,
    ),
  exportUrl: (pid: string, blind: boolean) =>
    `${API_BASE}/api/participants/${pid}/export.csv${queryString({ blind: blind || null })}`,
  trajectoryGuide: (pid: string) => get<TrajectoryGuide>(`/api/experiments/trajectory/${pid}`),
}

export const api = {
  ...(READ_ONLY ? readOnlyApi : liveApi),
  // images keep their URL paths in the snapshot, so these are the same either way
  sliceUrl: (id: string, index: number) =>
    `${API_BASE}/api/patients/${id}/slices/${String(index).padStart(3, '0')}.webp`,
  overlayUrl: (id: string, index: number) =>
    `${API_BASE}/api/patients/${id}/overlay/${String(index).padStart(3, '0')}.webp`,
  coronalUrl: (id: string) => `${API_BASE}/api/patients/${id}/coronal.webp`,
}
