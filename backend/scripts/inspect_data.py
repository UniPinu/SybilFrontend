"""M0 fact-check: print what IDC actually gives us.

Answers open questions 1 and 5 of MVP.md §10:
  * which indices exist, and how long the one-time clinical download takes;
  * the real column names of `nlst_prsn` and how missing values are coded;
  * whether the SeriesDescription parsing of MVP.md §5.2 holds on real rows.

Run:  uv run python scripts/inspect_data.py
"""
from __future__ import annotations

import sys
import time

import pandas as pd

from app.idc import get_client

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def main() -> int:
    t0 = time.time()
    client = get_client()
    print(f"IDCClient ready in {time.time() - t0:.1f}s")

    print("\n== indices available ==")
    try:
        print(client.indices_overview)
    except Exception as exc:  # pragma: no cover - informational
        print(f"  (indices_overview unavailable: {exc})")

    print("\n== main index: NLST CT series ==")
    df = client.sql_query(
        """
        SELECT PatientID, StudyInstanceUID, SeriesInstanceUID, SeriesDescription,
               Manufacturer, instanceCount, series_size_MB
        FROM index
        WHERE collection_id = 'nlst' AND Modality = 'CT'
        LIMIT 8
        """
    )
    print(df.to_string())
    n = client.sql_query(
        "SELECT COUNT(*) AS series, COUNT(DISTINCT PatientID) AS patients "
        "FROM index WHERE collection_id = 'nlst' AND Modality = 'CT'"
    )
    print(n.to_string(index=False))

    print("\n== clinical_index ==")
    t0 = time.time()
    client.fetch_index("clinical_index")
    print(f"fetch_index('clinical_index') took {time.time() - t0:.1f}s")
    tables = client.sql_query(
        "SELECT * EXCLUDE (values) FROM clinical_index WHERE collection_id = 'nlst'"
    )
    print(tables.to_string(index=False))

    print("\n== nlst_prsn ==")
    prsn = client.get_clinical_table("nlst_prsn")
    print(f"shape: {prsn.shape}")
    print("columns:")
    for col in sorted(prsn.columns):
        print(f"  {col:<28} {str(prsn[col].dtype):<10}")

    wanted = [
        "dicom_patient_id", "pid", "age", "gender", "pkyr", "cigsmok",
        "scr_days0", "scr_days1", "scr_days2", "candx_days", "cancyr",
        # the two we substitute for, and the ones we substitute with
        "fup_days", "lung_cancer", "canc_free_days", "canc_rpt_link", "de_stag",
    ]
    print("\nexpected columns present?")
    for col in wanted:
        print(f"  {col:<20} {'YES' if col in prsn.columns else 'missing'}")

    present = [c for c in wanted if c in prsn.columns]
    print("\nhead of the columns we need:")
    print(prsn[present].head(10).to_string())
    print("\nmissing-value coding (nulls / negatives / unique small values):")
    for col in present:
        s = prsn[col]
        line = f"  {col:<20} nulls={s.isna().sum():<7}"
        if pd.api.types.is_numeric_dtype(s):
            line += f" min={s.min()} max={s.max()}"
            neg = (s < 0).sum()
            line += f" negatives={neg}"
        else:
            line += f" uniques={s.unique()[:8]}"
        print(line)

    if "lung_cancer" in prsn.columns:
        print("\nlung_cancer value counts:")
        print(prsn["lung_cancer"].value_counts(dropna=False).to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
