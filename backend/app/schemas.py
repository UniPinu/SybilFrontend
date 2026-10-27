"""Response shapes for the API (MVP.md section 6.5).

Deliberately permissive: most fields can be absent while the cache is still
warming up, and the frontend renders skeletons for whatever is missing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    model_loaded: bool
    model_name: str
    device: str
    threads: int
    weights_present: bool
    candidates: Dict[str, Any]
    cache: Dict[str, Any]
    jobs: Dict[str, Any]
    published_metrics_url: Optional[str] = None


class PersonCard(BaseModel):
    patient_id: str
    display_id: str
    age: Optional[int] = None
    age_at_randomization: Optional[int] = None
    sex: Optional[str] = None
    smoking_status: Optional[str] = None
    race: Optional[str] = None
    screening_round: Optional[str] = None
    round_label: Optional[str] = None
    manufacturer: Optional[str] = None
    scanner_model: Optional[str] = None
    n_slices: Optional[int] = None
    thickness_mm: Optional[float] = None
    series_size_mb: Optional[float] = None
    kernel: Optional[str] = None
    in_regression_set: bool = False
    set: str = "live"
    ready: bool = False
    mode: Optional[str] = None


class RunStarted(BaseModel):
    job_id: Optional[str] = None
    patient_id: str
    ready: bool = False
    state: Optional[str] = None


class RiskResult(BaseModel):
    patient_id: str
    risk_by_year: List[float]
    risk_pct_by_year: List[float]
    headline_pct: float
    people_in_100: int
    raw_mean: Optional[List[float]] = None
    raw_per_model: Optional[List[List[float]]] = None
    n_slices: int
    width: int
    height: int
    slice_importance: List[float]
    hotspot_slice: int
    coronal_size: List[int]
    geometry: Dict[str, Any]
    timings: Dict[str, Any]
    model: Dict[str, Any]
    reference: Optional[Dict[str, Any]] = None
    band: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class Outcome(BaseModel):
    patient_id: str
    available: bool = True
    cancer_within_6y: Optional[bool] = None
    eligible: Optional[bool] = None
    exclusion_reason: Optional[str] = None
    years_to_cancer: Optional[int] = None
    diagnosis_year: Optional[int] = None
    years_followed: Optional[int] = None
    stage: Optional[str] = None
    lesion_size_mm: Optional[float] = None
    headline: Optional[str] = None
    detail: Optional[str] = None
    reminder: Optional[str] = None
    note: Optional[str] = None
    source: Optional[str] = None


class CohortEntry(BaseModel):
    patient_id: str
    display_id: str
    risk_6y: float
    risk_1y: float
    cancer_within_6y: Optional[bool] = None
    years_to_cancer: Optional[int] = None
    years_followed: Optional[int] = None
    set: str
    in_regression_set: bool = False
    age: Optional[int] = None
    sex: Optional[str] = None
    screening_round: Optional[str] = None


class Cohort(BaseModel):
    people: List[CohortEntry]
    caveat: str
    published: List[Dict[str, Any]]


# --- Explore: participants and their rounds ----------------------------------
class RoundStatus(BaseModel):
    round: str
    status: str


class ParticipantSummary(BaseModel):
    nlst_pid: str
    display_id: str
    age_at_randomization: Optional[int] = None
    sex: Optional[str] = None
    smoking_status: Optional[str] = None
    race: Optional[str] = None
    rounds: List[RoundStatus]
    n_rounds: int
    n_eligible: int
    manufacturers: List[str] = Field(default_factory=list)
    in_regression_set: bool = False
    results_ready: int = 0
    # absent in blind mode
    outcome: Optional[Dict[str, Any]] = None


class ParticipantPage(BaseModel):
    total: int
    page: int
    page_size: int
    blind: bool
    items: List[ParticipantSummary]
    facets: Dict[str, Any]


class RoundDetail(BaseModel):
    round: str
    study_yr: int
    status: str
    reason: Optional[str] = None
    runnable: bool
    years_since_rand: Optional[float] = None
    exam_id: Optional[str] = None
    age_at_scan: Optional[int] = None
    series: Optional[Dict[str, Any]] = None
    ready: bool = False
    job: Optional[Dict[str, Any]] = None
    outcome: Optional[Dict[str, Any]] = None


class ParticipantDetail(ParticipantSummary):
    blind: bool
    timeline: Dict[str, Any]
    rounds: List[RoundDetail]  # type: ignore[assignment]


class RunRequest(BaseModel):
    # omitted: every runnable round
    exam_ids: Optional[List[str]] = None


class RoundRun(BaseModel):
    exam_id: str
    round: str
    job_id: Optional[str] = None
    ready: bool
    state: Optional[str] = None


class ParticipantRuns(BaseModel):
    nlst_pid: str
    runs: List[RoundRun]


class ExamResult(BaseModel):
    exam_id: str
    round: str
    study_yr: int
    eligible: bool
    years_since_rand: Optional[float] = None
    age_at_scan: Optional[int] = None
    manufacturer: Optional[str] = None
    kernel: Optional[str] = None
    risk_by_year: List[float]
    risk_pct_by_year: List[float]
    band: Optional[str] = None
    hotspot_slice: Optional[int] = None
    n_slices: Optional[int] = None
    slice_importance: List[float] = []
    created_at: Optional[str] = None
    sybil_commit: Optional[str] = None
    change_from_previous: Optional[Dict[str, Any]] = None
    outcome: Optional[Dict[str, Any]] = None


class ParticipantResults(BaseModel):
    nlst_pid: str
    blind: bool
    timeline: Dict[str, Any]
    exams: List[ExamResult]
    reference: Optional[Dict[str, Any]] = None
    outcome: Optional[Dict[str, Any]] = None


class TrajectoryGuide(BaseModel):
    """The Experiment page: one participant's T0 + T1 -> T2 walk-through (app/experiment.py)."""
    nlst_pid: str
    outcome: Optional[Dict[str, Any]] = None
    scans: List[Dict[str, Any]]
    offset: float
    t2_offset: float
    align: Dict[str, Any]
    curve: List[Dict[str, Any]]
    forecast: Dict[str, Any]
    development: Dict[str, Any]
    network: Dict[str, Any]
    dataset: Dict[str, Any]
