"""M1: build the exam, candidate and participant tables from the IDC index.

No scans are downloaded here. It queries the local IDC index (DuckDB), parses
`SeriesDescription`, joins IDC's `nlst_prsn` clinical table and applies the same
exam-level filters Sybil's own NLST dataset applies (see app/catalog.py for what
each output holds). Takes a few seconds.

Run:  uv run python scripts/build_candidates.py
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from app.catalog import ROUNDS, assemble
from app.config import settings
from app.idc import get_clinical_client
from app.regression_uids import NLST_REGRESSION_SERIES_UIDS

# MVP.md 5.2. NLST packs acquisition info into SeriesDescription, e.g.
#   "2,OPA,GE,LSPLUS,LUNG,360,2.5,120,80,0.1,1.5"
#    ^ round           ^ kernel  ^FOV ^ thickness(mm)
# Verified against the real index: field 1 = screening round, field 2 = series
# kind (OPA axial / OPL localizer), field 5 = kernel, field 6 = reconstruction
# FOV, field 7 = slice thickness. The backend re-checks SliceThickness from the
# DICOM header after download, because this parsing is derived from observed
# data rather than from a published spec.
SERIES_CTE = """
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
)
"""

# One series per participant *and round*. Ranking per StudyInstanceUID instead
# let 47 participants keep two exams for the same round, because IDC holds two
# studies for them (some byte-identical).
CANDIDATE_SQL = SERIES_CTE + """
, ok AS (
  SELECT * FROM s
  WHERE kind = 'OPA'
    AND thickness_mm BETWEEN 1.0 AND 2.5
    AND series_size_MB <= {max_mb}
    AND instanceCount >= 80
    AND study_yr IN (0, 1, 2)
), best AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY PatientID, study_yr
                               ORDER BY thickness_mm, series_size_MB,
                                        SeriesInstanceUID) AS rk
  FROM ok
)
SELECT * EXCLUDE (rk) FROM best WHERE rk = 1
"""

# Every round that has *any* CT, so a participant page can tell "imaged, but
# nothing usable" apart from "no scan at all".
ROUNDS_SQL = SERIES_CTE + """
SELECT DISTINCT PatientID, study_yr FROM s WHERE study_yr IN (0, 1, 2)
"""

PRSN_COLUMNS = [
    "dicom_patient_id", "age", "gender", "race", "cigsmok",
    "scr_days0", "scr_days1", "scr_days2",
    "candx_days", "cancyr", "canc_free_days", "de_stag", "lesionsize", "can_scr",
]


def query(max_mb: float):
    client = get_clinical_client()

    t0 = time.time()
    series = client.sql_query(CANDIDATE_SQL.format(max_mb=max_mb))
    rounds_seen = client.sql_query(ROUNDS_SQL)
    print(f"index query: {len(series):,} axial series (thinnest per participant and round),"
          f" {len(rounds_seen):,} imaged rounds, in {time.time() - t0:.1f}s")

    prsn = client.get_clinical_table("nlst_prsn")
    missing = [c for c in PRSN_COLUMNS if c not in prsn.columns]
    if missing:
        raise SystemExit(
            f"nlst_prsn is missing columns this build needs: {missing}\n"
            "Run scripts/inspect_data.py and adapt app/labels.py (MVP.md 5.1)."
        )
    prsn = prsn[PRSN_COLUMNS].copy()
    print(f"nlst_prsn: {len(prsn):,} participants, {len(prsn.columns)} columns used")
    return series, rounds_seen, prsn


def summarise(exams: pd.DataFrame, df: pd.DataFrame, participants: pd.DataFrame,
              excluded: dict) -> None:
    print(f"\nexams with a usable series: {len(exams):,}")
    if excluded:
        print("excluded from evaluation (same rules as Sybil's skip_sample / check_label),"
              " still runnable in Explore:")
        for reason, n in sorted(excluded.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>7,}  {reason}")
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

    print(f"\nparticipants: {len(participants):,}"
          f" (diagnosed at any point: {int(participants.diagnosed.sum()):,})")
    print(f"  runnable rounds {dict(participants.n_rounds.value_counts().sort_index())}")
    for yr in ROUNDS:
        print(f"  T{yr} {dict(participants[f't{yr}_status'].value_counts())}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-mb", type=float, default=settings.max_series_mb,
                    help="series size cap in MB (default %(default)s)")
    args = ap.parse_args()

    settings.ensure_dirs()
    series, rounds_seen, prsn = query(args.max_mb)
    exams, df, participants, excluded = assemble(series, rounds_seen, prsn,
                                                 NLST_REGRESSION_SERIES_UIDS)
    if df.empty:
        print("no candidates -- refusing to write an empty parquet", file=sys.stderr)
        return 1
    summarise(exams, df, participants, excluded)
    for frame, path in ((exams, settings.exams_path), (df, settings.candidates_path),
                        (participants, settings.participants_path)):
        frame.to_parquet(path, index=False)
        print(f"wrote {path} ({path.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
