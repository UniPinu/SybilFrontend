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

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
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
  run: async (id: string): Promise<RunStarted> => {
    const response = await fetch(`/api/patients/${id}/run`, { method: 'POST' })
    if (!response.ok) {
      let detail = response.statusText
      try {
        detail = (await response.json()).detail ?? detail
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(detail, response.status)
    }
    return response.json()
  },
  sliceUrl: (id: string, index: number) =>
    `/api/patients/${id}/slices/${String(index).padStart(3, '0')}.webp`,
  overlayUrl: (id: string, index: number) =>
    `/api/patients/${id}/overlay/${String(index).padStart(3, '0')}.webp`,
  coronalUrl: (id: string) => `/api/patients/${id}/coronal.webp`,
}
