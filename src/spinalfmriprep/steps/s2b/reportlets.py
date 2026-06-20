"""S2B MP-PCA denoise QC reportlets.

Three figures, designed so one glance answers "did denoising help, and did it
stay honest" (CLAUDE.md dev principle #4):

  1. noise_sigma   — the dwidenoise noise (sigma) map: where/how much thermal
                     noise was estimated. Flat, anatomy-free is expected.
  2. tsnr_ba       — temporal-SNR before vs after, same slices + colorbar, with
                     the median-gain number. The benefit, visualized.
  3. residual      — temporal SD of REMOVED signal (raw - denoised). THE key
                     check: it must look like structureless noise. If cord/CSF
                     anatomy or edges show through, denoising ate signal
                     (over-denoising) -- a FAIL the human can see immediately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_BG = "#0d1117"
_FG = "#e6edf3"


def _mid_slices(nz: int, n: int = 7) -> list[int]:
    if nz <= n:
        return list(range(nz))
    lo, hi = int(nz * 0.2), int(nz * 0.8)
    return [int(round(x)) for x in np.linspace(lo, hi, n)]


def _tsnr(data4d: np.ndarray) -> np.ndarray:
    m = data4d.mean(axis=3)
    s = data4d.std(axis=3)
    return np.where(s > 0, m / s, 0.0)


def _montage(ax, vol3d, slices, cmap, vmax=None, title=""):
    tiles = [np.rot90(vol3d[:, :, z]) for z in slices]
    strip = np.concatenate(tiles, axis=1)
    vmax = vmax if vmax is not None else (np.percentile(strip[strip > 0], 99)
                                          if (strip > 0).any() else 1.0)
    ax.imshow(strip, cmap=cmap, vmin=0, vmax=vmax)
    ax.set_title(title, color=_FG, fontsize=10, loc="left")
    ax.axis("off")
    return vmax


def render_denoise_reportlets(
    raw_path: Path, denoised_path: Path, noise_path: Optional[Path],
    out_dir: Path, prefix: str, status: str = "PASS",
    tsnr_gain_pct: Optional[float] = None,
) -> dict[str, Path]:
    """Render the 3 QC figures. Returns {name: png_path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = nib.load(str(raw_path)).get_fdata(dtype=np.float32)
    den = nib.load(str(denoised_path)).get_fdata(dtype=np.float32)
    if raw.ndim != 4 or raw.shape != den.shape:
        return {}
    nz = raw.shape[2]
    slices = _mid_slices(nz)
    out: dict[str, Path] = {}

    # 1. noise sigma map
    if noise_path and Path(noise_path).exists():
        sig = nib.load(str(noise_path)).get_fdata(dtype=np.float32)
        if sig.ndim == 4:
            sig = sig[..., 0]
        fig, ax = plt.subplots(figsize=(11, 2.4), facecolor=_BG)
        _montage(ax, sig, slices, "magma",
                 title=f"S2B noise σ map  [{status}]")
        fig.tight_layout()
        p = out_dir / f"{prefix}_desc-S2B_noise_sigma.png"
        fig.savefig(p, facecolor=_BG, dpi=110); plt.close(fig)
        out["noise_sigma"] = p

    # 2. tSNR before vs after
    tb, td = _tsnr(raw), _tsnr(den)
    fig, axes = plt.subplots(2, 1, figsize=(11, 4.6), facecolor=_BG)
    vmax = max(np.percentile(tb[tb > 0], 99) if (tb > 0).any() else 1.0,
               np.percentile(td[td > 0], 99) if (td > 0).any() else 1.0)
    _montage(axes[0], tb, slices, "viridis", vmax=vmax, title="tSNR — raw")
    gtxt = f"  (median gain {tsnr_gain_pct:+.0f}%)" if tsnr_gain_pct is not None else ""
    _montage(axes[1], td, slices, "viridis", vmax=vmax,
             title=f"tSNR — denoised{gtxt}")
    fig.tight_layout()
    p = out_dir / f"{prefix}_desc-S2B_tsnr_before_after.png"
    fig.savefig(p, facecolor=_BG, dpi=110); plt.close(fig)
    out["tsnr_before_after"] = p

    # 3. residual structure check (removed = raw - denoised, temporal SD)
    removed_sd = (raw - den).std(axis=3)
    fig, ax = plt.subplots(figsize=(11, 2.4), facecolor=_BG)
    _montage(ax, removed_sd, slices, "inferno",
             title="S2B removed-noise SD (must be structureless — anatomy here = over-denoising)")
    fig.tight_layout()
    p = out_dir / f"{prefix}_desc-S2B_residual_structure.png"
    fig.savefig(p, facecolor=_BG, dpi=110); plt.close(fig)
    out["residual_structure"] = p

    return out
