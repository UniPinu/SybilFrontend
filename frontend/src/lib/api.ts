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

async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(path))
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return parse<T>(
    await fetch(path, {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
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

export const api = {
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
    `/api/participants/${pid}/export.csv${queryString({ blind: blind || null })}`,
  sliceUrl: (id: string, index: number) =>
    `/api/patients/${id}/slices/${String(index).padStart(3, '0')}.webp`,
  overlayUrl: (id: string, index: number) =>
    `/api/patients/${id}/overlay/${String(index).padStart(3, '0')}.webp`,
  coronalUrl: (id: string) => `/api/patients/${id}/coronal.webp`,
}
