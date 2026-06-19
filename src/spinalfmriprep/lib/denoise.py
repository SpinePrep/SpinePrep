"""MP-PCA thermal-noise denoising of 4D BOLD via MRtrix3 ``dwidenoise``.

Marchenko-Pastur PCA (Veraart 2016, MRM; Cordero-Grande 2019) removes thermal
(random-matrix) noise by hard-thresholding the noise-only singular values of a
local voxel x time patch. ``dwidenoise`` is the reference implementation; the
algorithm is contrast-agnostic so it applies to a 4D BOLD series.

CRITICAL — placement: this MUST run on the rawest possible per-run 4D BOLD,
before ANY interpolation (motion/distortion correction, smoothing, resampling).
Interpolation correlates ("colours") the noise and violates the i.i.d.
Marchenko-Pastur assumption (MRtrix docs treat this as a failure condition).
In this pipeline it runs as the first S3 operation, before localize/crop/S4-moco
-- matching the only spinal-cord-fMRI precedent (Kaptan/Eippert 2023, NeuroImage:
MP-PCA on the whole 4D cord series before moco, ~140% GM tSNR gain).

Honest caveats (see policy comments): magnitude data is Rician (dwidenoise does
NOT correct the non-Gaussian floor -- a tolerated high-SNR approximation);
low-rank denoising can cause activation "spreading"; and patch mixing of
cord/CSF/tissue in the thin cord is unstudied for fMRI. Hence: optional, off by
default.

Patch size: left to dwidenoise's auto rule (smallest isotropic patch exceeding
the volume count -- 5^3 for <=125 vols, 7^3 for <=343), which is the recommended
voxels >= volumes regime. Override only via policy ``extent``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spinalfmriprep.lib.run import run_command as _run_command


def _dwidenoise_version() -> Optional[str]:
    ok, out = _run_command(["dwidenoise", "-version"])
    if not ok:
        return None
    return out.splitlines()[0].strip() if out else "unknown"


def _tissue_median_tsnr(bold_path: Path) -> Optional[float]:
    """Median temporal SNR (mean/std over time) in a coarse tissue mask
    (temporal-mean above the 60th percentile of nonzero voxels). Cheap, mask-
    free QC proxy for the cord tSNR gain; the in-cord value is reported later
    once S3.1 has the cord mask."""
    img = nib.load(bold_path)
    data = img.get_fdata(dtype=np.float32)
    if data.ndim != 4 or data.shape[3] < 3:
        return None
    m = data.mean(axis=3)
    s = data.std(axis=3)
    nz = m[m > 0]
    if nz.size == 0:
        return None
    thr = float(np.percentile(nz, 60))
    tissue = m > thr
    tsnr = np.where(s > 0, m / s, 0.0)
    vals = tsnr[tissue & (s > 0) & np.isfinite(tsnr)]
    return float(np.median(vals)) if vals.size else None


def mppca_denoise(
    bold_path: Path, out_path: Path, work_dir: Path, cfg: dict[str, Any],
) -> tuple[bool, Optional[Path], dict[str, Any]]:
    """Denoise a 4D BOLD with dwidenoise. Returns (ok, noise_map_path, meta).

    meta carries provenance (tool, version, extent) + the step-local truth
    metric (tissue median tSNR before/after and % gain). On any failure returns
    ok=False with an explanatory meta['error']; the caller falls back to the raw
    BOLD so denoising can never silently corrupt the chain.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    noise_map = work_dir / "denoise_noise_map.nii.gz"
    meta: dict[str, Any] = {"tool": "dwidenoise", "enabled": True}

    cmd = ["dwidenoise", str(bold_path), str(out_path),
           "-noise", str(noise_map), "-force"]
    extent = cfg.get("extent")
    if extent:  # e.g. "5,5,5"; default (None) lets dwidenoise auto-size
        cmd += ["-extent", str(extent)]
        meta["extent"] = str(extent)
    else:
        meta["extent"] = "auto"

    tsnr_pre = _tissue_median_tsnr(bold_path)
    ok, out = _run_command(cmd)
    if not ok or not out_path.exists():
        meta["error"] = (out or "dwidenoise produced no output")[:300]
        return False, None, meta

    meta["version"] = _dwidenoise_version()
    tsnr_post = _tissue_median_tsnr(out_path)
    meta["tsnr_pre"] = tsnr_pre
    meta["tsnr_post"] = tsnr_post
    if tsnr_pre and tsnr_post and tsnr_pre > 0:
        meta["tsnr_gain_pct"] = round(100.0 * (tsnr_post - tsnr_pre) / tsnr_pre, 1)
    try:
        nz = nib.load(noise_map).get_fdata()
        nz = nz[nz > 0]
        meta["noise_median"] = float(np.median(nz)) if nz.size else None
    except Exception:
        meta["noise_median"] = None
    return True, noise_map, meta
