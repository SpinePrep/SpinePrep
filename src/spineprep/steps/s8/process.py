"""S8: per-run confound + physio regressor extraction.

Spec: .claude/specs/s8-confounds-and-physio-regressors.md

Five families assembled into a BIDS-Derivatives confounds TSV + JSON sidecar:
  1. Motion           — trans_x/y + derivatives + FD (S4 bulk+slicewise moco)
  2. Outliers         — FD>0.5 (Power 2014) OR DVARS/refRMS Tukey Q3+1.5·IQR
                        (S3 frame_metrics) → one-hot
  3. CSF aCompCor     — 5 PCs/slice via FSL fslmeants --eig on per-voxel
                        detrended BOLD (Behzadi 2007 / CoSpi spi12)
  4. RETROICOR        — slicewise via FSL PNM (32 regressors × slices)
  5. Cosine basis     — DCT high-pass equivalent (optional; cosine.enabled)
  6. SpinalCompCor    — optional (spinalcompcor.enabled); 18 mm noise ROI

Native func space throughout. No BOLD resampling. No regression.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import pandas as pd

from spineprep.lib.run import run_command as _run_command


# ---------------------------------------------------------------------------
# 1. Motion family
# ---------------------------------------------------------------------------


def _extract_motion(
    moco_x_4d_path: Path, moco_y_4d_path: Path, n_volumes_expected: int,
) -> dict[str, np.ndarray]:
    """trans_x/y = Stage-1 bulk + mean-over-z of Stage-2 slicewise moco; FD = |Δx|+|Δy|.

    SCT writes the per-volume slicewise params as 4D NIfTI with shape
    (1, 1, n_slices, n_volumes). Mean across slices yields the scalar
    in-plane slicewise translation per volume; the Stage-1 coarse bulk XY
    (co-located moco_params_coarse.tsv) is added on top so the confound
    motion + FD reflect total (bulk + slicewise) motion, consistent with
    S4's FD (BUG-1b).

    **Cord-2D motion variant** (not full Friston 1996 24P). S4's cord
    moco is 2D slicewise — no Z translation and no rotations are
    estimated. We emit 4 motion columns (trans_x, trans_y, plus
    derivative1 of each) + FD = |Δtrans_x| + |Δtrans_y|. This matches
    Mohammed 2020 cord moco conventions and Kaptan 2023's reported
    4-6 motion params; full 24P with squares and squared-derivatives
    is deliberately not emitted because it would overfit on the
    cord's small ROI (~100 voxels per slice). See audit-v2 Findings
    1-2-5 in .claude/specs/s8-algorithm-audit.md.
    """
    mx = nib.load(moco_x_4d_path).get_fdata()
    my = nib.load(moco_y_4d_path).get_fdata()
    if mx.ndim != 4 or my.ndim != 4:
        raise ValueError(f"moco params not 4D: {mx.shape}, {my.shape}")
    tx = mx.mean(axis=(0, 1, 2)).astype(np.float64)  # (n_volumes,) slicewise
    ty = my.mean(axis=(0, 1, 2)).astype(np.float64)
    # Add Stage-1 coarse bulk XY so motion/FD = bulk + slicewise, matching
    # S4's FD. The coarse TSV is co-located with the slicewise NIfTIs; absent
    # on 2d-only runs, in which case motion stays slicewise-only. (BUG-1b)
    coarse_tsv = Path(moco_x_4d_path).parent / "moco_params_coarse.tsv"
    if coarse_tsv.exists():
        c = pd.read_csv(coarse_tsv, sep="\t")
        if len(c) == tx.size and {"tx_coarse", "ty_coarse"} <= set(c.columns):
            tx = tx + c["tx_coarse"].to_numpy(dtype=np.float64)
            ty = ty + c["ty_coarse"].to_numpy(dtype=np.float64)
    if tx.size != n_volumes_expected:
        raise ValueError(
            f"moco length {tx.size} != BOLD volumes {n_volumes_expected}"
        )
    dtx = np.diff(tx, prepend=tx[0])
    dty = np.diff(ty, prepend=ty[0])
    fd = np.abs(dtx) + np.abs(dty)
    return {
        "trans_x": tx, "trans_y": ty,
        "trans_x_derivative1": dtx, "trans_y_derivative1": dty,
        "framewise_displacement": fd,
    }


# ---------------------------------------------------------------------------
# 2. Outliers — DVARS + refRMS via S3.2 frame_metrics
# ---------------------------------------------------------------------------


def _load_frame_metrics(frame_metrics_tsv: Path) -> pd.DataFrame:
    df = pd.read_csv(frame_metrics_tsv, sep="\t")
    return df


def _tukey_outlier_mask(x: np.ndarray, k: float = 1.5) -> np.ndarray:
    """Tukey upper-fence outlier flag: values above Q3 + k·IQR.

    Non-parametric; works on heavy-tailed cord-fMRI distributions
    where the μ + nσ Gaussian rule over-flags. Matches fMRIPrep's
    `motion_outlier_NN` convention and S3.2's own outlier rule.
    """
    q1, q3 = np.percentile(x, [25, 75])
    return x > (q3 + k * (q3 - q1))


def _build_outlier_columns(
    frame_metrics: pd.DataFrame, fd: np.ndarray,
    fd_thresh: float,
    dvars_iqr_k: float = 1.5, refrms_iqr_k: float = 1.5,
) -> tuple[dict[str, np.ndarray], int]:
    """One-hot spike columns where FD > thresh OR DVARS Tukey OR refRMS Tukey.

    Field-standard convention (fMRIPrep `motion_outlier_NN`):
      FD > 0.5 mm  (Power 2014 / Kaptan 2023 / Dabbagh 2024 cord)
      DVARS > Q3 + 1.5·IQR  (Tukey; matches S3.2's own outlier rule)
      refRMS > Q3 + 1.5·IQR (same)

    Audit references: .claude/specs/s8-outlier-rate-root-cause.md
    + .claude/specs/s8-algorithm-audit.md.

    We do NOT OR-merge S3.2's `frame_metrics["outlier"]` column anymore
    — S3.2 used Tukey on the same DVARS/refRMS for funcref-selection,
    and we recompute Tukey here for the spike regressors. Merging
    layered detectors caused duplicated/inflated flag counts.
    """
    n = len(frame_metrics)
    dvars = frame_metrics["dvars"].to_numpy(dtype=np.float64)
    refrms = frame_metrics["ref_rms"].to_numpy(dtype=np.float64)
    flag = np.zeros(n, dtype=bool)
    flag |= (fd[:n] > fd_thresh)
    flag |= _tukey_outlier_mask(dvars, k=dvars_iqr_k)
    flag |= _tukey_outlier_mask(refrms, k=refrms_iqr_k)
    cols: dict[str, np.ndarray] = {}
    idx_outliers = np.where(flag)[0]
    for i, t in enumerate(idx_outliers):
        spike = np.zeros(n, dtype=np.float32)
        spike[t] = 1.0
        cols[f"motion_outlier_{i:02d}"] = spike
    cols["dvars"] = dvars.astype(np.float32)
    cols["ref_rms"] = refrms.astype(np.float32)
    return cols, int(flag.sum())


# ---------------------------------------------------------------------------
# 3. CSF slicewise — top-20%-variance mean per slice
# ---------------------------------------------------------------------------


def _erode_mask_voxels(mask: np.ndarray, n: int = 1) -> np.ndarray:
    if n <= 0:
        return mask
    from scipy.ndimage import binary_erosion
    return binary_erosion(mask, iterations=n)


def _csf_acompcor_slicewise(
    bold_path: Path, csf_mask_path: Path, work_dir: Path,
    n_components: int = 5,
    erode_voxels: int = 0,
    min_voxels_per_slice: int = 5,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Per-slice CSF aCompCor: the top-``n_components`` principal components
    (eigenvariates) of the CSF ROI in each Z slice.

    Tools agreed with Gergely + Jan Valošek in Slack (replacing the Matlab SPM
    PhysIO toolbox, which is hard to embed): **FSL `fslmeants --eig --order N`**
    computes the eigenvariates (= PCs), and the BOLD is first per-voxel
    constant+linear detrended in numpy to match PhysIO's pre-PCA step. Validated
    against PhysIO in ``research/physio_vs_fslmeants_acompcor`` (matches CoSpi
    ``spi12_acompcor.m``, which uses 5 PCs/slice). Emits up to ``n_components``
    columns per slice: ``csf_slice{z}_pc{k}``.
    """
    bimg = nib.load(bold_path)
    bold = bimg.get_fdata()
    if bold.ndim != 4:
        raise ValueError(f"BOLD not 4D: {bold.shape}")
    nx, ny, nz, nt = bold.shape
    csf = (nib.load(csf_mask_path).get_fdata() > 0.5)
    if csf.shape[:3] != bold.shape[:3]:
        raise ValueError(f"CSF mask shape {csf.shape} != BOLD {bold.shape[:3]}")
    csf_eroded = _erode_mask_voxels(csf, erode_voxels)

    # Per-voxel constant + linear detrend (matches PhysIO; detrend_lstsq.py).
    t = np.arange(nt)
    dm = np.column_stack([np.ones(nt), t - t.mean()])
    flat = bold.reshape(-1, nt).astype(np.float64)
    beta = np.linalg.lstsq(dm, flat.T, rcond=None)[0]
    resid = (flat - (dm @ beta).T).reshape(nx, ny, nz, nt).astype(np.float32)
    acdir = work_dir / "csf_acompcor"
    acdir.mkdir(parents=True, exist_ok=True)
    det_path = acdir / "bold_detrended.nii.gz"
    nib.save(nib.Nifti1Image(resid, bimg.affine, bimg.header), det_path)

    cols: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {
        "method": "fslmeants_eig_acompcor", "n_components_requested": n_components,
        "n_slices_total": nz, "n_slices_with_csf": 0,
        "pcs_per_slice": [], "slice_voxel_counts": [], "skipped_slices": [],
    }
    for z in range(nz):
        m = csf_eroded[:, :, z]
        nv = int(m.sum())
        meta["slice_voxel_counts"].append(nv)
        if nv < min_voxels_per_slice:
            meta["skipped_slices"].append(z)
            continue
        # max retrievable PCs is bounded by voxels-1 and timepoints-1
        k = min(n_components, nv - 1, nt - 1)
        if k < 1:
            meta["skipped_slices"].append(z)
            continue
        sm = np.zeros((nx, ny, nz), dtype=np.uint8)
        sm[:, :, z] = m.astype(np.uint8)
        sm_path = acdir / f"csf_slice{z:02d}_mask.nii.gz"
        nib.save(nib.Nifti1Image(sm, bimg.affine, bimg.header), sm_path)
        out_txt = acdir / f"csf_slice{z:02d}_eig.txt"
        cmd = ["fslmeants", "-i", str(det_path), "--eig", f"--order={k}",
               "-m", str(sm_path), "-o", str(out_txt)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not out_txt.exists():
            meta["skipped_slices"].append(z)
            continue
        arr = np.loadtxt(str(out_txt))
        if arr.ndim == 1:
            arr = arr[:, None]
        for j in range(arr.shape[1]):
            cols[f"csf_slice{z:02d}_pc{j + 1:02d}"] = arr[:, j].astype(np.float32)
        meta["pcs_per_slice"].append(int(arr.shape[1]))
        meta["n_slices_with_csf"] += 1
    return cols, meta


# ---------------------------------------------------------------------------
# 4. RETROICOR via FSL PNM
# ---------------------------------------------------------------------------


_CARDIAC_ALIASES = {"cardiac", "pulse", "puls", "ecg", "ppg", "pulseox"}
_RESPIRATORY_ALIASES = {"respiratory", "resp", "breath", "breathing"}


def _normalize_physio_channel(col: str) -> Optional[str]:
    cl = col.lower().strip()
    if cl in _CARDIAC_ALIASES:
        return "cardiac"
    if cl in _RESPIRATORY_ALIASES:
        return "respiratory"
    if cl == "trigger":
        return "trigger"
    return None


_SIEMENS_PMU_FOOTER_KEYS = (
    "LogStartMDHTime", "LogStopMDHTime", "LogStartMPCUTime", "LogStopMPCUTime",
    "ECG", "PULS", "RESP", "EXT", "Freq", "Per", "Min", "Max", "Avg", "StdDiff",
)


def _parse_siemens_pmu(content: str) -> tuple[np.ndarray, np.ndarray]:
    """Parse Siemens PMU log format (space-separated single-line stream with
    inline trigger markers 5000/5001 and text-block markers 5002…6002).

    Stops parsing at the trailing measurement-statistics footer (recognised
    by tokens like `LogStartMDHTime`, `PULS`, `Freq`, etc.). This avoids
    capturing the file-end timestamps (~10^7 ms) as physio values.

    Returns (values, trigger). OpenNeuro often ships physio in this format
    despite the BIDS .tsv.gz extension (e.g., ds005883, ds005884).
    """
    tokens = content.split()
    values: list[int] = []
    triggers: list[int] = []
    # Siemens trigger markers 5000/5001 are instantaneous: they mark the
    # *next* physio sample as the trigger event (FSL PNM expects a sparse
    # pulse train, not a sustained level). One-shot per marker.
    next_trigger = 0
    in_text_block = False
    for tok in tokens:
        # Hard stop at footer marker (data is done, only stats remain)
        if tok in _SIEMENS_PMU_FOOTER_KEYS:
            break
        if tok == "5002":
            in_text_block = True
            continue
        if tok == "6002":
            in_text_block = False
            continue
        if in_text_block:
            continue
        try:
            v = int(tok)
        except ValueError:
            continue
        if v == 5000 or v == 5003:  # 5003 seen in some PMU variants
            next_trigger = 1
            continue
        if v == 5001:
            # End-of-trigger marker; no immediate sample tag
            continue
        # Sanity range: Siemens PMU ADC is 12-bit (0–4095). Tokens > 10000
        # are footer timestamps even when the footer keyword check missed.
        if v < 0 or v > 10000:
            continue
        values.append(v)
        triggers.append(next_trigger)
        next_trigger = 0
    return np.asarray(values, dtype=np.float64), np.asarray(triggers, dtype=np.float64)


def _load_bids_physio(
    physio_pairs: list[tuple[Path, Path]],
) -> Optional[dict[str, Any]]:
    """Decode BIDS physio. Accepts:
      - BIDS columnar TSV.GZ (tab-separated, one row per sample, no header), or
      - multiple `_recording-<label>_physio.tsv.gz` pairs (BIDS multi-recording), or
      - Siemens PMU raw log format (space-separated single line with embedded
        trigger markers) — common in OpenNeuro spinal-cord uploads.

    Returns dict with `cardiac`, `respiratory`, `trigger`,
    `sampling_frequency_hz`, `start_time_s`. None on unreadable input.
    """
    if not physio_pairs:
        return None
    fs_seen: Optional[float] = None
    start_seen: Optional[float] = None
    out: dict[str, Any] = {}
    for tsv_gz, js in physio_pairs:
        try:
            meta = json.loads(js.read_text())
            cols = meta["Columns"]
            fs = float(meta["SamplingFrequency"])
            start = float(meta.get("StartTime", 0.0))
        except Exception:
            return None
        # Try BIDS columnar first; fall back to Siemens PMU
        arr: Optional[np.ndarray] = None
        try:
            with gzip.open(tsv_gz, "rt") as f:
                arr = np.loadtxt(f, delimiter="\t")
        except Exception:
            arr = None
        if arr is None:
            # Siemens PMU fallback (single-line space-separated with markers)
            try:
                with gzip.open(tsv_gz, "rt") as f:
                    content = f.read()
                values, triggers = _parse_siemens_pmu(content)
                if values.size == 0:
                    return None
                # Siemens stream is ONE channel + trigger; the JSON "Columns"
                # tells us which channel via the recording-<label> filename.
                # We synthesize a 2-column array consistent with BIDS spec.
                arr = np.column_stack([values, triggers])
                # Override cols to match what we actually built
                cols = ["data", "trigger"]
            except Exception:
                return None
        if arr.ndim == 1:
            arr = arr[:, None]
        # Determine target channel from filename when columns are ambiguous
        # (e.g., Siemens fallback used generic "data" name).
        recording_hint = None
        for token in tsv_gz.name.split("_"):
            if token.startswith("recording-"):
                label = token.split("-", 1)[1]
                recording_hint = _normalize_physio_channel(label)
                break
        if fs_seen is None:
            fs_seen = fs; start_seen = start
        # Resolve channels
        for i, c in enumerate(cols):
            if i >= arr.shape[1]:
                continue
            ch = _normalize_physio_channel(c)
            if ch is None and c == "data" and recording_hint is not None:
                ch = recording_hint
            if ch is None:
                continue
            if ch not in out or out[ch].size == 0:
                out[ch] = arr[:, i]
    if not out:
        return None
    out["sampling_frequency_hz"] = fs_seen
    out["start_time_s"] = start_seen or 0.0
    return out


def _physio_to_pnm_input(
    physio: dict[str, Any], work_dir: Path,
    tr_s: Optional[float] = None, n_volumes: Optional[int] = None,
) -> tuple[Optional[Path], dict[str, Any]]:
    """Write a 2-column PNM-readable physio text file (cardiac, respiratory).

    We drop the trigger column because Siemens-PMU 5000/5003 markers
    are gradient/RF events, not volume triggers — popp's trigger-timing
    validator rejects them ("Time per trigger / TR ≈ 0.3"). Instead we
    crop the physio to the BOLD-acquisition window using the first
    trigger as the BOLD start (typical Siemens cardiac/respiratory log
    starts before scan; first trigger ≈ first volume).

    Returns (path, info) where info has the cropping provenance.
    """
    info: dict[str, Any] = {"trigger_used_for_crop": False, "crop_samples": None}
    fs = float(physio.get("sampling_frequency_hz", 0)) or 1.0
    cardiac = np.asarray(physio.get("cardiac", np.array([])), dtype=np.float64)
    respiratory = np.asarray(physio.get("respiratory", np.array([])), dtype=np.float64)
    trigger = np.asarray(physio.get("trigger", np.array([])), dtype=np.float64)
    if cardiac.size == 0 and respiratory.size == 0:
        return None, info
    L = min(cardiac.size if cardiac.size else respiratory.size,
            respiratory.size if respiratory.size else cardiac.size)
    if L == 0:
        L = max(cardiac.size, respiratory.size)
    if cardiac.size < L: cardiac = np.zeros(L)
    if respiratory.size < L: respiratory = np.zeros(L)
    # Crop to BOLD window using first trigger
    start = 0
    if trigger.size and trigger.sum() > 0:
        trig_idx = np.where(trigger[:L] > 0.5)[0]
        if trig_idx.size:
            start = int(trig_idx[0])
            info["trigger_used_for_crop"] = True
    bold_window = None
    if tr_s and n_volumes:
        bold_window = int(round(tr_s * n_volumes * fs))
    end = L if bold_window is None else min(L, start + bold_window)
    info["crop_samples"] = [int(start), int(end)]
    cardiac = cardiac[start:end]
    respiratory = respiratory[start:end]
    out = work_dir / "physio_pnm.txt"
    np.savetxt(out, np.column_stack([cardiac, respiratory]), fmt="%.6f")
    return out, info


def _write_pnm_slicetiming(slice_timing_s: list[float], dest: Path) -> None:
    """One-line space-separated slicetiming text file (seconds)."""
    dest.write_text(" ".join(f"{t:.6f}" for t in slice_timing_s) + "\n")


def _run_pnm(
    bold_path: Path,
    physio_pnm_path: Path,
    slicetiming_path: Path,
    tr_s: float,
    sampling_rate_hz: float,
    cardiac_order: int,
    respiratory_order: int,
    interaction_order: int,
    work_dir: Path,
) -> tuple[bool, Optional[str], Optional[dict]]:
    """Invoke FSL popp (peak detection) + pnm_evs (EV generation).

    popp args use `--key=value` syntax (not space-separated). The physio
    text file has 2 columns: cardiac (col 1), respiratory (col 2). The
    trigger column is dropped at the converter stage; physio is cropped
    so sample 0 = first BOLD volume.
    """
    pnm_dir = work_dir / "pnm"
    pnm_dir.mkdir(parents=True, exist_ok=True)
    popp_out = pnm_dir / "popp"
    cmd_popp = [
        "popp", "-i", str(physio_pnm_path), "-o", str(popp_out),
        f"--samplingrate={sampling_rate_hz}",
        f"--tr={tr_s}",
        "--smoothcard=0.1",
        "--smoothresp=0.1",
        "--cardiac=1", "--resp=2",
        "--rvt",          # respiratory volume per time (slow)
        "--heartrate",    # heart rate (slow)
    ]
    ok, stderr = _run_command(cmd_popp)
    # popp may emit non-zero on trigger validation but still produce
    # cardiac+respiratory peak files. Accept if those exist.
    card_file = popp_out.with_suffix(".card") if popp_out.with_suffix(".card").exists() \
                else pnm_dir / "popp_card.txt"
    resp_file = popp_out.with_suffix(".resp") if popp_out.with_suffix(".resp").exists() \
                else pnm_dir / "popp_resp.txt"
    if not card_file.exists() or not resp_file.exists():
        return False, f"popp failed: {stderr or 'no stderr'}", None
    # HR + RVT outputs (popp writes <prefix>.hr and <prefix>.rvt when flags passed)
    hr_file = popp_out.with_suffix(".hr")
    rvt_file = popp_out.with_suffix(".rvt")
    # pnm_evs: generate the slicewise EVs as voxelwise NIfTI files
    evs_prefix = pnm_dir / "ev"
    # Defensive: clear any stale EV artifacts before regenerating. The reg chain
    # symlinks each step's work/ to S1's shared tree, so a prior run's ev*.nii.gz
    # and ev_evlist.txt linger; the evlist-reuse below (`if not evlist.exists()`)
    # would then return the OLD EV count (e.g. 80) instead of the freshly
    # generated set, defeating any recipe change. Removing them makes reruns
    # deterministic. (BUG-1d)
    for _stale in list(pnm_dir.glob("ev*.nii.gz")) + list(pnm_dir.glob("ev*evlist*.txt")):
        _stale.unlink(missing_ok=True)
    # interaction_order is the FSL pnm_evs multiplicative order (--multc/--multr).
    # pnm_evs EV count = 2*oc + 2*or + 4*multc*multr (verified empirically + in
    # FSL pnm_evs.cc). order 2 -> 4*2*2 = 16 interaction EVs -> 8+8+16 = 32 total
    # (Kaptan 2023 / Dabbagh 2024 cord recipe). order 0 drops interactions (16
    # total) for short runs. The previous `sqrt(interaction_order)` mapping turned
    # 16 into multc=multr=4 -> 64 interaction -> 80 total (BUG-2).
    mult = max(0, int(interaction_order))
    cmd_evs = [
        "pnm_evs", "-i", str(bold_path), "-o", str(evs_prefix),
        "-r", str(resp_file), "-c", str(card_file),
        f"--tr={tr_s}",
        f"--oc={cardiac_order}",
        f"--or={respiratory_order}",
        f"--multc={mult}",
        f"--multr={mult}",
        "--slicedir=z",
        "--sliceorder=up",
        f"--slicetiming={slicetiming_path}",
    ]
    ok, stderr = _run_command(cmd_evs)
    if not ok:
        return False, f"pnm_evs failed: {stderr or 'no stderr'}", None
    evlist = pnm_dir / "ev_evlist.txt"
    if not evlist.exists():
        cands = sorted(pnm_dir.glob("ev*evlist*.txt"))
        if cands:
            evlist = cands[0]
        else:
            # Fall back: enumerate ev*.nii.gz directly
            ev_files = sorted(pnm_dir.glob("ev*.nii.gz"))
            if not ev_files:
                return False, "no PNM EV files produced", None
            evlist = pnm_dir / "ev_evlist.txt"
            evlist.write_text("\n".join(str(p) for p in ev_files) + "\n")
    return True, None, {
        "evlist": evlist,
        "hr_file": hr_file if hr_file.exists() else None,
        "rvt_file": rvt_file if rvt_file.exists() else None,
    }


def _read_popp_slow_regressor(
    txt_path: Path, sampling_rate_hz: float, tr_s: float, n_volumes: int,
) -> Optional[np.ndarray]:
    """Read FSL popp .hr or .rvt file (text, per-sample) and downsample to
    one value per BOLD volume (TR rate). Output is float32 length n_volumes.
    Aligns sample 0 to TR-bin 0; partial bins at the end are zero-padded.
    """
    if not txt_path.exists():
        return None
    try:
        arr = np.loadtxt(txt_path)
    except Exception:
        return None
    if arr.ndim > 1:
        # If two columns (time, value), pick value
        arr = arr[:, -1]
    samples_per_vol = max(1, int(round(tr_s * sampling_rate_hz)))
    out = np.zeros(n_volumes, dtype=np.float32)
    for v in range(n_volumes):
        s0 = v * samples_per_vol
        s1 = min(s0 + samples_per_vol, arr.size)
        if s0 >= arr.size:
            break
        out[v] = float(arr[s0:s1].mean())
    return out


def _retroicor_columns_from_pnm(
    evlist_path: Path,
    cord_mask_path: Path,
    n_slices: int,
    work_dir: Path,
    aggregation: str = "slice_mean",
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """For each EV NIfTI from `pnm_evs`, produce ONE column per EV.

    Aggregation choices:
      - "slice_mean" (default, BIDS-friendly): mean across cord-bearing
        slices, scalar timeseries per EV (~32 total columns per run).
        Matches the Kaptan 2023 / Dabbagh 2024 cord recipe (32 RETROICOR
        regressors per run). Slicewise voxelwise EVs remain available
        in the work tree for analysts who want FEAT-style voxelwise
        confound regression.
      - "central_slice": just the central cord slice's timeseries.
      - "slicewise" (research/debug): per-slice columns (~32 × N_slices).

    FSL pnm_evs writes EVs as 4D NIfTI with shape `(1, 1, n_slices, T)`
    when slicewise mode is on (constant within slice, varies across).
    """
    cols: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {"n_evs": 0, "missing": [], "aggregation": aggregation,
                            "cord_slice_indices": []}
    if not evlist_path.exists():
        return cols, meta
    # Determine which slices are "cord-bearing" — use the cord mask
    cord_slices: list[int] = []
    try:
        cord = nib.load(cord_mask_path).get_fdata() > 0.5
        for z in range(min(n_slices, cord.shape[2])):
            if cord[:, :, z].any():
                cord_slices.append(z)
    except Exception:
        cord_slices = list(range(n_slices))
    if not cord_slices:
        cord_slices = list(range(n_slices))
    meta["cord_slice_indices"] = cord_slices

    paths = [Path(p.strip()) for p in evlist_path.read_text().splitlines()
             if p.strip()]
    for i, p in enumerate(paths):
        if not p.is_absolute():
            p = evlist_path.parent / p
        if not p.exists():
            meta["missing"].append(p.name)
            continue
        img = nib.load(p)
        arr = img.get_fdata()
        if arr.ndim != 4:
            continue
        meta["n_evs"] += 1
        ev_name = p.stem.replace(".nii", "")
        Z = arr.shape[2]
        valid_z = [z for z in cord_slices if z < Z]
        if not valid_z:
            continue
        if aggregation == "slicewise":
            for z in valid_z:
                cols[f"retroicor_{ev_name}_slice{z:02d}"] = arr[0, 0, z, :].astype(np.float32)
        elif aggregation == "central_slice":
            zc = valid_z[len(valid_z) // 2]
            cols[f"retroicor_{ev_name}"] = arr[0, 0, zc, :].astype(np.float32)
        else:  # slice_mean (default)
            stack = np.stack([arr[0, 0, z, :] for z in valid_z], axis=0)
            cols[f"retroicor_{ev_name}"] = stack.mean(axis=0).astype(np.float32)
    return cols, meta


# ---------------------------------------------------------------------------
# 5. Cosine basis (DCT high-pass equivalent)
# ---------------------------------------------------------------------------


def _cosine_basis(n_volumes: int, tr_s: float, cutoff_hz: float
                  ) -> dict[str, np.ndarray]:
    """fMRIPrep convention: DCT type-II basis up to (and excluding) cutoff_hz."""
    if n_volumes < 2 or cutoff_hz <= 0:
        return {}
    # nyquist of the temporal sampling
    n_keep = int(np.floor(2 * n_volumes * tr_s * cutoff_hz))
    if n_keep < 1:
        return {}
    cols: dict[str, np.ndarray] = {}
    t = np.arange(n_volumes, dtype=np.float64) + 0.5
    for k in range(1, n_keep + 1):
        c = np.sqrt(2.0 / n_volumes) * np.cos(np.pi * k * t / n_volumes)
        cols[f"cosine_{k - 1:02d}"] = c.astype(np.float32)
    return cols


# ---------------------------------------------------------------------------
# 6. SpinalCompCor (opt-in)
# ---------------------------------------------------------------------------


def _iaaft_surrogate(x: np.ndarray, max_iter: int = 500,
                     rng: np.random.Generator | None = None
                     ) -> np.ndarray:
    """Iterative Amplitude-Adjusted Fourier Transform surrogate.

    Preserves amplitude distribution + power spectrum; randomizes phases.
    Schreiber & Schmitz 1996.
    """
    if rng is None:
        rng = np.random.default_rng()
    n = x.size
    sorted_x = np.sort(x)
    target_amp = np.abs(np.fft.rfft(x))
    # initial: shuffle
    y = rng.permutation(x)
    for _ in range(max_iter):
        Y = np.fft.rfft(y)
        phases = np.angle(Y)
        Y_new = target_amp * np.exp(1j * phases)
        y_temp = np.fft.irfft(Y_new, n)
        ranks = np.argsort(np.argsort(y_temp))
        y_new = sorted_x[ranks]
        if np.allclose(y_new, y):
            break
        y = y_new
    return y


def _iaaft_batch(X: np.ndarray, max_iter: int = 500,
                 rng: np.random.Generator | None = None
                 ) -> np.ndarray:
    """Batched IAAFT: process V timeseries in parallel via vectorized FFT.

    Input X: shape (V, T). Output: surrogates of same shape, each row
    preserves its row's amplitude distribution + power spectrum.
    50–100× faster than per-row loop for V~500.
    """
    if rng is None:
        rng = np.random.default_rng()
    V, T = X.shape
    sorted_X = np.sort(X, axis=1)
    target_amp = np.abs(np.fft.rfft(X, axis=1))  # (V, T//2+1)
    # Initialize Y by per-row shuffle
    perm = np.argsort(rng.standard_normal(X.shape), axis=1)
    Y = np.take_along_axis(X, perm, axis=1).astype(np.float64, copy=False)
    for _ in range(max_iter):
        F = np.fft.rfft(Y, axis=1)
        phases = np.angle(F)
        F_new = target_amp * np.exp(1j * phases)
        Y_temp = np.fft.irfft(F_new, n=T, axis=1)
        # Per-row rank-based amplitude adjustment
        ranks = np.argsort(np.argsort(Y_temp, axis=1), axis=1)
        Y_new = np.take_along_axis(sorted_X, ranks, axis=1)
        if np.allclose(Y_new, Y, rtol=1e-6, atol=1e-9):
            return Y_new
        Y = Y_new
    return Y


def _detrend_dct(ts: np.ndarray, tr_s: float, cutoff_hz: float
                 ) -> np.ndarray:
    """Project out the DCT basis up to cutoff_hz from each row of ts (V, T)."""
    if ts.ndim != 2:
        raise ValueError("ts must be 2D (V, T)")
    n = ts.shape[1]
    cosines = _cosine_basis(n, tr_s, cutoff_hz)
    if not cosines:
        return ts - ts.mean(axis=1, keepdims=True)
    B = np.column_stack(list(cosines.values()))
    # Add intercept
    B = np.column_stack([np.ones(n), B])
    coef, *_ = np.linalg.lstsq(B, ts.T, rcond=None)
    return (ts.T - B @ coef).T


def _spinalcompcor_slicewise(
    bold_path: Path, cord_mask_path: Path, csf_mask_path: Path,
    work_dir: Path,
    dilation_mm: float,
    edge_voxel_remove: int,
    pre_pca_mean_center: bool,
    pre_pca_dct_detrend_hz: float,
    n_iaaft_surrogates: int,
    iaaft_max_iter: int,
    min_voxels_per_slice: int,
    min_volumes: int,
    tr_s: float,
    rng_seed: Optional[int] = None,
    component_selection: str = "fixed_n",
    fixed_n_components: int = 5,
    aggregation: str = "global_3d",
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Slicewise SpinalCompCor (Hemmerling 2025). One PC = one column."""
    bimg = nib.load(bold_path)
    bold = bimg.get_fdata()
    n_volumes = bold.shape[3]
    if n_volumes < min_volumes:
        return {}, {"skipped": "too_few_volumes", "n_volumes": int(n_volumes)}
    zooms = bimg.header.get_zooms()[:3]
    dilate_vox = int(round(dilation_mm / min(zooms[:2])))
    cord = nib.load(cord_mask_path).get_fdata() > 0.5
    csf = nib.load(csf_mask_path).get_fdata() > 0.5
    cord_csf = cord | csf
    from scipy.ndimage import binary_dilation
    dilated = binary_dilation(cord_csf, iterations=dilate_vox)
    noise_roi_full = dilated & ~cord_csf
    # Remove up to N voxels at slice FOV edge
    if edge_voxel_remove > 0:
        noise_roi = np.zeros_like(noise_roi_full)
        e = edge_voxel_remove
        noise_roi[e:-e, e:-e, :] = noise_roi_full[e:-e, e:-e, :]
    else:
        noise_roi = noise_roi_full
    cols: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {
        "dilation_voxels": int(dilate_vox),
        "n_slices_with_pc": 0,
        "pcs_per_slice": [],
        "noise_voxels_per_slice": [],
        "skipped_slices": [],
        "aggregation": aggregation,
    }
    rng = np.random.default_rng(rng_seed if rng_seed is not None else None)
    # Global 3D PCA mode: gather all noise-ROI voxels across all slices,
    # mean-center / DCT-detrend, single SVD → top-K global PCs. Matches
    # fMRIPrep brain a_comp_cor convention. K columns total.
    if aggregation == "global_3d":
        voxel_ts = []
        for z in range(noise_roi.shape[2]):
            m = noise_roi[:, :, z]
            nv = int(m.sum())
            meta["noise_voxels_per_slice"].append(nv)
            if nv < min_voxels_per_slice:
                meta["skipped_slices"].append(z)
                continue
            voxel_ts.append(bold[:, :, z][m].astype(np.float64))
        if not voxel_ts:
            return cols, meta
        ts = np.concatenate(voxel_ts, axis=0)
        if pre_pca_dct_detrend_hz > 0:
            ts = _detrend_dct(ts, tr_s, pre_pca_dct_detrend_hz)
        elif pre_pca_mean_center:
            ts = ts - ts.mean(axis=1, keepdims=True)
        U, S, Vt = np.linalg.svd(ts, full_matrices=False)
        real_eigs = (S ** 2) / max(ts.shape[1] - 1, 1)
        if component_selection == "iaaft":
            n_keep = _parallel_analysis_count(
                ts, real_eigs, n_iaaft_surrogates, iaaft_max_iter, rng,
            )
        elif component_selection == "kaiser":
            n_keep = int((real_eigs > real_eigs.mean()).sum())
        else:
            n_keep = min(int(fixed_n_components), real_eigs.size)
        if n_keep > 0:
            for p in range(n_keep):
                cols[f"spinalcompcor_pc{p:02d}"] = Vt[p].astype(np.float32)
            meta["n_pcs_global"] = int(n_keep)
        return cols, meta
    # Otherwise: slicewise (Hemmerling 2025 paper layout, voluminous cols)
    for z in range(noise_roi.shape[2]):
        m = noise_roi[:, :, z]
        nv = int(m.sum())
        meta["noise_voxels_per_slice"].append(nv)
        if nv < min_voxels_per_slice:
            meta["skipped_slices"].append(z)
            meta["pcs_per_slice"].append(0)
            continue
        ts = bold[:, :, z][m].astype(np.float64)  # (V, T)
        # Pre-PCA processing
        if pre_pca_dct_detrend_hz > 0:
            ts = _detrend_dct(ts, tr_s, pre_pca_dct_detrend_hz)
        elif pre_pca_mean_center:
            ts = ts - ts.mean(axis=1, keepdims=True)
        # SVD: ts (V, T); we want temporal PCs (right-singular vectors)
        U, S, Vt = np.linalg.svd(ts, full_matrices=False)
        real_eigs = (S ** 2) / max(ts.shape[1] - 1, 1)
        # Component selection:
        #   - "fixed_n": top-K (default 5). Matches Behzadi 2007 CompCor /
        #     fMRIPrep convention; fast, no IAAFT.
        #   - "iaaft": Hemmerling 2025 parallel analysis. Validated, but
        #     50 surrogates × 500 iters is ~30 min/run even vectorized.
        #   - "kaiser": eigenvalue > 1 of normalized covariance. Lightweight.
        if component_selection == "iaaft":
            n_keep = _parallel_analysis_count(
                ts, real_eigs, n_iaaft_surrogates, iaaft_max_iter, rng,
            )
        elif component_selection == "kaiser":
            mean_eig = real_eigs.mean()
            n_keep = int((real_eigs > mean_eig).sum())
        else:  # fixed_n (default)
            n_keep = min(int(fixed_n_components), real_eigs.size)
        if n_keep <= 0:
            meta["pcs_per_slice"].append(0)
            continue
        # Vt has shape (min(V,T), T). Take the first n_keep rows = top PCs.
        pcs = Vt[:n_keep]  # (n_keep, T)
        for p in range(n_keep):
            cols[f"spinalcompcor_pc{p:02d}_slice{z:02d}"] = pcs[p].astype(np.float32)
        meta["pcs_per_slice"].append(n_keep)
        meta["n_slices_with_pc"] += 1
    return cols, meta


def _parallel_analysis_count(
    ts: np.ndarray, real_eigs: np.ndarray, n_surrogates: int,
    max_iter: int, rng: np.random.Generator,
) -> int:
    """For each component k, compare real eigvals to surrogate mean. The
    cutoff is the largest k where real_eigs[k] > surrogate_mean[k].

    Vectorized: each surrogate matrix is generated by batched IAAFT
    across all V voxels at once, then SVD. ~100x faster than per-voxel
    loop for typical V (~500 voxels, 50 surrogates).
    """
    V, T = ts.shape
    if V == 0 or T == 0:
        return 0
    K = real_eigs.size
    surrogate_eigs = np.zeros((n_surrogates, K), dtype=np.float64)
    for s in range(n_surrogates):
        S_mat = _iaaft_batch(ts, max_iter=max_iter, rng=rng)
        _, S_vals, _ = np.linalg.svd(S_mat, full_matrices=False)
        surrogate_eigs[s, : S_vals.size] = (S_vals ** 2) / max(T - 1, 1)
    surrogate_mean = surrogate_eigs.mean(axis=0)
    keep = (real_eigs > surrogate_mean)
    for i, k in enumerate(keep):
        if not k:
            return i
    return int(keep.sum())


# ---------------------------------------------------------------------------
# QC + assembly
# ---------------------------------------------------------------------------


def _bpm_cpm_from_popp(work_dir: Path) -> tuple[Optional[float], Optional[float]]:
    """Compute cardiac BPM + respiratory CPM from FSL popp output.

    Cardiac BPM = 60 / median(diff(card_peaks_times)).
    Respiratory CPM = 60 × n_breath_cycles / duration_s, where breath
    cycles are detected from phase wraps in popp_resp.txt.

    Mirrors the calculation in render_s8_pnm_peaks so qc.json and the
    reportlet stay consistent.
    """
    pnm = work_dir / "pnm"
    bpm: Optional[float] = None
    cpm: Optional[float] = None
    card_path = pnm / "popp_card.txt"
    resp_path = pnm / "popp_resp.txt"
    if card_path.exists():
        try:
            card_times = np.loadtxt(card_path)
            if card_times.size > 1:
                bpm = float(60.0 / float(np.median(np.diff(card_times))))
        except Exception:
            bpm = None
    if resp_path.exists():
        try:
            arr = np.loadtxt(resp_path)
            if arr.ndim == 2 and arr.shape[1] == 2:
                t = arr[:, 0]; ph = arr[:, 1]
            elif arr.ndim == 1:
                t = np.arange(arr.size) * 0.0025  # 400 Hz default
                ph = arr
            else:
                t = np.array([]); ph = np.array([])
            if t.size > 1:
                phw = np.mod(ph + np.pi, 2 * np.pi) - np.pi
                n_breaths = int((np.diff(phw) < -np.pi).sum())
                duration_s = float(t[-1] - t[0])
                if duration_s > 0:
                    cpm = float(60.0 * n_breaths / duration_s)
        except Exception:
            cpm = None
    return bpm, cpm


def _condition_number(df: pd.DataFrame) -> float:
    if df.empty:
        return float("nan")
    X = df.to_numpy(dtype=np.float64, copy=False)
    X = X - X.mean(axis=0, keepdims=True)
    # Drop zero-variance cols to avoid NaN
    sd = X.std(axis=0)
    keep = sd > 1e-12
    if not keep.any():
        return float("nan")
    X = X[:, keep] / sd[keep]
    try:
        s = np.linalg.svd(X, compute_uv=False)
        if s[-1] <= 0:
            return float("inf")
        return float(s[0] / s[-1])
    except Exception:
        return float("nan")


_SLICE_COL_RE = re.compile(r"(?:^|_)slice(\d+)")


def _slice_of_column(name: str) -> Optional[int]:
    """The slice index a per-slice regressor belongs to, else None (global).

    Matches the slicewise families' naming: CSF aCompCor ``csf_slice03_pc02``
    and any slicewise RETROICOR ``*_slice03``. Global regressors (motion,
    cosine, spinalcompcor global_3d, slice-mean RETROICOR, outliers) carry no
    ``slice##`` token and stay in every slice's design.
    """
    m = _SLICE_COL_RE.search(name)
    return int(m.group(1)) if m else None


def _condition_number_slicewise(df: pd.DataFrame) -> dict:
    """Per-slice design conditioning (the honest gate for a slicewise GLM).

    Per-slice confound families (CSF aCompCor ``csf_slice{z}_pc{k}``, and any
    slicewise RETROICOR ``*_slice{z}``) are applied SLICE-LOCALLY downstream —
    CoSpi/FEAT hand them to FSL as voxelwise EVs so each slice's GLM only ever
    sees its own 5 CSF PCs (``spi12_acompcor.m`` → ``spi15_*.fsf``). Scoring the
    condition number on the FLAT union of every slice's columns is therefore
    wrong: it stacks 5×N_slices CSF columns into one matrix and explodes for a
    design no voxel actually fits. We instead score each slice's REAL design =
    global regressors + that slice's own per-slice columns, and report the worst
    (max) slice as the headline gate. Falls back to the flat number when no
    per-slice family is present (e.g. CSF disabled).
    """
    if df.empty:
        return {"condition_number": float("nan"), "global_only": float("nan"),
                "worst_slice": None, "per_slice": {}}
    cols = list(df.columns)
    slice_of = {c: _slice_of_column(c) for c in cols}
    global_cols = [c for c in cols if slice_of[c] is None]
    per_slice_cols: dict[int, list[str]] = {}
    for c in cols:
        z = slice_of[c]
        if z is not None:
            per_slice_cols.setdefault(z, []).append(c)

    global_cn = _condition_number(df[global_cols]) if global_cols else float("nan")

    if not per_slice_cols:
        flat = _condition_number(df)
        return {"condition_number": flat, "global_only": flat,
                "worst_slice": None, "per_slice": {}}

    per_slice_cn: dict[int, float] = {}
    for z, scols in sorted(per_slice_cols.items()):
        per_slice_cn[z] = _condition_number(df[global_cols + scols])
    finite = {z: v for z, v in per_slice_cn.items() if np.isfinite(v)}
    if finite:
        worst_z = max(finite, key=finite.get)
        headline = finite[worst_z]
    else:
        worst_z, headline = None, float("inf")
    return {
        "condition_number": float(headline),
        "global_only": float(global_cn),
        "worst_slice": (int(worst_z) if worst_z is not None else None),
        "per_slice": {int(z): float(v) for z, v in per_slice_cn.items()},
    }


def _classify(metrics: dict, thresholds: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    worst = "PASS"
    cn = metrics.get("condition_number")
    pass_cn = thresholds.get("pass_condition_number", 1000.0)
    warn_cn = thresholds.get("warn_condition_number", 10000.0)
    if cn is None or not np.isfinite(cn):
        reasons.append("condition_number not computed")
        worst = "WARN"
    elif cn > warn_cn:
        reasons.append(f"condition_number FAIL: {cn:.1f}")
        worst = "FAIL"
    elif cn > pass_cn:
        reasons.append(f"condition_number WARN: {cn:.1f}")
        if worst == "PASS":
            worst = "WARN"
    # Outlier fraction is observability-only — high motion is the analyst's
    # problem to handle at GLM time, not S8's. We surface it as a WARN flag
    # when it's elevated but never FAIL on it. Datasets like Balgrist
    # KombiShimZSpine routinely have FD > 0.2 mm and outlier_fraction > 50%.
    of = metrics.get("outlier_fraction")
    pass_of = thresholds.get("pass_outlier_fraction_max", 0.20)
    if of is not None and of > pass_of:
        reasons.append(f"outlier_fraction WARN: {of:.2%}")
        if worst == "PASS":
            worst = "WARN"
    return worst, reasons


# ---------------------------------------------------------------------------
# Public per-run entry
# ---------------------------------------------------------------------------


def _build_csf_mask_from_s2(
    s2_canal_dseg: Path, s2_cord_dseg: Path,
    s6_warp_anat_to_bold: Path, bold_ref: Path, work_dir: Path,
) -> Optional[Path]:
    """Warp S2 canal_dseg + cord_dseg (anat space) to BOLD space via S6's
    from-anat_to-bold xfm; subtract cord → CSF in native func.
    """
    canal_in_bold = work_dir / "s2_canal_in_bold.nii.gz"
    cord_in_bold = work_dir / "s2_cord_in_bold.nii.gz"
    for src, dst in [(s2_canal_dseg, canal_in_bold), (s2_cord_dseg, cord_in_bold)]:
        ok, _ = _run_command([
            "sct_apply_transfo",
            "-i", str(src), "-d", str(bold_ref),
            "-w", str(s6_warp_anat_to_bold),
            "-x", "nn", "-o", str(dst),
        ])
        if not ok or not dst.exists():
            return None
    canal = (nib.load(canal_in_bold).get_fdata() > 0.5)
    cord = (nib.load(cord_in_bold).get_fdata() > 0.5)
    csf = canal & ~cord
    if csf.sum() == 0:
        return None
    csf_path = work_dir / "csf_mask_s2_canal_minus_cord.nii.gz"
    img = nib.load(canal_in_bold)
    nib.save(nib.Nifti1Image(csf.astype(np.uint8), img.affine, img.header), csf_path)
    return csf_path


def run_S8_confounds_and_physio_regressors(
    bold_path: Path,
    cord_mask_path: Path,
    csf_mask_path: Optional[Path],
    moco_x_path: Optional[Path],
    moco_y_path: Optional[Path],
    frame_metrics_path: Optional[Path],
    tr_s: float,
    slice_timing_s: Optional[list[float]],
    physio_pairs: Optional[list[tuple[Path, Path]]],
    bold_run: dict,
    out_dir: Path,
    work_dir: Path,
    dataset_key: str,
    policy: dict[str, Any],
    s2_canal_dseg: Optional[Path] = None,
    s2_cord_dseg: Optional[Path] = None,
    s6_warp_anat_to_bold: Optional[Path] = None,
) -> dict[str, Any]:
    """Run S8 for a single BOLD run."""
    step_code = "S8_confounds_and_physio_regressors"
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
        func_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                    / f"sub-{subject}" / f"ses-{session}" / "func")
        figures_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                       / f"sub-{subject}" / f"ses-{session}" / "figures")
    else:
        func_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                    / f"sub-{subject}" / "func")
        figures_dir = (out_dir / "derivatives" / "spineprep" / dataset_key
                       / f"sub-{subject}" / "figures")
    func_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    s8_work_dir = work_dir / step_code / dataset_key / run_id
    s8_work_dir.mkdir(parents=True, exist_ok=True)

    failure_reasons: list[str] = []

    # BOLD geometry
    bimg = nib.load(bold_path)
    bshape = bimg.shape
    n_volumes = int(bshape[3]) if len(bshape) == 4 else 1
    n_slices = int(bshape[2])

    columns: dict[str, np.ndarray] = {}
    family_counts: dict[str, int] = {
        "motion": 0, "csf": 0, "retroicor": 0,
        "cosine": 0, "spinalcompcor": 0, "outliers": 0,
    }
    family_meta: dict[str, Any] = {}

    # 1. Motion family
    if moco_x_path and moco_y_path and moco_x_path.exists() and moco_y_path.exists():
        try:
            mcols = _extract_motion(moco_x_path, moco_y_path, n_volumes)
            for k, v in mcols.items():
                columns[k] = v.astype(np.float32)
                family_counts["motion"] += 1
        except Exception as e:
            failure_reasons.append(f"motion extraction failed: {e}")
            columns["trans_x"] = np.zeros(n_volumes, dtype=np.float32)
            columns["trans_y"] = np.zeros(n_volumes, dtype=np.float32)
            columns["framewise_displacement"] = np.zeros(n_volumes, dtype=np.float32)
            family_counts["motion"] = 3
    else:
        failure_reasons.append("motion: moco_params NIfTI not found")
        columns["trans_x"] = np.zeros(n_volumes, dtype=np.float32)
        columns["trans_y"] = np.zeros(n_volumes, dtype=np.float32)
        columns["framewise_displacement"] = np.zeros(n_volumes, dtype=np.float32)
        family_counts["motion"] = 3

    # 2. Outliers + DVARS/refRMS columns
    mp = policy.get("motion", {})
    if frame_metrics_path and frame_metrics_path.exists():
        frame_metrics = _load_frame_metrics(frame_metrics_path)
        ocols, n_out = _build_outlier_columns(
            frame_metrics,
            columns["framewise_displacement"],
            fd_thresh=float(mp.get("fd_outlier_threshold_mm", 0.5)),
            dvars_iqr_k=float(mp.get("dvars_outlier_iqr_k", 1.5)),
            refrms_iqr_k=float(mp.get("refrms_outlier_iqr_k", 1.5)),
        )
        for k, v in ocols.items():
            columns[k] = v
            if k.startswith("motion_outlier_"):
                family_counts["outliers"] += 1
        outlier_fraction = n_out / max(n_volumes, 1)
    else:
        failure_reasons.append("frame_metrics not found; outliers skipped")
        outlier_fraction = 0.0

    # 3. CSF slicewise — try subject-specific (S2 canal − cord) first;
    # fall back to S7 PAM50csf_mask if the canal warp isn't producible.
    csf_meta = {}
    cp = policy.get("csf_slicewise", {})
    mask_source = str(cp.get("mask_source", "S2_canal_minus_cord"))
    csf_used: Optional[Path] = None
    csf_used_source: Optional[str] = None
    if (cp.get("enabled", True) and mask_source == "S2_canal_minus_cord"
            and s2_canal_dseg and s2_cord_dseg and s6_warp_anat_to_bold
            and s2_canal_dseg.exists() and s2_cord_dseg.exists()
            and s6_warp_anat_to_bold.exists()):
        built = _build_csf_mask_from_s2(
            s2_canal_dseg, s2_cord_dseg, s6_warp_anat_to_bold,
            funcref_local := bold_path, s8_work_dir,
        )
        if built is not None:
            csf_used = built
            csf_used_source = "S2_canal_minus_cord"
    if csf_used is None and csf_mask_path is not None and csf_mask_path.exists():
        csf_used = csf_mask_path
        csf_used_source = "S7_pam50csf"
    csf_meta["mask_source_used"] = csf_used_source
    if (cp.get("enabled", True) and csf_used is not None):
        try:
            ccols, csf_meta_inner = _csf_acompcor_slicewise(
                bold_path, csf_used, s8_work_dir,
                n_components=int(cp.get("n_components", 5)),
                erode_voxels=int(cp.get("erode_voxels", 0)),
                min_voxels_per_slice=int(cp.get("min_voxels_per_slice", 5)),
            )
            csf_meta.update(csf_meta_inner)
            for k, v in ccols.items():
                columns[k] = v
                family_counts["csf"] += 1
        except Exception as e:
            failure_reasons.append(f"csf_slicewise failed: {e}")
    elif cp.get("enabled", True):
        failure_reasons.append("csf_slicewise: CSF mask not found, skipped")
    family_meta["csf"] = csf_meta

    # 4. RETROICOR via FSL PNM
    physio_present = False
    pnm_meta: dict[str, Any] = {}
    rp = policy.get("retroicor", {})
    # SliceTiming reconciliation now handled by orchestrate
    # (_slicetiming_for_bold). When the input length != n_slices, the
    # orchestrate has already substituted a uniform-interleaved
    # approximation (Brooks 2008 cord-RETROICOR convention). slice_timing_s
    # is therefore guaranteed length n_slices when not None.
    slicetiming_ok = bool(
        slice_timing_s is not None and len(slice_timing_s) == n_slices
    )
    # Adapt RETROICOR orders to volume count — short runs can't afford
    # the full 4c + 4r + 16-interaction recipe (would leave < 1 DOF).
    # Heuristic: target retroicor + outliers + csf + motion + cosine
    # ≤ 0.7 × n_volumes. When short, drop interactions first.
    rp_eff = dict(rp)
    if n_volumes < 200:
        rp_eff["interaction_order"] = 0
        rp_eff["_short_run_adaptation"] = True
    if (rp.get("enabled", True) and physio_pairs and slicetiming_ok):
        physio = _load_bids_physio(physio_pairs)
        if physio is None:
            failure_reasons.append("RETROICOR: physio unreadable")
        else:
            physio_present = True
            physio_pnm_path, physio_info = _physio_to_pnm_input(
                physio, s8_work_dir, tr_s=tr_s, n_volumes=n_volumes,
            )
            pnm_meta["physio_info"] = physio_info
            if physio_pnm_path is None:
                failure_reasons.append("RETROICOR: physio missing cardiac/respiratory")
            else:
                slicetiming_path = s8_work_dir / "slicetiming.txt"
                _write_pnm_slicetiming(slice_timing_s, slicetiming_path)
                ok, err, pnm_out = _run_pnm(
                    bold_path=bold_path,
                    physio_pnm_path=physio_pnm_path,
                    slicetiming_path=slicetiming_path,
                    tr_s=tr_s,
                    sampling_rate_hz=float(physio["sampling_frequency_hz"]),
                    cardiac_order=int(rp_eff.get("cardiac_order", 4)),
                    respiratory_order=int(rp_eff.get("respiratory_order", 4)),
                    interaction_order=int(rp_eff.get("interaction_order", 2)),
                    work_dir=s8_work_dir,
                )
                if not ok:
                    failure_reasons.append(f"RETROICOR: {err}")
                else:
                    aggregation = str(rp.get("aggregation", "slice_mean"))
                    rcols, pnm_meta_inner = _retroicor_columns_from_pnm(
                        pnm_out["evlist"], cord_mask_path, n_slices, s8_work_dir,
                        aggregation=aggregation,
                    )
                    pnm_meta.update(pnm_meta_inner)
                    # HR + RVT slow regressors (one column each, downsampled to TR)
                    if rp.get("hr_rvt_enabled", True):
                        if pnm_out.get("hr_file"):
                            hr = _read_popp_slow_regressor(
                                pnm_out["hr_file"],
                                float(physio["sampling_frequency_hz"]),
                                tr_s, n_volumes,
                            )
                            if hr is not None:
                                rcols["heart_rate"] = hr
                        if pnm_out.get("rvt_file"):
                            rvt = _read_popp_slow_regressor(
                                pnm_out["rvt_file"],
                                float(physio["sampling_frequency_hz"]),
                                tr_s, n_volumes,
                            )
                            if rvt is not None:
                                rcols["rvt"] = rvt
                    for k, v in rcols.items():
                        columns[k] = v.astype(np.float32)
                        family_counts["retroicor"] += 1
    elif rp.get("enabled", True):
        failure_reasons.append("RETROICOR: physio TSV / SliceTiming missing — skipped")
    family_meta["retroicor"] = pnm_meta

    # 5. Cosine basis (optional; default ON — DCT high-pass is the cord standard,
    # Kaptan/Dabbagh. Set cosine.enabled: false to omit, e.g. when the analyst's
    # downstream GLM owns high-pass filtering.)
    cob = policy.get("cosine", {})
    if cob.get("enabled", True):
        cccols = _cosine_basis(
            n_volumes=n_volumes, tr_s=tr_s,
            cutoff_hz=float(cob.get("cutoff_hz", 0.01)),
        )
        for k, v in cccols.items():
            columns[k] = v
            family_counts["cosine"] += 1
        family_meta["cosine"] = {"enabled": True, "n_columns": int(family_counts["cosine"])}
    else:
        family_meta["cosine"] = {"enabled": False}

    # 6. SpinalCompCor (opt-in)
    sp = policy.get("spinalcompcor", {})
    sc_meta: dict[str, Any] = {"enabled": bool(sp.get("enabled", False))}
    if sp.get("enabled", False):
        try:
            sccols, sc_meta = _spinalcompcor_slicewise(
                bold_path=bold_path,
                cord_mask_path=cord_mask_path,
                csf_mask_path=csf_used or csf_mask_path or cord_mask_path,
                work_dir=s8_work_dir,
                dilation_mm=float(sp.get("dilation_mm", 18.0)),
                edge_voxel_remove=int(sp.get("edge_voxel_remove", 3)),
                pre_pca_mean_center=bool(sp.get("pre_pca_mean_center", True)),
                pre_pca_dct_detrend_hz=float(sp.get("pre_pca_dct_detrend_hz", 0.01)),
                n_iaaft_surrogates=int(sp.get("n_iaaft_surrogates", 50)),
                iaaft_max_iter=int(sp.get("iaaft_max_iter", 500)),
                min_voxels_per_slice=int(sp.get("min_voxels_per_slice", 10)),
                min_volumes=int(sp.get("min_volumes", 100)),
                tr_s=tr_s,
                rng_seed=1 if policy.get("reproducibility", {}).get("strict", False) else None,
                component_selection=str(sp.get("component_selection", "fixed_n")),
                fixed_n_components=int(sp.get("fixed_n_components", 5)),
                aggregation=str(sp.get("aggregation", "global_3d")),
            )
            sc_meta["enabled"] = True
            for k, v in sccols.items():
                columns[k] = v
                family_counts["spinalcompcor"] += 1
        except Exception as e:
            failure_reasons.append(f"SpinalCompCor failed: {e}")
            sc_meta["error"] = str(e)
    family_meta["spinalcompcor"] = sc_meta

    # Build DataFrame
    df = pd.DataFrame({k: v for k, v in columns.items()})
    # Truncate any column that overshot n_volumes (defensive)
    df = df.iloc[:n_volumes]

    # Condition number QC — per-slice (slicewise GLM), see
    # _condition_number_slicewise. Headline = worst slice's design conditioning.
    cn_info = _condition_number_slicewise(df)
    cn = cn_info["condition_number"]

    # SpinalCompCor: report the actual K (component count). In
    # `aggregation: global_3d` (default) this equals
    # `fixed_n_components` when SpinalCompCor ran; previously
    # `spinalcompcor_median_pcs` always returned NaN because it
    # medianed an empty `pcs_per_slice` list. See
    # .claude/specs/s8-reportlet-set-audit.md.
    sc_n = None
    if sc_meta.get("enabled"):
        per_slice = sc_meta.get("pcs_per_slice") or []
        if per_slice:
            sc_n = int(np.median(per_slice))
        else:
            # global_3d mode: count global PC columns we actually built
            sc_n = int(family_counts.get("spinalcompcor", 0)) or None

    # Cardiac BPM + respiratory CPM from popp output (when PNM ran).
    # Previously documented "populated when PNM ran" but always None.
    cardiac_bpm, respiratory_cpm = _bpm_cpm_from_popp(s8_work_dir)

    # CSF aCompCor is slicewise: n_columns_csf is the flat-TSV total
    # (components × N_slices). The model dimensionality a single slice's GLM
    # actually fits is the PER-SLICE component count — report it explicitly so
    # the reportlet/QC shows 5 (per slice), not the 5×N_slices stacked total.
    _csf_meta = family_meta.get("csf", {})
    _pcs = _csf_meta.get("pcs_per_slice") or []
    csf_n_slices = int(_csf_meta.get("n_slices_with_csf", 0))
    csf_per_slice = (int(np.median(_pcs)) if _pcs
                     else int(policy.get("csf_slicewise", {}).get("n_components", 5)))

    metrics = {
        "n_volumes": int(n_volumes),
        "n_columns_total": int(df.shape[1]),
        "n_columns_motion": int(family_counts["motion"]),
        "n_columns_csf": int(family_counts["csf"]),
        "n_csf_components_per_slice": (csf_per_slice if csf_n_slices else None),
        "n_csf_slices": csf_n_slices,
        "n_columns_retroicor": int(family_counts["retroicor"]),
        "n_columns_cosine": int(family_counts["cosine"]),
        "n_columns_spinalcompcor": int(family_counts["spinalcompcor"]),
        "n_columns_outliers": int(family_counts["outliers"]),
        "outlier_fraction": float(outlier_fraction),
        "condition_number": cn,
        "condition_number_global": cn_info["global_only"],
        "condition_number_worst_slice": cn_info["worst_slice"],
        "fd_mean_mm": float(np.mean(columns["framewise_displacement"])),
        "fd_max_mm": float(np.max(columns["framewise_displacement"])),
        "dvars_mean": float(np.mean(columns["dvars"])) if "dvars" in columns else None,
        "cardiac_bpm_estimate": cardiac_bpm,
        "respiratory_cpm_estimate": respiratory_cpm,
        "spinalcompcor_n_components": sc_n,
    }

    status, reasons = _classify(metrics, policy.get("qc_thresholds", {}))
    failure_reasons.extend(reasons)

    # Write TSV + JSON
    prefix = run_id
    tsv_path = func_dir / f"{prefix}_desc-confounds_timeseries.tsv"
    json_path = func_dir / f"{prefix}_desc-confounds_timeseries.json"
    df.to_csv(tsv_path, sep="\t", index=False, float_format="%.6f", na_rep="n/a")

    policy_sha = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    sidecar = {
        "Description": "Confound regressors per BIDS-Derivatives convention. S8 emits the matrix; S9 (analyst) regresses.",
        "PolicySha256": policy_sha,
        "Software": "SpinePrep S8 + FSL PNM (popp + pnm_evs)",
        "ConfoundFamilies": {
            "motion": "trans_x/y from S4 slicewise NIfTI moco params (mean-over-z), derivative1, FD = |Δx|+|Δy|",
            "outliers": "one-hot for frames where FD > %.2f mm OR DVARS > Q3+%.1f·IQR OR refRMS > Q3+%.1f·IQR" % (
                float(policy.get("motion", {}).get("fd_outlier_threshold_mm", 0.5)),
                float(policy.get("motion", {}).get("dvars_outlier_iqr_k", 1.5)),
                float(policy.get("motion", {}).get("refrms_outlier_iqr_k", 1.5)),
            ),
            "csf": "slicewise CSF aCompCor: top-%d PCs/slice via FSL fslmeants --eig on per-voxel-detrended BOLD (csf_slice{z}_pc{k}); Behzadi 2007 / CoSpi spi12" % int(policy.get("csf_slicewise", {}).get("n_components", 5)),
            "retroicor": "FSL PNM slicewise cardiac/respiratory/interactions × N_slices (cord-mean of voxelwise EVs)",
            "cosine": "DCT type-II basis up to %s Hz (~%.0f s high-pass)" % (
                str(policy.get("cosine", {}).get("cutoff_hz", 0.01)),
                1.0 / float(policy.get("cosine", {}).get("cutoff_hz", 0.01)),
            ),
            "spinalcompcor": "Hemmerling 2025: 18 mm noise ROI, mean-center + DCT-detrend, IAAFT parallel analysis (when enabled)",
        },
        "Columns": list(df.columns),
        "FamilyCounts": family_counts,
        "PhysioPresent": bool(physio_present),
        "SpinalCompCorEnabled": bool(sc_meta.get("enabled", False)),
    }
    json_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    # Save work-side qc metrics
    (s8_work_dir / "qc_metrics.json").write_text(json.dumps({
        "metrics": metrics,
        "family_meta": family_meta,
        "failure_reasons": failure_reasons,
        "policy_sha256": policy_sha,
    }, indent=2, default=str))

    # Reportlets — 5 PNGs, visual-standard chrome (status pill + dark theme).
    # csf_variance reportlet dropped 2026-05-28 — its info is already in
    # metrics.n_columns_csf + the correlation_heatmap.
    # carpet_plot added 2026-05-28 (Power 2017 / fMRIPrep standard).
    from .reportlets import (
        render_s8_confound_columns,
        render_s8_fd_dvars_outliers,
        render_s8_pnm_peaks,
        render_s8_correlation_heatmap,
        render_s8_carpet_plot,
    )
    rep_cols    = figures_dir / f"{prefix}_desc-S8_confound_columns.png"
    rep_fd      = figures_dir / f"{prefix}_desc-S8_fd_dvars_outliers.png"
    rep_pnm     = figures_dir / f"{prefix}_desc-S8_pnm_peaks.png"
    rep_corr    = figures_dir / f"{prefix}_desc-S8_correlation_heatmap.png"
    rep_carpet  = figures_dir / f"{prefix}_desc-S8_carpet_plot.png"

    # Outlier indices for the FD/DVARS panels — derived from the one-hot
    # motion_outlier_NN columns we already built.
    outlier_indices = np.array([
        int(np.argmax(v)) for k, v in columns.items()
        if k.startswith("motion_outlier_")
    ], dtype=int)
    fd_thr = float(policy.get("motion", {}).get("fd_outlier_threshold_mm", 0.5))

    try:
        render_s8_confound_columns(
            family_counts, sidecar, rep_cols,
            status=status,
            n_columns_total=metrics.get("n_columns_total"),
            condition_number=metrics.get("condition_number"),
            csf_per_slice=metrics.get("n_csf_components_per_slice"),
            csf_n_slices=metrics.get("n_csf_slices"),
        )
    except Exception as e:
        failure_reasons.append(f"confound_columns reportlet failed: {e}")
    try:
        render_s8_fd_dvars_outliers(
            columns.get("framewise_displacement"),
            columns.get("dvars"), columns.get("ref_rms"),
            family_counts["outliers"], rep_fd,
            status=status,
            fd_thresh=fd_thr,
            outlier_indices=outlier_indices,
        )
    except Exception as e:
        failure_reasons.append(f"fd_dvars_outliers reportlet failed: {e}")
    try:
        render_s8_pnm_peaks(
            s8_work_dir, physio_present, rep_pnm,
            status=status,
        )
    except Exception as e:
        failure_reasons.append(f"pnm_peaks reportlet failed: {e}")
    try:
        render_s8_correlation_heatmap(
            df, rep_corr,
            status=status,
            condition_number=metrics.get("condition_number"),
        )
    except Exception as e:
        failure_reasons.append(f"correlation_heatmap reportlet failed: {e}")
    try:
        # Cord-restricted carpet plot of the BOLD timeseries (Power 2017
        # / fMRIPrep standard). Uses the cord_mask the orchestrator
        # already passed; bold_path is the same 4D used for csf+spcc.
        render_s8_carpet_plot(
            bold_path=bold_path,
            cord_mask_path=cord_mask_path,
            output_path=rep_carpet,
            fd=columns.get("framewise_displacement"),
            dvars=columns.get("dvars"),
            status=status,
            fd_thresh=fd_thr,
            outlier_indices=outlier_indices,
        )
    except Exception as e:
        failure_reasons.append(f"carpet_plot reportlet failed: {e}")

    return {
        "status": status,
        "step_code": step_code,
        "dataset_key": dataset_key,
        "subject": subject,
        "session": session,
        "run_id": run_id,
        "physio_present": bool(physio_present),
        "spinalcompcor_enabled": bool(sc_meta.get("enabled", False)),
        "metrics": metrics,
        "failure_reasons": failure_reasons,
        "failure_message": "; ".join(failure_reasons) if failure_reasons else None,
        "reportlets": {
            "carpet_plot":         str(rep_carpet.relative_to(out_dir)) if rep_carpet.exists() else "",
            "fd_dvars_outliers":   str(rep_fd.relative_to(out_dir))     if rep_fd.exists() else "",
            "confound_columns":    str(rep_cols.relative_to(out_dir))   if rep_cols.exists() else "",
            "pnm_peaks":           str(rep_pnm.relative_to(out_dir))    if rep_pnm.exists() else "",
            "correlation_heatmap": str(rep_corr.relative_to(out_dir))   if rep_corr.exists() else "",
        },
        "confounds_paths": {
            "tsv":  str(tsv_path.relative_to(out_dir)),
            "json": str(json_path.relative_to(out_dir)),
        },
    }
