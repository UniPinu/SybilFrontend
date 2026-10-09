"""Synthetic IDC rows for the Explore tests: four made-up participants.

    900001  never diagnosed, all three rounds usable
    900002  diagnosed ~1.4 years in; T2 was imaged but has no screening date,
            so Sybil's rules exclude it (the real-data case that motivated this)
    900003  T0 usable, T1 imaged without a usable series, T2 never screened
    900004  imaged, but nothing usable: not a participant anyone can explore
"""
from __future__ import annotations

import pandas as pd

PRSN = pd.DataFrame([
    dict(dicom_patient_id="900001", age=60, gender=1, race=1, cigsmok=0,
         scr_days0="10", scr_days1="375", scr_days2="740",
         candx_days="", cancyr="", canc_free_days="2400", de_stag="", lesionsize="", can_scr=""),
    dict(dicom_patient_id="900002", age=68, gender=2, race=2, cigsmok=1,
         scr_days0="12", scr_days1="420", scr_days2="",
         candx_days="510", cancyr="1", canc_free_days="390", de_stag="120", lesionsize="",
         can_scr="1"),
    dict(dicom_patient_id="900003", age=56, gender=1, race=1, cigsmok=1,
         scr_days0="5", scr_days1="370", scr_days2="",
         candx_days="", cancyr="", canc_free_days="2300", de_stag="", lesionsize="", can_scr=""),
    dict(dicom_patient_id="900004", age=70, gender=2, race=1, cigsmok=0,
         scr_days0="8", scr_days1="", scr_days2="",
         candx_days="", cancyr="", canc_free_days="2000", de_stag="", lesionsize="", can_scr=""),
])


def series_row(pid: str, yr: int, *, maker="GE MEDICAL SYSTEMS", thickness=2.5, size=80.0,
               study=None, series=None) -> dict:
    return dict(
        PatientID=pid,
        StudyInstanceUID=study or f"study.{pid}.{yr}",
        SeriesInstanceUID=series or f"series.{pid}.{yr}",
        SeriesDescription=f"{yr},OPA,GE,LSULT,STANDARD,360,{thickness},120,80,0,1.4",
        study_yr=yr, kind="OPA", kernel="STANDARD", fov_mm=360.0, thickness_mm=thickness,
        instanceCount=150, series_size_MB=size, Manufacturer=maker,
    )


SERIES = pd.DataFrame([
    series_row("900001", 0),
    series_row("900001", 1, maker="SIEMENS"),
    series_row("900001", 2),
    series_row("900002", 0, maker="TOSHIBA"),
    series_row("900002", 1, maker="TOSHIBA"),
    series_row("900002", 2, maker="TOSHIBA"),
    series_row("900003", 0),
])

ROUNDS_SEEN = pd.DataFrame(
    [(pid, yr) for pid, yr in [("900001", 0), ("900001", 1), ("900001", 2),
                               ("900002", 0), ("900002", 1), ("900002", 2),
                               ("900003", 0), ("900003", 1), ("900004", 0)]],
    columns=["PatientID", "study_yr"],
)
