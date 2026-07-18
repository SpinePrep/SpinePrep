"""Reference analysis — a non-canonical demonstration of consuming the derivatives.

This is NOT part of the validated preprocessing pipeline (decision 3B; see
.claude/specs/reference-analysis.md). It is a worked example: native-space,
per-segmental-level cord resting-state connectivity, the canonical cord analysis
(Barry et al. 2014; Kaptan et al. 2023). It shows a new user how to apply the S8
confounds, use S7's PAM50 spinal-level atlas already in native space, and produce
a first-level output. It never runs during a normal `participant` call; invoke it
explicitly. Every output is stamped as a demonstration.

It deliberately does not: run a task GLM, do group statistics, threshold or
interpret connectivity, or push anything to template. Those are the analyst's.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import nibabel as nib

BANNER = "REFERENCE ANALYSIS -- demonstration, not validated preprocessing"


def _confound_design(confounds_tsv: Path) -> tuple[np.ndarray, list[str]]:
    """Build the confound design matrix from the S8 TSV.

    Uses every numeric column (motion + derivatives, cosine drift, CSF/aCompCor
    components, physio, and the one-hot spike/outlier columns), drops all-NaN or
    constant columns, fills residual NaNs with the column mean, and prepends an
    intercept. This is the whole point of S8's contract: one simultaneous
    regression, which is where the Carp 2013 filter-then-scrub concern is avoided.
    """
    df = pd.read_csv(confounds_tsv, sep="\t")
    num = df.select_dtypes(include=[np.number]).copy()
    # drop columns that carry no information for a GLM
    keep = [c for c in num.columns
            if num[c].notna().any() and num[c].nunique(dropna=True) > 1]
    X = num[keep].to_numpy(dtype=np.float64)
    # column-mean impute any remaining NaNs (e.g. derivative1 first frame)
    col_mean = np.nanmean(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_mean, inds[1])
    X = np.column_stack([np.ones(len(X)), X])   # intercept
    return X, ["intercept"] + keep


def _residualize(bold: np.ndarray, mask: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS-residualize each in-mask voxel time-course against the confounds X.

    Returns residuals of shape (n_voxels, T). One simultaneous regression, not a
    sequence -- the design's whole reason for existing.
    """
    Y = bold[mask].T                     # (T, n_vox)
    if X.shape[0] != Y.shape[0]:
        raise ValueError(f"confound rows {X.shape[0]} != BOLD frames {Y.shape[0]}")
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    return resid.T                       # (n_vox, T)


def run_reference_analysis(
    out_dir: Path,
    run_id: str,
    subject: str,
    session: Optional[str] = None,
) -> dict[str, Any]:
    """Demonstrate native-space per-level cord connectivity for one run.

    Consumes the S9 primary derivative + S8 confounds + S7 spinal-level atlas
    (all in native functional space) and writes a level x level correlation
    matrix, a heatmap, and provenance -- all under reference_analysis/ and all
    stamped as a demonstration.
    """
    out_dir = Path(out_dir)
    deriv = out_dir / "derivatives" / "spineprep"
    sub = f"sub-{subject}" if not subject.startswith("sub-") else subject
    func = deriv / sub / (f"ses-{session}" if session else "") / "func"
    func = Path(str(func).replace("//", "/"))

    bold_p = func / f"{run_id}_desc-preproc_bold.nii.gz"
    conf_p = func / f"{run_id}_desc-confounds_timeseries.tsv"
    levels_p = func / f"{run_id}_desc-PAM50spinallevels.nii.gz"
    cordmask_p = func / f"{run_id}_desc-PAM50cord_mask.nii.gz"

    missing = [p.name for p in (bold_p, conf_p, levels_p) if not p.exists()]
    if missing:
        return {"status": "SKIP", "run_id": run_id,
                "reason": f"missing inputs: {missing}", "banner": BANNER}

    ra_dir = out_dir / "reference_analysis" / sub
    ra_dir.mkdir(parents=True, exist_ok=True)

    bold = nib.load(bold_p).get_fdata().astype(np.float64)
    levels = nib.load(levels_p).get_fdata().astype(np.int32)
    if cordmask_p.exists():
        cord = nib.load(cordmask_p).get_fdata() > 0.5
    else:
        cord = levels > 0                 # fall back to any labelled voxel

    X, col_names = _confound_design(conf_p)
    resid = _residualize(bold, cord, X)   # (n_vox, T)

    # per-level mean residual time-course, restricted to the cord
    lvl_in_cord = levels[cord]
    uniq = sorted(int(v) for v in np.unique(lvl_in_cord) if v > 0)
    if len(uniq) < 2:
        return {"status": "SKIP", "run_id": run_id,
                "reason": f"need >=2 spinal levels, got {len(uniq)}", "banner": BANNER}
    ts = np.vstack([resid[lvl_in_cord == lv].mean(axis=0) for lv in uniq])  # (L, T)

    corr = np.corrcoef(ts)

    # outputs
    labels = [f"level_{lv}" for lv in uniq]
    cm = pd.DataFrame(corr, index=labels, columns=labels)
    cm_path = ra_dir / f"{run_id}_desc-levelconnectivity_matrix.tsv"
    cm.to_csv(cm_path, sep="\t")

    fig_path = ra_dir / f"{run_id}_desc-levelconnectivity_heatmap.png"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 4.2))
        im = ax.imshow(corr, vmin=-1, vmax=1, cmap="RdBu_r")
        ax.set_xticks(range(len(labels))); ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=90, fontsize=7)
        ax.set_yticklabels(labels, fontsize=7)
        ax.set_title(f"{run_id}\nper-level cord connectivity (native, confound-cleaned)",
                     fontsize=8)
        fig.colorbar(im, ax=ax, fraction=0.046, label="Pearson r")
        fig.text(0.5, 0.005, BANNER, ha="center", fontsize=6, color="#b00020")
        fig.tight_layout(rect=[0, 0.03, 1, 1])
        fig.savefig(fig_path, dpi=120); plt.close(fig)
    except Exception:
        fig_path = None

    prov = {
        "banner": BANNER,
        "run_id": run_id, "subject": sub, "session": session,
        "inputs": {"preproc_bold": bold_p.name, "confounds": conf_p.name,
                   "spinal_levels": levels_p.name},
        "n_confound_regressors": len(col_names),
        "confound_columns": col_names,
        "n_levels": len(uniq), "levels": uniq,
        "method": ("native-space per-spinal-level ROI connectivity: OLS-residualize "
                   "the confound design (one simultaneous regression), mean residual "
                   "per level in the cord, level x level Pearson correlation"),
        "note": ("Illustrative only. The confound selection, the ROI scheme, and the "
                 "connectivity measure are analyst choices SpinePrep does not make. "
                 "No thresholding, no group stats, nothing pushed to template."),
    }
    prov_path = ra_dir / f"{run_id}_reference_analysis.json"
    prov_path.write_text(json.dumps(prov, indent=2))

    return {
        "status": "OK", "run_id": run_id, "banner": BANNER,
        "n_levels": len(uniq), "n_confound_regressors": len(col_names),
        "outputs": {
            "matrix_tsv": str(cm_path.relative_to(out_dir)),
            "heatmap": str(fig_path.relative_to(out_dir)) if fig_path else None,
            "provenance": str(prov_path.relative_to(out_dir)),
        },
    }
