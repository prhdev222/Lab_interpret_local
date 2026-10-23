"""CKD-EPI 2021 creatinine equation (race-free), Inker et al., N Engl J Med 2021."""
from __future__ import annotations


def ckd_epi_2021(scr_mg_dl: float, age: float, sex: str) -> float:
    """sex: 'M' or 'F'. Returns mL/min/1.73 m2."""
    female = sex.upper() == "F"
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    ratio = scr_mg_dl / kappa
    egfr = 142 * (min(ratio, 1.0) ** alpha) * (max(ratio, 1.0) ** -1.200) * (0.9938 ** age)
    return egfr * 1.012 if female else egfr
