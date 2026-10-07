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
