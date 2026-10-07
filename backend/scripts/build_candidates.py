"""M1: build `data/candidates.parquet` -- every NLST exam we could demo.

No scans are downloaded here. It queries the local IDC index (DuckDB), parses
`SeriesDescription`, joins IDC's `nlst_prsn` clinical table and applies the same
exam-level filters Sybil's own NLST dataset applies. Takes a few seconds.

Run:  uv run python scripts/build_candidates.py
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from app.config import settings
from app.idc import get_clinical_client
from app.labels import describe_person, nlst_label, to_num
from app.regression_uids import NLST_REGRESSION_SERIES_UIDS

# MVP.md 5.2. NLST packs acquisition info into SeriesDescription, e.g.
#   "2,OPA,GE,LSPLUS,LUNG,360,2.5,120,80,0.1,1.5"
#    ^ round           ^ kernel  ^FOV ^ thickness(mm)
# Verified against the real index: field 1 = screening round, field 2 = series
# kind (OPA axial / OPL localizer), field 5 = kernel, field 6 = reconstruction
# FOV, field 7 = slice thickness. The backend re-checks SliceThickness from the
# DICOM header after download, because this parsing is derived from observed
# data rather than from a published spec.
CANDIDATE_SQL = """
WITH s AS (
  SELECT PatientID, StudyInstanceUID, SeriesInstanceUID, SeriesDescription,
         TRY_CAST(split_part(SeriesDescription, ',', 1) AS INT)    AS study_yr,
         split_part(SeriesDescription, ',', 2)                     AS kind,
         split_part(SeriesDescription, ',', 5)                     AS kernel,
         TRY_CAST(split_part(SeriesDescription, ',', 6) AS DOUBLE) AS fov_mm,
         TRY_CAST(split_part(SeriesDescription, ',', 7) AS DOUBLE) AS thickness_mm,
         instanceCount, series_size_MB, Manufacturer
  FROM index
  WHERE collection_id = 'nlst' AND Modality = 'CT'
), ok AS (
  SELECT * FROM s
  WHERE kind = 'OPA'
    AND thickness_mm BETWEEN 1.0 AND 2.5
    AND series_size_MB <= {max_mb}
    AND instanceCount >= 80
    AND study_yr IN (0, 1, 2)
), best AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY StudyInstanceUID
                               ORDER BY thickness_mm, series_size_MB) AS rk
  FROM ok
)
SELECT * EXCLUDE (rk) FROM best WHERE rk = 1
"""

PRSN_COLUMNS = [
    "dicom_patient_id", "age", "gender", "race", "cigsmok",
    "scr_days0", "scr_days1", "scr_days2",
    "candx_days", "cancyr", "canc_free_days", "de_stag", "lesionsize", "can_scr",
]


def build(max_mb: float) -> pd.DataFrame:
    client = get_clinical_client()

    t0 = time.time()
    series = client.sql_query(CANDIDATE_SQL.format(max_mb=max_mb))
    print(f"index query: {len(series):,} axial series (thinnest per exam)"
          f" in {time.time() - t0:.1f}s")

    prsn = client.get_clinical_table("nlst_prsn")
    missing = [c for c in PRSN_COLUMNS if c not in prsn.columns]
    if missing:
        raise SystemExit(
            f"nlst_prsn is missing columns this build needs: {missing}\n"
            "Run scripts/inspect_data.py and adapt app/labels.py (MVP.md 5.1)."
        )
    prsn = prsn[PRSN_COLUMNS].copy()
    print(f"nlst_prsn: {len(prsn):,} participants, {len(prsn.columns)} columns used")

    df = series.merge(prsn, left_on="PatientID", right_on="dicom_patient_id", how="inner")
    print(f"joined: {len(df):,} exams from {df.PatientID.nunique():,} participants")

    regression = set(NLST_REGRESSION_SERIES_UIDS)
    rows = []
    dropped: dict[str, int] = {}
    for row in df.itertuples(index=False):
        rec = row._asdict()
        yr = int(rec["study_yr"])
        label = nlst_label(rec, yr)
        if not label.valid:
            dropped[label.reason] = dropped.get(label.reason, 0) + 1
            continue
        rows.append(
            {
                "patient_id": f"{rec['PatientID']}_T{yr}",
                "nlst_pid": rec["PatientID"],
                "study_yr": yr,
                "study_uid": rec["StudyInstanceUID"],
                "series_uid": rec["SeriesInstanceUID"],
                "series_description": rec["SeriesDescription"],
                "manufacturer": rec["Manufacturer"],
                "kernel": rec["kernel"],
                "n_instances": int(rec["instanceCount"]),
                "series_size_mb": float(rec["series_size_MB"]),
                "thickness_mm": float(rec["thickness_mm"]),
                "fov_mm": to_num(rec["fov_mm"]),
                **describe_person(rec, yr),
                "cancer_within_6y": label.cancer_within_6y,
                "years_to_cancer": label.years_to_cancer,
                "years_followed": label.years_followed,
                "stage_code": to_num(rec["de_stag"]),
                "lesion_size_mm": to_num(rec["lesionsize"]),
                "in_regression_set": rec["SeriesInstanceUID"] in regression,
            }
        )

    if dropped:
        print("dropped exams (same rules as Sybil's skip_sample / check_label):")
        for reason, n in sorted(dropped.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>7,}  {reason}")
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame) -> None:
    print(f"\ncandidates: {len(df):,} exams from {df.nlst_pid.nunique():,} participants")
    print(f"  cancer within 6y: {int(df.cancer_within_6y.sum()):,}"
          f" ({100 * df.cancer_within_6y.mean():.1f}%)")
    print(f"  size MB   median {df.series_size_mb.median():.1f}"
          f"  p90 {df.series_size_mb.quantile(0.9):.1f}"
          f"  max {df.series_size_mb.max():.1f}")
    print(f"  slices    median {df.n_instances.median():.0f}"
          f"  range {df.n_instances.min()}-{df.n_instances.max()}")
    print(f"  thickness {dict(df.thickness_mm.value_counts().sort_index())}")
    print(f"  rounds    {dict(df.study_yr.value_counts().sort_index())}")
    print(f"  in upstream regression set: {int(df.in_regression_set.sum())} series")
    yrs = df.loc[df.cancer_within_6y, "years_to_cancer"]
    print(f"  years_to_cancer {dict(yrs.value_counts().sort_index())}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-mb", type=float, default=settings.max_series_mb,
                    help="series size cap in MB (default %(default)s)")
    ap.add_argument("--out", default=str(settings.candidates_path))
    args = ap.parse_args()

    settings.ensure_dirs()
    df = build(args.max_mb)
    if df.empty:
        print("no candidates -- refusing to write an empty parquet", file=sys.stderr)
        return 1
    summarise(df)
    df.to_parquet(args.out, index=False)
    mb = len(df.to_parquet(index=False)) / 1e6
    print(f"\nwrote {args.out} ({mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
