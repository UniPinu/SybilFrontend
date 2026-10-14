/** The recorded Sybil run the Visualiser replays (backend/scripts/capture_visualiser.py). */
import { useQuery } from '@tanstack/react-query'

export const VISUALISER_CASE = '217203_T2'
export const caseUrl = (file: string, id = VISUALISER_CASE) => `/visualiser/${id}/${file}`

export type Atlas = {
  file: string
  count: number
  cols: number
  rows: number
  tile: number
  lo: number
  hi: number
  bytes: number
}

export type LogLine = { t: number; step: string; message: string; [fact: string]: unknown }

export type StageRecord = {
  name: 'stem' | 'layer1' | 'layer2' | 'layer3' | 'layer4'
  /** [channels, slices, height, width] */
  shape: [number, number, number, number]
  z: number
  mean_atlas: Atlas
  channel_atlas: Atlas
  channel_ids: number[]
  per_slice: number[]
  zeroed_by_relu: number
}

export type ModelRecord = {
  image_attention: number[][]
  volume_attention: number[]
  volume_attention_2: number[]
  hidden_1: number[]
  hidden_2: number[]
  maxpool_hidden: number[]
  hidden_pre_relu: number[]
  hidden: number[]
  raw_hazard: number[]
  base_hazard: number
  cum_logit: number[]
  prob: number[]
  per_frame_max?: number[][]
  slab_features?: number[][] | null
  hazard_top_units?: number[]
  hazard_contrib_top?: number[][]
  hazard_bias?: number[]
}

export type VisualiserCase = {
  case: string
  person: {
    nlst_pid: string
    age: number | null
    sex: string | null
    smoking_status: string | null
    screening_round: string | null
    manufacturer: string | null
    scanner_model: string | null
    kernel: string | null
  }
  outcome: {
    cancer_within_6y: boolean | null
    years_to_cancer: number | null
    stage: string | null
    lesion_size_mm?: number | null
  } | null
  dicom: {
    n_slices: number
    rows: number
    cols: number
    pixel_spacing_mm: number[]
    thickness_mm: number
    extent_mm: number[]
    manufacturer: string
  }
  window: {
    center: number
    width: number
    lo_hu: number
    hi_hu: number
    slice: number
    hist: number[]
    hist_edges: number[]
    hu_range: [number, number]
    hu_image: string
    windowed_image: string
  }
  raw_atlas: Atlas
  preprocess: {
    img_mean: number
    img_std: number
    voxel_spacing_target: number[]
    resized: number[]
    resampled: number[]
    input: number[]
    pad_slices_before: number
    pad_slices_after: number
    pad_pixels: number[]
    value_range: number[]
    example_slice_in: number
    images: { resized: string; resampled: string; padded: string }
  }
  input_atlas: Atlas
  receptive_field: { stage: string; rf: number[]; jump: number[] }[]
  architecture: {
    stem: { kernel: number[]; stride: number[]; padding: number[]; out_channels: number }
    stages: { name: string; blocks: number }[]
    params_per_model: number
    dropout: number
  }
  stem_voxel: {
    filter: number
    input_slice: number
    out_yx: [number, number]
    in_yx: [number, number]
    patch: number[][][]
    weights: number[][][][]
    weights_summed: number[][][]
    dot: number
    bn: { gamma: number; beta: number; mean: number; var: number; eps: number }
    after_bn: number
    after_relu: number
    hooked_value: number
    all_filters_here: number[]
    map: string
    input_slice_image: string
  }
  stem_filters: number[][][][]
  stem_maps: Atlas
  stages: StageRecord[]
  models: ModelRecord[]
  ensemble: {
    raw_mean: number[]
    calibrated: number[]
    calibration_x: number[]
    calibration_curves: number[][]
  }
  attention_grid: number[][][]
  hotspot: { slab: number; y: number; x: number; input_slices: [number, number]; input_pixels: number[] }
  matches_cached_run?: boolean
  log: LogLine[]
}

export function useVisualiserCase(id = VISUALISER_CASE) {
  return useQuery({
    queryKey: ['visualiser-case', id],
    queryFn: async (): Promise<VisualiserCase> => {
      const response = await fetch(caseUrl('case.json', id))
      if (!response.ok) throw new Error(`No recorded run for ${id} (${response.status})`)
      return response.json()
    },
    staleTime: Infinity,
  })
}
