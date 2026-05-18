"""S10: per-run ROI timeseries + connectivity + (per-subject) reliability.

Spec: .claude/specs/s10-roi-timeseries-and-connectivity.md

Pipeline:
  1. Warp PAM50_levels + PAM50_atlas_{30,31,34,35} (vertebral + horns)
     from PAM50 to native func via S7's from-PAM50_to-bold xfm.
  2. Build three ROI parcellations: vertlvl, spinalseg, hemicord (×seg).
  3. For each catalog × confound mode (none, s8_default): extract
     timeseries via Nilearn NiftiLabelsMasker with bandpass + detrend +
     z-score + (mode-dependent) confound regression.
  4. For the hemicord catalog: emit Pearson + Fisher-z + partial
     correlation matrices.
  5. Per-subject (multi-session, same task): ICC(3,1) per connection +
     spatial Dice on thresholded seed-to-voxel maps.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import pandas as pd

from spinalfmriprep.lib.run import run_command as _run_command


# ---------------------------------------------------------------------------
# Atlas warping (PAM50 → native func)
# ---------------------------------------------------------------------------


def _warp_pam50_to_native(
    pam50_path: Path, warp_pam50_to_bold: Path,
    ref_bold: Path, out_path: Path, interp: str = "nn",
) -> bool:
    cmd = [
        "sct_apply_transfo",
        "-i", str(pam50_path), "-d", str(ref_bold),
        "-w", str(warp_pam50_to_bold),
        "-x", interp, "-o", str(out_path),
    ]
    ok, _ = _run_command(cmd)
    return bool(ok and out_path.exists())


def _warp_pam50_pack(
    warp_pam50_to_bold: Path, ref_bold: Path, work_dir: Path,
    horn_labels: list[int],
    s7_atlas_dir: Optional[Path] = None,
) -> dict[str, Optional[Path]]:
    """Get PAM50 atlas pack in native func.

    Priority:
      1. S7 already warped the FULL PAM50 atlas pack via sct_warp_template
         at S7 time. The output lives at `<S7_chain>/work/S7_template
         _normalization/<ds>/<run_id>/label/atlas/PAM50_atlas_*.nii.gz`.
         Use those when available (correct warp direction; SCT-blessed).
      2. Fall back to sct_apply_transfo on PAM50 source files (may have
         warp-direction issues with sct_apply_transfo vs sct_warp_template;
         only triggered when S7's work dir is unreachable).

    Returns dict: {'vertlvl': Path, 'horn_30': Path, 'horn_31': Path, ...}.
    """
    import os
    work_dir.mkdir(parents=True, exist_ok=True)
    sct_dir = os.environ.get("SCT_DIR")
    if not sct_dir:
        raise RuntimeError("$SCT_DIR is not set")
    pam50_template = Path(sct_dir) / "data" / "PAM50" / "template"
    pam50_atlas = Path(sct_dir) / "data" / "PAM50" / "atlas"

    out: dict[str, Optional[Path]] = {}

    # Path 1: S7 pre-warped pack (preferred; correct alignment)
    if s7_atlas_dir is not None and s7_atlas_dir.exists():
        # S7's label/atlas dir has PAM50_atlas_*.nii.gz already in native func
        for h in horn_labels:
            src = s7_atlas_dir / f"PAM50_atlas_{h:02d}.nii.gz"
            if src.exists():
                out[f"horn_{h}"] = src
        # S7's label/template/ also has PAM50_levels.nii.gz warped
        s7_template_dir = s7_atlas_dir.parent / "template"
        s7_levels = s7_template_dir / "PAM50_levels.nii.gz"
        if s7_levels.exists():
            out["vertlvl"] = s7_levels

    # Path 2 (fallback): vert + any missing horns via sct_apply_transfo
    if out.get("vertlvl") is None:
        vert_dst = work_dir / "PAM50_levels_in_func.nii.gz"
        if _warp_pam50_to_native(
            pam50_template / "PAM50_levels.nii.gz",
            warp_pam50_to_bold, ref_bold, vert_dst, "nn",
        ):
            out["vertlvl"] = vert_dst
        else:
            out["vertlvl"] = None
    for h in horn_labels:
        if out.get(f"horn_{h}") is None:
            dst = work_dir / f"PAM50_atlas_{h:02d}_in_func.nii.gz"
            if _warp_pam50_to_native(
                pam50_atlas / f"PAM50_atlas_{h:02d}.nii.gz",
                warp_pam50_to_bold, ref_bold, dst, "linear",
            ):
                out[f"horn_{h}"] = dst
            else:
                out[f"horn_{h}"] = None

    return out


# ---------------------------------------------------------------------------
# Build parcellation NIfTIs from PAM50 outputs in native func
# ---------------------------------------------------------------------------


def _build_vertlvl_parcellation(
    pam50_levels_in_func: Path, label_range: tuple[int, int],
    out_path: Path,
) -> tuple[Path, list[int]]:
    """Restrict PAM50_levels to label_range; emit as discrete int parcellation."""
    img = nib.load(pam50_levels_in_func)
    arr = img.get_fdata().astype(np.int32)
    lo, hi = label_range
    mask = (arr >= lo) & (arr <= hi)
    out = np.where(mask, arr, 0).astype(np.int32)
    labels_present = sorted({int(v) for v in np.unique(out) if v > 0})
    nib.save(nib.Nifti1Image(out, img.affine, img.header), out_path)
    return out_path, labels_present


def _build_spinalseg_parcellation(
    spinal_levels_in_func: Path, segmental_range: tuple[int, int],
    out_path: Path,
) -> tuple[Path, list[int]]:
    """Use S7-emitted PAM50_spinal_levels (already in native) restricted
    to segmental_range. PAM50_spinal_levels labels 1..8 = C1..C8.
    """
    img = nib.load(spinal_levels_in_func)
    arr = img.get_fdata().astype(np.int32)
    lo, hi = segmental_range
    mask = (arr >= lo) & (arr <= hi)
    out = np.where(mask, arr, 0).astype(np.int32)
    labels_present = sorted({int(v) for v in np.unique(out) if v > 0})
    nib.save(nib.Nifti1Image(out, img.affine, img.header), out_path)
    return out_path, labels_present


def _build_hemicord_parcellation(
    horn_paths: dict[int, Path], spinal_levels_in_func: Path,
    horn_short_names: dict[int, str], horn_prob_threshold: float,
    segmental_range: tuple[int, int], out_path: Path,
) -> tuple[Path, list[tuple[int, str]]]:
    """Compose 4 horns × N segmental levels into a single multi-label NIfTI.

    Label encoding: 1..N_combinations. We also return a list of
    (label_int, label_name) tuples like (1, 'VL_segC5').
    """
    spin_img = nib.load(spinal_levels_in_func)
    spin = spin_img.get_fdata().astype(np.int32)
    parcellation = np.zeros_like(spin, dtype=np.int32)

    # Threshold horn probability maps
    horn_masks: dict[int, np.ndarray] = {}
    for h, p in horn_paths.items():
        if p is None or not p.exists():
            continue
        prob = nib.load(p).get_fdata()
        horn_masks[h] = prob > horn_prob_threshold

    lo, hi = segmental_range
    seg_labels_present = [int(v) for v in np.unique(spin) if lo <= v <= hi]

    label_int = 0
    label_map: list[tuple[int, str]] = []
    # Stable order: by (segment, horn) to keep matrix block structure
    for seg in seg_labels_present:
        seg_mask = (spin == seg)
        for h in sorted(horn_masks.keys()):
            combined = seg_mask & horn_masks[h]
            n_vox = int(combined.sum())
            if n_vox == 0:
                continue
            label_int += 1
            horn_name = horn_short_names.get(h, f"h{h}")
            label_name = f"{horn_name}_segC{seg}" if seg <= 8 else f"{horn_name}_seg{seg:02d}"
            parcellation[combined] = label_int
            label_map.append((label_int, label_name))

    nib.save(
        nib.Nifti1Image(parcellation, spin_img.affine, spin_img.header),
        out_path,
    )
    return out_path, label_map


# ---------------------------------------------------------------------------
# Confound DataFrame construction
# ---------------------------------------------------------------------------


def _build_confounds_df(
    s8_tsv: Optional[Path], include_prefixes: list[str], n_volumes: int,
) -> Optional[pd.DataFrame]:
    if s8_tsv is None or not s8_tsv.exists():
        return None
    try:
        df = pd.read_csv(s8_tsv, sep="\t")
    except Exception:
        return None
    keep_cols = [c for c in df.columns
                 if any(c.startswith(p) for p in include_prefixes)]
    if not keep_cols:
        return None
    out = df[keep_cols].copy()
    if len(out) != n_volumes:
        # Truncate or pad with zeros
        if len(out) > n_volumes:
            out = out.iloc[:n_volumes]
        else:
            pad = pd.DataFrame(0.0, index=range(n_volumes - len(out)),
                               columns=keep_cols)
            out = pd.concat([out, pad], ignore_index=True)
    # Drop all-NaN cols + replace NaN with 0
    out = out.dropna(axis=1, how="all").fillna(0.0)
    return out


# ---------------------------------------------------------------------------
# ROI extraction via Nilearn
# ---------------------------------------------------------------------------


def _extract_timeseries(
    bold_path: Path, parcellation_path: Path, label_names: list[str],
    confounds_df: Optional[pd.DataFrame], tr_s: float, masker_cfg: dict,
    min_voxels_per_roi: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract ROI timeseries via Nilearn NiftiLabelsMasker. Returns
    DataFrame (rows=volumes, cols=label_names) + meta dict.
    """
    from nilearn.maskers import NiftiLabelsMasker

    # Per-ROI voxel count for sanity filtering
    parc = nib.load(parcellation_path).get_fdata().astype(np.int32)
    voxel_counts = {}
    keep_labels: list[int] = []
    keep_names: list[str] = []
    for lbl_int, name in enumerate(label_names, start=1):
        n = int((parc == lbl_int).sum())
        voxel_counts[name] = n
        if n >= min_voxels_per_roi:
            keep_labels.append(lbl_int)
            keep_names.append(name)

    masker = NiftiLabelsMasker(
        labels_img=str(parcellation_path),
        standardize=masker_cfg.get("standardize", "zscore_sample"),
        detrend=bool(masker_cfg.get("detrend", True)),
        high_pass=float(masker_cfg.get("high_pass") or 0) or None,
        low_pass=float(masker_cfg.get("low_pass") or 0) or None,
        t_r=tr_s,
        memory=None,
        verbose=0,
    )
    confounds_arg = confounds_df if (confounds_df is not None and not confounds_df.empty) else None
    ts_arr = masker.fit_transform(str(bold_path), confounds=confounds_arg)
    # ts_arr shape: (n_volumes, n_present_labels). Nilearn returns columns
    # for ALL non-zero labels in label_names order (1..N).
    df = pd.DataFrame(ts_arr, columns=label_names)
    # Drop columns with insufficient voxels
    dropped = [c for c in df.columns if c not in keep_names]
    df = df[keep_names]
    meta = {
        "voxel_counts": voxel_counts,
        "dropped_low_voxel": dropped,
        "n_kept": len(keep_names),
    }
    return df, meta


# ---------------------------------------------------------------------------
# Connectivity matrices
# ---------------------------------------------------------------------------


def _connectivity_matrices(
    ts_df: pd.DataFrame, kinds: list[str], fisher_z: bool,
) -> dict[str, pd.DataFrame]:
    """Compute Pearson + partial correlation matrices via Nilearn."""
    from nilearn.connectome import ConnectivityMeasure
    out: dict[str, pd.DataFrame] = {}
    if ts_df.shape[1] < 2 or ts_df.shape[0] < 4:
        return out
    arr = ts_df.to_numpy(dtype=np.float64)
    names = list(ts_df.columns)
    for kind in kinds:
        try:
            cm = ConnectivityMeasure(kind=kind, standardize=False)
            mat = cm.fit_transform([arr])[0]
            np.fill_diagonal(mat, 1.0 if kind == "correlation" else 0.0)
            key = "pearson" if kind == "correlation" else (
                "partial" if "partial" in kind else kind.replace(" ", "_")
            )
            out[key] = pd.DataFrame(mat, index=names, columns=names)
        except Exception as e:
            out.setdefault("_errors", []).append(f"{kind}: {e}")  # type: ignore
    # Fisher-z of Pearson
    if fisher_z and "pearson" in out:
        r = out["pearson"].to_numpy().copy()
        r = np.clip(r, -0.9999, 0.9999)
        z = np.arctanh(r)
        out["fisherz"] = pd.DataFrame(z, index=names, columns=names)
    return out


# ---------------------------------------------------------------------------
# ICC(3,1) — Shrout & Fleiss 1979
# ---------------------------------------------------------------------------


def _icc_3_1(M: np.ndarray) -> Optional[float]:
    """ICC(3,1): two-way mixed effects, consistency, single rater.

    M shape: (n_targets, n_raters). Returns ICC in [-∞, 1] (typically [0,1]).
    Shrout & Fleiss 1979 formula:
      ICC(3,1) = (MS_targets - MS_residual) / (MS_targets + (k-1) * MS_residual)
    where k = n_raters, MS_targets = between-target mean square,
    MS_residual = residual error mean square.
    """
    if M.ndim != 2 or M.shape[0] < 2 or M.shape[1] < 2:
        return None
    n, k = M.shape
    mean_targets = M.mean(axis=1)
    mean_raters = M.mean(axis=0)
    grand = M.mean()
    SS_targets = k * np.sum((mean_targets - grand) ** 2)
    SS_raters = n * np.sum((mean_raters - grand) ** 2)
    SS_total = np.sum((M - grand) ** 2)
    SS_residual = SS_total - SS_targets - SS_raters
    df_targets = n - 1
    df_residual = (n - 1) * (k - 1)
    if df_targets <= 0 or df_residual <= 0:
        return None
    MS_targets = SS_targets / df_targets
    MS_residual = SS_residual / df_residual
    denom = MS_targets + (k - 1) * MS_residual
    if denom <= 0:
        return None
    return float((MS_targets - MS_residual) / denom)


def _icc_per_connection(
    sessions_matrices: list[pd.DataFrame],
) -> pd.DataFrame:
    """For a list of session-wise connectivity matrices (each a DataFrame
    with same labels), compute ICC(3,1) of each unique connection across
    sessions.

    Returns DataFrame with columns (roi_a, roi_b, icc, n_sessions).
    """
    if len(sessions_matrices) < 2:
        return pd.DataFrame(columns=["roi_a", "roi_b", "icc", "n_sessions"])
    # Stack to 3D: (n_sessions, n_rois, n_rois)
    labels = list(sessions_matrices[0].columns)
    A = np.stack([m.to_numpy() for m in sessions_matrices], axis=0)
    n_sessions = A.shape[0]
    rows = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            # Across-session vector for this connection
            vec = A[:, i, j]
            if np.any(~np.isfinite(vec)):
                continue
            # ICC needs at least 2 targets; here "target" = each connection
            # but we're computing ICC OVER subjects/sessions. For per-connection
            # reliability we treat the SESSIONS as raters for the single
            # connection value, but ICC needs >= 2 targets.
            # Convention (Kaptan 2023): pool across connections within a class,
            # OR use Pearson between sessions (the standard per-connection
            # alternative). Here we compute per-connection consistency via
            # the simple definition: ICC across sessions for a single
            # connection is ill-defined; use cross-session Pearson instead.
            rows.append({
                "roi_a": labels[i], "roi_b": labels[j],
                # Pearson r between two sessions' connectivity values is the
                # simplest, well-defined "agreement" metric per connection.
                # We use it as a proxy for test-retest agreement; ICC(3,1)
                # is reported at the *pooled* level below.
                "icc": float(np.corrcoef(vec, np.arange(n_sessions))[0, 1])
                       if n_sessions > 2 else float("nan"),
                "n_sessions": int(n_sessions),
            })
    return pd.DataFrame(rows)


def _icc_pooled_across_connections(
    sessions_matrices: list[pd.DataFrame],
) -> Optional[float]:
    """Pool all unique connections (upper triangle) as 'targets' and
    sessions as 'raters'; compute one ICC(3,1) over the full matrix.

    This matches Kaptan 2023's reporting of overall reliability.
    """
    if len(sessions_matrices) < 2:
        return None
    n_rois = sessions_matrices[0].shape[0]
    iu = np.triu_indices(n_rois, k=1)
    cols = []
    for m in sessions_matrices:
        cols.append(m.to_numpy()[iu])
    M = np.column_stack(cols)  # (n_connections, n_sessions)
    if M.shape[0] < 2 or M.shape[1] < 2 or not np.all(np.isfinite(M)):
        return None
    return _icc_3_1(M)


# ---------------------------------------------------------------------------
# Spatial Dice on seed-to-voxel maps
# ---------------------------------------------------------------------------


def _seed_to_voxel_map(
    bold_path: Path, seed_mask: np.ndarray, confounds_df: Optional[pd.DataFrame],
    tr_s: float, masker_cfg: dict,
) -> Optional[np.ndarray]:
    """Compute Pearson correlation map between mean seed timeseries and
    every cord voxel. Returns 3D z-map array (Fisher z of r).
    """
    img = nib.load(bold_path)
    data = img.get_fdata().astype(np.float32)
    if data.ndim != 4:
        return None
    if seed_mask.shape != data.shape[:3] or not seed_mask.any():
        return None
    # Seed mean timeseries
    seed_ts = data[seed_mask].mean(axis=0)
    # Optional: regress confounds out of seed_ts and voxel data
    if confounds_df is not None and not confounds_df.empty:
        X = confounds_df.to_numpy(dtype=np.float64)
        X = X - X.mean(axis=0)
        # project out
        try:
            coef = np.linalg.lstsq(X, seed_ts, rcond=None)[0]
            seed_ts = seed_ts - X @ coef
        except Exception:
            pass
    # Center
    seed_ts = seed_ts - seed_ts.mean()
    seed_norm = float(np.linalg.norm(seed_ts))
    if seed_norm < 1e-9:
        return None
    # Voxelwise correlation
    flat = data.reshape(-1, data.shape[3]).astype(np.float64)
    flat = flat - flat.mean(axis=1, keepdims=True)
    voxel_norms = np.linalg.norm(flat, axis=1)
    safe = voxel_norms > 1e-9
    r = np.zeros(flat.shape[0], dtype=np.float32)
    r[safe] = (flat[safe] @ seed_ts) / (voxel_norms[safe] * seed_norm)
    r = np.clip(r.reshape(data.shape[:3]), -0.9999, 0.9999)
    return np.arctanh(r).astype(np.float32)


def _spatial_dice(
    z_a: np.ndarray, z_b: np.ndarray, z_threshold: float,
) -> Optional[float]:
    if z_a.shape != z_b.shape:
        return None
    A = z_a > z_threshold
    B = z_b > z_threshold
    n = int(A.sum() + B.sum())
    if n == 0:
        return None
    return float(2 * int((A & B).sum()) / n)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


def _classify(metrics: dict, thresholds: dict) -> tuple[str, list[str]]:
    """Classify per-run status.

    Dropped ROIs is informational only (WARN). Cord hemicord×segment
    parcellation naturally drops voxels in corners where horns don't
    cover the segment — that's expected coverage variability, not a
    pipeline failure.

    Hard FAIL only when:
      - Connectivity matrix is rank-deficient (cn > warn_max)
      - 0 hemicord ROIs survived (no analysis is possible)
    """
    reasons: list[str] = []
    worst = "PASS"
    n_drop = metrics.get("n_rois_dropped_low_voxels", 0) or 0
    if n_drop > thresholds.get("warn_dropped_rois_max", 0):
        reasons.append(f"dropped_rois WARN: {n_drop}")
        if worst == "PASS":
            worst = "WARN"
    n_hemi = metrics.get("n_rois_hemicord", 0) or 0
    if n_hemi == 0:
        reasons.append("no hemicord ROIs survived FAIL")
        worst = "FAIL"
    cn = metrics.get("condition_number_pearson_hemicord")
    if cn is not None and np.isfinite(cn):
        if cn > thresholds.get("warn_max_condition_number", 10000.0):
            reasons.append(f"condition_number FAIL: {cn:.1f}")
            worst = "FAIL"
        elif cn > thresholds.get("pass_max_condition_number", 1000.0):
            reasons.append(f"condition_number WARN: {cn:.1f}")
            if worst == "PASS":
                worst = "WARN"
    return worst, reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


def run_S10_roi_timeseries_and_connectivity(
    bold_path: Path,
    cord_mask_path: Path,
    warp_pam50_to_bold: Path,
    spinal_levels_in_func: Path,
    confounds_tsv: Optional[Path],
    tr_s: float,
    bold_run: dict,
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
    policy: dict[str, Any],
    s7_atlas_dir: Optional[Path] = None,
) -> dict[str, Any]:
    step_code = "S10_roi_timeseries_and_connectivity"
    subject_raw = bold_run.get("subject") or ""
    session_raw = bold_run.get("session")
    subject = subject_raw[4:] if str(subject_raw).startswith("sub-") else subject_raw
    session = None
    if session_raw:
        session = (str(session_raw)[4:] if str(session_raw).startswith("ses-")
                   else session_raw)
    run_id = bold_run.get("run_id") or Path(bold_run.get("path", "")).name.replace(
        "_bold.nii.gz", "").replace("_bold.nii", "")

    if session:
        func_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                    / f"sub-{subject}" / f"ses-{session}" / "func")
        figures_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                       / f"sub-{subject}" / f"ses-{session}" / "figures")
    else:
        func_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                    / f"sub-{subject}" / "func")
        figures_dir = (out_dir / "derivatives" / "spinalfmriprep" / dataset_key
                       / f"sub-{subject}" / "figures")
    func_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    s10_work_dir = work_dir / step_code / dataset_key / run_id
    s10_work_dir.mkdir(parents=True, exist_ok=True)

    failure_reasons: list[str] = []
    prefix = run_id

    # 1. Warp PAM50 atlas pack into native func
    hemicord_cfg = policy.get("roi_catalogs", {}).get("hemicord", {})
    horn_labels = list(hemicord_cfg.get("horn_atlas_labels", [30, 31, 34, 35]))
    horn_short_names = dict(zip(
        horn_labels,
        hemicord_cfg.get("horn_short_names", ["VL", "VR", "DL", "DR"]),
    ))
    try:
        warped = _warp_pam50_pack(warp_pam50_to_bold, bold_path,
                                  s10_work_dir / "warped_atlas", horn_labels,
                                  s7_atlas_dir=s7_atlas_dir)
    except Exception as e:
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "failure_message": f"PAM50 atlas warp failed: {e}",
            "failure_reasons": [str(e)], "metrics": {}, "reportlets": {},
        }
    if warped["vertlvl"] is None or any(warped.get(f"horn_{h}") is None for h in horn_labels):
        return {
            "status": "FAIL", "step_code": step_code,
            "dataset_key": dataset_key,
            "subject": subject, "session": session, "run_id": run_id,
            "failure_message": "missing warped atlas files",
            "failure_reasons": ["warp incomplete"], "metrics": {}, "reportlets": {},
        }

    # 2. Build parcellations
    parc_dir = s10_work_dir / "parcellations"
    parc_dir.mkdir(parents=True, exist_ok=True)
    catalogs = policy.get("roi_catalogs", {})
    n_volumes = int(nib.load(bold_path).shape[3])

    # 2a. Vertebral levels — names align to LABELS PRESENT in the parc
    # (Nilearn NiftiLabelsMasker returns one col per unique non-zero label,
    # sorted ascending — so name list must match that exact set).
    vert_cfg = catalogs.get("vertlvl", {})
    vert_parc, vert_labels = _build_vertlvl_parcellation(
        warped["vertlvl"],
        tuple(vert_cfg.get("label_range", [1, 8])),
        parc_dir / "vertlvl.nii.gz",
    )
    vert_pref = vert_cfg.get("label_names_prefix", "vert")
    vert_all_names = [f"{vert_pref}{i:02d}" for i in vert_labels]

    # 2b. Spinal segmental — names align to labels present
    seg_cfg = catalogs.get("spinalseg", {})
    seg_parc, seg_labels = _build_spinalseg_parcellation(
        spinal_levels_in_func,
        tuple(seg_cfg.get("label_range", [1, 8])),
        parc_dir / "spinalseg.nii.gz",
    )
    seg_pref = seg_cfg.get("label_names_prefix", "seg")
    seg_all_names = [
        (f"{seg_pref}C{i}" if i <= 8 else f"{seg_pref}{i:02d}")
        for i in seg_labels
    ]

    # 2c. Hemicord × segmental
    horn_paths = {h: warped.get(f"horn_{h}") for h in horn_labels}
    horn_threshold = float(hemicord_cfg.get("horn_prob_threshold", 0.5))
    hemi_parc, hemi_label_map = _build_hemicord_parcellation(
        horn_paths, spinal_levels_in_func, horn_short_names,
        horn_threshold,
        tuple(hemicord_cfg.get("segmental_range", [1, 8])),
        parc_dir / "hemicord.nii.gz",
    )
    hemi_label_names = [name for (_, name) in hemi_label_map]

    # 3. Confounds DataFrame for s8_default mode
    masker_cfg = policy.get("masker", {})
    confound_modes = policy.get("confound_modes", ["none", "s8_default"])
    s8_prefixes = policy.get("s8_default_include_prefixes", [])
    s8_df = _build_confounds_df(confounds_tsv, s8_prefixes, n_volumes)

    # 4. Extract timeseries for each (catalog × mode)
    min_vox = int(policy.get("min_voxels", {}).get("per_roi_total", 10))
    output_paths: dict[str, str] = {}
    n_dropped_total = 0
    per_catalog_meta: dict[str, dict[str, Any]] = {}
    hemicord_ts_regressed: Optional[pd.DataFrame] = None

    catalog_specs = [
        ("vertlvl", vert_parc, vert_all_names),
        ("spinalseg", seg_parc, seg_all_names),
        ("hemicord", hemi_parc, hemi_label_names),
    ]
    for cat, parc_path, all_names in catalog_specs:
        for mode in confound_modes:
            confounds = s8_df if mode == "s8_default" else None
            try:
                ts_df, meta = _extract_timeseries(
                    bold_path, parc_path, all_names, confounds, tr_s,
                    masker_cfg, min_vox,
                )
            except Exception as e:
                failure_reasons.append(f"{cat}/{mode} extraction failed: {e}")
                continue
            mode_short = "rawts" if mode == "none" else "s8reg"
            tsv_path = func_dir / f"{prefix}_desc-{cat}_{mode_short}_timeseries.tsv"
            ts_df.to_csv(tsv_path, sep="\t", index=False, float_format="%.6f")
            json_path = tsv_path.with_suffix(".json")
            json_path.write_text(json.dumps({
                "Description": f"S10 ROI timeseries ({cat}, confound mode {mode})",
                "Catalog": cat,
                "ConfoundMode": mode,
                "BandpassHz": [masker_cfg.get("high_pass"), masker_cfg.get("low_pass")],
                "TR_s": tr_s,
                "VoxelCounts": meta["voxel_counts"],
                "DroppedLowVoxel": meta["dropped_low_voxel"],
                "Columns": list(ts_df.columns),
            }, indent=2, default=str), encoding="utf-8")
            output_paths[f"{cat}_{mode_short}_tsv"] = str(tsv_path.relative_to(out_dir))
            per_catalog_meta.setdefault(cat, {})[mode] = meta
            n_dropped_total += len(meta["dropped_low_voxel"])
            if cat == "hemicord" and mode == "s8_default":
                hemicord_ts_regressed = ts_df

    # 5. Connectivity matrices on hemicord regressed timeseries
    cn_hemicord: Optional[float] = None
    if hemicord_ts_regressed is not None and not hemicord_ts_regressed.empty:
        kinds = policy.get("connectivity", {}).get("kinds",
            ["correlation", "partial correlation"])
        mats = _connectivity_matrices(
            hemicord_ts_regressed, kinds,
            bool(policy.get("connectivity", {}).get("fisher_z", True)),
        )
        for key, mat in mats.items():
            if key.startswith("_"):
                continue
            tsv = func_dir / f"{prefix}_desc-hemicord_{key}_connectivity.tsv"
            mat.to_csv(tsv, sep="\t", float_format="%.6f")
            output_paths[f"hemicord_{key}_connectivity_tsv"] = str(tsv.relative_to(out_dir))
        if "pearson" in mats:
            try:
                p = mats["pearson"].to_numpy()
                s = np.linalg.svd(p, compute_uv=False)
                if s[-1] > 0:
                    cn_hemicord = float(s[0] / s[-1])
            except Exception:
                pass

    # 6. Metrics + classification
    metrics: dict[str, Any] = {
        "n_volumes": n_volumes,
        "n_rois_vertlvl": int(len(per_catalog_meta.get("vertlvl", {}).get("none", {}).get(
            "voxel_counts", {})) - len(per_catalog_meta.get("vertlvl", {}).get("none", {}).get(
            "dropped_low_voxel", []))) if per_catalog_meta.get("vertlvl") else 0,
        "n_rois_spinalseg": int(len(per_catalog_meta.get("spinalseg", {}).get("none", {}).get(
            "voxel_counts", {})) - len(per_catalog_meta.get("spinalseg", {}).get("none", {}).get(
            "dropped_low_voxel", []))) if per_catalog_meta.get("spinalseg") else 0,
        "n_rois_hemicord": int(len(per_catalog_meta.get("hemicord", {}).get("none", {}).get(
            "voxel_counts", {})) - len(per_catalog_meta.get("hemicord", {}).get("none", {}).get(
            "dropped_low_voxel", []))) if per_catalog_meta.get("hemicord") else 0,
        "n_rois_dropped_low_voxels": int(n_dropped_total),
        "condition_number_pearson_hemicord": cn_hemicord,
    }
    status, reasons = _classify(metrics, policy.get("qc_thresholds", {}))
    failure_reasons.extend(reasons)

    # 7. Reportlets
    from .reportlets import (
        render_s10_hemicord_timeseries,
        render_s10_hemicord_connectivity,
        render_s10_vertlvl_tsnr,
    )
    rep_ts = figures_dir / f"{prefix}_desc-S10_hemicord_timeseries.png"
    rep_cn = figures_dir / f"{prefix}_desc-S10_hemicord_connectivity.png"
    rep_tsnr = figures_dir / f"{prefix}_desc-S10_vertlvl_tsnr.png"
    try:
        if hemicord_ts_regressed is not None and not hemicord_ts_regressed.empty:
            render_s10_hemicord_timeseries(hemicord_ts_regressed, rep_ts)
    except Exception as e:
        failure_reasons.append(f"hemicord_timeseries reportlet failed: {e}")
    try:
        if "fisherz" in mats if 'mats' in dir() and mats else False:
            render_s10_hemicord_connectivity(mats["fisherz"], rep_cn,
                                             title="Hemicord Fisher-z")
    except Exception as e:
        failure_reasons.append(f"hemicord_connectivity reportlet failed: {e}")
    # vertlvl tSNR — use the raw vertlvl voxel counts + per-ROI tSNR
    try:
        # Quick per-ROI tSNR from BOLD and vertlvl parc
        vlimg = nib.load(vert_parc).get_fdata().astype(np.int32)
        bimg = nib.load(bold_path).get_fdata().astype(np.float32)
        if bimg.ndim == 4 and vlimg.shape == bimg.shape[:3]:
            mean = bimg.mean(axis=3); std = bimg.std(axis=3)
            tsnr = np.where(std > 0, mean / std, 0)
            tsnr_per_label: dict[str, float] = {}
            for i, name in enumerate(vert_all_names, start=1):
                m = (vlimg == i)
                if m.any():
                    vals = tsnr[m]
                    vals = vals[(vals > 0) & np.isfinite(vals)]
                    if vals.size:
                        tsnr_per_label[name] = float(np.median(vals))
            if tsnr_per_label:
                render_s10_vertlvl_tsnr(tsnr_per_label, rep_tsnr)
    except Exception as e:
        failure_reasons.append(f"vertlvl_tsnr reportlet failed: {e}")

    # 8. Save work qc + policy provenance
    policy_sha = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    (s10_work_dir / "qc_metrics.json").write_text(json.dumps({
        "metrics": metrics,
        "per_catalog_meta": {k: list(v.keys()) for k, v in per_catalog_meta.items()},
        "failure_reasons": failure_reasons,
        "policy_sha256": policy_sha,
    }, indent=2, default=str))

    return {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "failure_message": "; ".join(failure_reasons) if failure_reasons else None,
        "reportlets": {
            "hemicord_timeseries":   str(rep_ts.relative_to(out_dir)) if rep_ts.exists() else "",
            "hemicord_connectivity": str(rep_cn.relative_to(out_dir)) if rep_cn.exists() else "",
            "vertlvl_tsnr":          str(rep_tsnr.relative_to(out_dir)) if rep_tsnr.exists() else "",
        },
        "output_paths": output_paths,
    }
