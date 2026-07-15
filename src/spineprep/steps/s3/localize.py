"""S3.1: Dummy drop, coarse functional reference (median over all
dummy-dropped frames), cord localization, brain-contamination check
(internal: drift gate), and `func_ref0` for downstream S3.2.

Naming notes: the "coarse functional reference" follows fMRIPrep's
"coarse / initial reference volume" terminology; the on-disk filename
is `func_ref_fast.nii.gz`, kept stable for the S4-S10 downstream
contract. The "brain-contamination check" is what the policy YAML
and code call `drift_gate` (kept for backwards compatibility); user-
facing text uses the literature-aligned name."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np

from spineprep.lib.run import run_command as _run_command
from spineprep.subtask import (
    should_exit_after_subtask,
    subtask,
    subtask_context,
)

from .io import _extract_subject_session_from_work_dir
from .localize_viz import _render_s3_1_simple_func_with_mask  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_drift_gate(
    disc_data: np.ndarray,
    affine: np.ndarray,
    policy: dict[str, Any],
) -> tuple[bool, str, dict]:
    """Detect brain contamination in a cord segmentation.

    Cervical cord cross-sectional area is ~60-90 mm² (Piaggio 2018: 88.9 ± 6.0
    at the foramen magnum, 74.8 ± 4.9 at C2-C3). A segmentation that climbs past
    the cord enters the MEDULLA, which is only ~130-175 mm² (derived from
    published volumes; no axial medulla CSA appears to be published) -- roughly
    1.4x the cord over the first centimetre, NOT an order of magnitude. The
    order-of-magnitude figure (~500 mm²) belongs to the PONS, several centimetres
    higher, and should not be used to justify these thresholds.

    Consequence: the absolute cap is a gross-contamination backstop, not an
    early-leak detector -- a leak must climb ~1.3 cm before a 200 mm² cap fires.
    The relative spike test is what does the real work. A gradient test (cord
    tapers ~1.2 mm²/mm, measured on PAM50_cord; entering the medulla is
    ~8.6 mm²/mm) or a PMJ-referenced extent cap (sct_detect_pmj) would be more
    sensitive; see .claude/specs/s3-algorithm-audit.md.

    Two cheap checks on the most-superior `n_check` cord slices:

    - absolute cap: any of those slices exceeds `absolute_area_cap_mm2`
    - spike ratio: top slice area / immediately-inferior slice area > `area_spike_threshold`

    Returns (passed, message, info-dict). `info` carries per-slice areas so
    the QC log can show why a run was rejected.
    """
    drift_cfg = (
        policy.get("func_localization", {})
        .get("discover", {})
        .get("drift_gate", {})
    )
    if not drift_cfg.get("enabled", True):
        return True, "drift_gate disabled", {}

    n_check = int(drift_cfg.get("superior_slices_check", 5))
    spike_ratio = float(drift_cfg.get("area_spike_threshold", 4.0))
    abs_cap_mm2 = float(drift_cfg.get("absolute_area_cap_mm2", 200.0))
    # Minimum cord extent: discover.min_z_slices is the policy slot.
    min_z_slices = int(
        policy.get("func_localization", {}).get("discover", {}).get("min_z_slices", 0)
    )

    # Find the inferior-superior axis from the affine
    try:
        axcodes = nib.orientations.aff2axcodes(affine)
    except Exception:
        return True, "could not read orientation; drift_gate skipped", {}

    is_axis = None
    s_is_positive = None
    for i, c in enumerate(axcodes):
        if c == "S":
            is_axis, s_is_positive = i, True
            break
        if c == "I":
            is_axis, s_is_positive = i, False
            break
    if is_axis is None:
        return True, "no IS axis; drift_gate skipped", {}

    # Per-slice (along IS axis) area in mm²
    voxel_sizes = np.sqrt((affine[:3, :3] ** 2).sum(axis=0))
    in_plane = [i for i in (0, 1, 2) if i != is_axis]
    voxel_area_mm2 = float(voxel_sizes[in_plane[0]] * voxel_sizes[in_plane[1]])

    sum_axes = tuple(in_plane)
    slice_areas_mm2 = ((disc_data > 0).sum(axis=sum_axes) * voxel_area_mm2).astype(float)

    nonzero = np.where(slice_areas_mm2 > 0)[0]
    if nonzero.size == 0:
        return False, "empty segmentation", {"slice_areas_mm2": slice_areas_mm2.tolist()}

    # Order superior-to-inferior
    if s_is_positive:
        superior_zs = nonzero[-n_check:][::-1].tolist()
    else:
        superior_zs = nonzero[:n_check].tolist()

    info = {
        "slice_areas_mm2": slice_areas_mm2.tolist(),
        "is_axis": int(is_axis),
        "s_is_positive": bool(s_is_positive),
        "n_cord_slices": int(nonzero.size),
        "thresholds": {
            "absolute_area_cap_mm2": abs_cap_mm2,
            "area_spike_threshold": spike_ratio,
            "superior_slices_check": n_check,
            "min_z_slices": min_z_slices,
        },
        "checked_slices": [int(z) for z in superior_zs],
    }

    # Minimum extent: discovery must span at least min_z_slices along IS.
    if min_z_slices > 0 and nonzero.size < min_z_slices:
        return (
            False,
            f"cord too short: only {int(nonzero.size)} slices of segmentation "
            f"(< min_z_slices={min_z_slices})",
            info,
        )

    # Absolute cap: any superior slice with area > cap is brain
    for z in superior_zs:
        a = slice_areas_mm2[z]
        if a > abs_cap_mm2:
            return (
                False,
                f"brain detected: slice z={int(z)} area {a:.1f} mm² > cap {abs_cap_mm2:.0f} mm²",
                info,
            )

    # Spike: top slice vs the slice immediately inferior to it
    if len(superior_zs) >= 1:
        for z in superior_zs:
            below_z = z - 1 if s_is_positive else z + 1
            if 0 <= below_z < slice_areas_mm2.size:
                below = slice_areas_mm2[below_z]
                top = slice_areas_mm2[z]
                if below > 0 and top / below > spike_ratio:
                    return (
                        False,
                        f"brain detected: area spike at z={int(z)} "
                        f"({top:.1f}/{below:.1f} = {top / below:.2f}× > {spike_ratio:.1f}×)",
                        info,
                    )

    return True, "ok", info


def _caudal_union(
    deepseg: np.ndarray,
    propseg: np.ndarray,
    affine: np.ndarray,
    lateral_tol_vox: float,
    max_gap: int = 0,
    area_mult: float = 3.0,
    axis_tol_vox: float = 3.1,
) -> tuple[np.ndarray, list[int]]:
    """Extend a deepseg cord mask caudally using propseg's cord.

    `sct_deepseg spinalcord` on the *coarse* full-FOV functional reference
    sometimes gives up on the caudal (lower) cord where coil sensitivity /
    SNR is poor, so the mask stops partway down and the cord-focused crop
    derived from it cuts off real cord. `sct_propseg` is a deformable
    propagation model that tracks the cord as a tube; it reaches slightly
    further caudally and — critically — stays cord-shaped (it does not leak
    into the bright anterior airway/pharynx, which is the classic
    false-positive when extending a mask by brightness alone).

    This unions propseg's cord voxels onto deepseg for the *contiguous*
    stretch of slices immediately caudal to deepseg's caudal end, with four
    guards that keep it safe:

    - **Caudal-only, never cranial.** We only ever add slices below
      deepseg's caudal end, so propseg's habit of over-reaching up into the
      brainstem is discarded and the superior brain-contamination gate is
      untouched.
    - **Axis-deviation guard.** A genuine short caudal cord continuation is
      near-straight — it stays within a couple of voxels of the deepseg
      cord centreline extrapolated linearly downward. propseg sometimes
      keeps propagating past the true cord end onto a bright prevertebral
      vessel / airway that curves progressively off-axis; the added slice's
      centroid must stay within `axis_tol_vox` of the extrapolated axis, so
      that runaway is cut off. (Empirically genuine extensions deviate
      <2 vox; runaways cross 3+.)
    - **Lateral-jump guard.** Each added slice's propseg centroid must also
      lie within `lateral_tol_vox` of the *previous* accepted centroid,
      catching an abrupt single-slice jump.
    - **Area guard.** A propseg slice larger than `area_mult` × the median
      deepseg cord area is a bright CSF pool / non-cord blob, not cord.

    Stops at the first gap (> `max_gap`), off-axis slice, lateral jump, or
    ballooned slice. On runs whose deepseg mask already reaches the imaged
    cord end / FOV edge, propseg has nothing contiguous below to add, so
    this is a no-op (0 slices).

    Returns (completed_mask, added_slice_indices).
    """
    try:
        axcodes = nib.orientations.aff2axcodes(affine)
    except Exception:
        return deepseg, []
    iax = next((i for i, c in enumerate(axcodes) if c in ("S", "I")), None)
    if iax is None:
        return deepseg, []
    s_pos = axcodes[iax] == "S"

    D = np.moveaxis(deepseg > 0, iax, 2)
    P = np.moveaxis(propseg > 0, iax, 2)
    out = D.copy()

    dcoords = np.argwhere(D)
    dz = np.unique(dcoords[:, 2])
    if dz.size == 0:
        return deepseg, []
    # Median deepseg cord cross-section area — used to reject a propseg slice
    # that balloons well beyond cord size (a large bright CSF pool / airway).
    med_area = float(np.median([(dcoords[:, 2] == z).sum() for z in dz]))
    area_cap = area_mult * med_area
    # Caudal = most-inferior imaged slice of the deepseg mask.
    step = -1 if s_pos else 1
    z_caud = int(dz.min()) if s_pos else int(dz.max())

    def _centroid(mask3d, z):
        pts = np.argwhere(mask3d[:, :, z])
        return pts[:, :2].mean(axis=0) if pts.size else None

    ref_c = _centroid(D, z_caud)
    if ref_c is None:
        return deepseg, []

    # Linear fit of the deepseg cord centreline (in-plane x,y vs slice z),
    # extrapolated caudally to bound how far propseg may wander off-axis.
    d_cents = np.array([_centroid(D, int(z)) for z in dz])
    if dz.size >= 2:
        fit_x = np.polyfit(dz, d_cents[:, 0], 1)
        fit_y = np.polyfit(dz, d_cents[:, 1], 1)
    else:
        fit_x = np.array([0.0, float(ref_c[0])])
        fit_y = np.array([0.0, float(ref_c[1])])

    added: list[int] = []
    gap = 0
    z = z_caud + step
    nz = D.shape[2]
    while 0 <= z < nz:
        pc = _centroid(P, z)
        if pc is None:
            gap += 1
            if gap > max_gap:
                break
            z += step
            continue
        axis_pt = np.array([np.polyval(fit_x, z), np.polyval(fit_y, z)])
        if float(np.hypot(*(pc - axis_pt))) > axis_tol_vox:
            break  # propseg drifted off the extrapolated cord axis (non-cord)
        if float(np.hypot(*(pc - ref_c))) > lateral_tol_vox:
            break  # propseg jumped off the cord axis (e.g. onto the airway)
        if float(P[:, :, z].sum()) > area_cap:
            break  # propseg ballooned beyond cord size (bright CSF pool / airway)
        out[:, :, z] |= P[:, :, z]
        added.append(z)
        ref_c = pc
        gap = 0
        z += step

    if not added:
        return deepseg, []
    completed = np.moveaxis(out, 2, iax).astype(deepseg.dtype)
    return completed, [int(z) for z in added]


def _robust_cord_area(disc: np.ndarray, iax: int, s_pos: bool) -> float:
    """Robust per-slice cord cross-section (voxels) of a deepseg mask.

    A trimmed median over the mask's slices: the biggest slices (the
    medulla / cervico-medullary junction, which dwarf the cord) and the
    single tapering caudal sliver are dropped, leaving the representative
    cervical cord area. Used to scale the caudal-trace area gates so they
    adapt to each run's cord size rather than a fixed absolute.
    """
    D = np.moveaxis(disc > 0, iax, 2)
    dz = np.unique(np.argwhere(D)[:, 2])
    a = np.array([int(D[:, :, int(z)].sum()) for z in dz], dtype=float)
    a = a[a > 0]
    if a.size == 0:
        return 20.0
    lo, hi = np.percentile(a, [15, 75])
    core = a[(a >= lo) & (a <= hi)]
    return float(np.median(core)) if core.size else float(np.median(a))


def _caudal_trace(
    deepseg: np.ndarray,
    refimg: np.ndarray,
    affine: np.ndarray,
    intensity_frac: float = 0.5,
    radius_vox: int = 6,
    lateral_tol_mm: float = 5.0,
    core_area_max: float = 2.2,
    band_area_max: float = 3.0,
    min_area_vox: int = 6,
    core_peak_frac: float = 0.6,
    max_gap: int = 1,
    ref_slices: int = 5,
) -> tuple[np.ndarray, list[int]]:
    """Extend a cord mask caudally by tracing the cord on the reference image.

    `sct_deepseg spinalcord` (and `sct_propseg`) give up on the caudal cord
    where SNR / coil sensitivity is poor, so the mask stops partway down and
    the crop derived from it cuts real cord. Neither model re-activates on the
    faint tail, so this stage traces the cord directly on the coarse functional
    reference, slice by slice, starting from the (propseg-completed) caudal end.

    At each caudal slice it looks in a window around the previous cord centroid
    and thresholds at `intensity_frac` × the caudal cord intensity. The nearest
    bright connected component to the axis is the candidate. Two size gates,
    both scaled by the run's own robust cord area, separate genuine caudal cord
    from the bright CSF-filled spinal canal (the dominant false positive at this
    SNR):

    - **band gate** — the full component (thresholded at the intensity floor)
      must not exceed `band_area_max` × cord area. A wide, uniformly-bright CSF
      band fills the window and trips this; an isolated cord blob does not.
    - **core gate** — the compact bright *core* (component ∩ ≥ `core_peak_frac`
      × local peak) must not exceed `core_area_max` × cord area. This isolates
      the cord peak from a dim halo on low-SNR runs, yet a uniformly-bright CSF
      band still yields a large core and is rejected.

    A per-slice **lateral-jump** guard keeps the trace on the cord axis (the
    anterior airway sits ~15 mm off and is rejected). `max_gap` bridges a single
    faint/noisy slice; two consecutive rejects stop the trace — so a run whose
    caudal signal is CSF-dominated immediately below the terminus is a no-op.
    Only the compact core is painted into the mask (never the CSF band).

    Stops honestly at the noise / CSF floor: where the caudal cord fades into
    noise or is inseparable from CSF, the trace stops rather than fabricate cord.

    Returns (completed_mask, added_slice_indices). No-op ([]) when nothing
    cord-like persists below the caudal end.
    """
    from scipy import ndimage  # optional dep; keep module import light

    try:
        axcodes = nib.orientations.aff2axcodes(affine)
    except Exception:
        return deepseg, []
    iax = next((i for i, c in enumerate(axcodes) if c in ("S", "I")), None)
    if iax is None:
        return deepseg, []
    s_pos = axcodes[iax] == "S"

    D = np.moveaxis(deepseg > 0, iax, 2)
    IM = np.moveaxis(refimg, iax, 2)
    zooms = np.sqrt((affine[:3, :3] ** 2).sum(axis=0))
    in_plane = [i for i in (0, 1, 2) if i != iax]
    px, py = float(zooms[in_plane[0]]), float(zooms[in_plane[1]])

    coords = np.argwhere(D)
    if coords.size == 0:
        return deepseg, []
    dz = np.unique(coords[:, 2])
    step = -1 if s_pos else 1
    z_caud = int(dz.min()) if s_pos else int(dz.max())
    order = sorted(dz.tolist(), key=lambda z: z, reverse=(not s_pos))  # caudal-first

    robust = _robust_cord_area(deepseg, iax, s_pos)
    core_cap = core_area_max * robust
    band_cap = band_area_max * robust
    # Cord intensity learned from the caudal-most deepseg slices (the low-SNR
    # operating point), not the bright rostral medulla.
    cordI = float(np.median([
        np.median(IM[:, :, int(z)][D[:, :, int(z)]]) for z in order[:ref_slices]
    ]))
    floor = intensity_frac * cordI

    out = D.copy()
    added: list[int] = []
    gap = 0
    prev = np.argwhere(D[:, :, z_caud]).mean(axis=0)
    z = z_caud + step
    R = int(radius_vox)
    nz = D.shape[2]
    while 0 <= z < nz:
        sl = IM[:, :, z]
        cx, cy = prev
        x0 = max(0, int(round(cx)) - R); x1 = min(sl.shape[0], int(round(cx)) + R + 1)
        y0 = max(0, int(round(cy)) - R); y1 = min(sl.shape[1], int(round(cy)) + R + 1)
        win = sl[x0:x1, y0:y1]
        if win.size == 0:
            break
        peak = float(win.max())
        if peak < floor:
            gap += 1
            if gap > max_gap:
                break  # faded into noise
            z += step
            continue
        m = win >= floor
        lab, n = ndimage.label(m)
        pc = (cx - x0, cy - y0)
        best = None
        for lbl in range(1, n + 1):
            comp = lab == lbl
            band_a = int(comp.sum())
            yy, xx = ndimage.center_of_mass(comp)
            d = float(np.hypot((yy - pc[0]) * px, (xx - pc[1]) * py))
            if best is None or d < best[0]:
                best = (d, band_a, comp)
        _d, band_a, comp = best
        core = comp & (win >= max(floor, core_peak_frac * peak))
        if int(core.sum()) < min_area_vox:
            core = comp
        core_a = int(core.sum())
        yy, xx = ndimage.center_of_mass(core)
        gx, gy = yy + x0, xx + y0
        latd = float(np.hypot((gx - cx) * px, (gy - cy) * py))
        reject = (
            core_a < min_area_vox
            or core_a > core_cap
            or band_a > band_cap
            or latd > lateral_tol_mm
        )
        if reject:
            gap += 1
            if gap > max_gap:
                break
            z += step
            continue
        full = np.zeros_like(sl, dtype=bool)
        full[x0:x1, y0:y1] = core
        out[:, :, z] |= full
        added.append(int(z))
        prev = np.array([gx, gy])
        gap = 0
        z += step

    if not added:
        return deepseg, []
    completed = np.moveaxis(out, 2, iax).astype(deepseg.dtype)
    return completed, sorted(added)


def _extend_caudal_via_trace(
    func_ref_fast_path: Path,
    discovery_seg_path: Path,
    policy: dict[str, Any],
) -> list[int]:
    """Trace the caudal cord on the reference and union it onto the seg.

    Second stage of caudal completion, run after the propseg union. Overwrites
    `discovery_seg_path` in place when it adds slices. Strictly additive and
    failure-swallowing: any error leaves the mask untouched. Gated by
    ``func_localization.discover.caudal_completion.trace.enabled``.
    """
    cfg = (
        policy.get("func_localization", {})
        .get("discover", {})
        .get("caudal_completion", {})
        .get("trace", {})
    )
    if not cfg.get("enabled", True):
        return []
    try:
        disc_img = nib.load(discovery_seg_path)
        disc_data = disc_img.get_fdata()
        ref_data = nib.load(func_ref_fast_path).get_fdata()
        if ref_data.shape != disc_data.shape:
            return []
        completed, added = _caudal_trace(
            disc_data, ref_data, disc_img.affine,
            intensity_frac=float(cfg.get("intensity_frac", 0.5)),
            radius_vox=int(cfg.get("radius_vox", 6)),
            lateral_tol_mm=float(cfg.get("lateral_tol_mm", 5.0)),
            core_area_max=float(cfg.get("core_area_max", 2.2)),
            band_area_max=float(cfg.get("band_area_max", 3.0)),
            min_area_vox=int(cfg.get("min_area_vox", 6)),
            core_peak_frac=float(cfg.get("core_peak_frac", 0.6)),
            max_gap=int(cfg.get("max_gap", 1)),
        )
    except Exception:
        return []
    if added:
        nib.save(nib.Nifti1Image(completed, disc_img.affine, disc_img.header),
                 discovery_seg_path)
    return added


def _extend_caudal_via_propseg(
    func_ref_fast_path: Path,
    discovery_seg_path: Path,
    qc_dir: Path,
    policy: dict[str, Any],
) -> list[int]:
    """Run propseg and union its caudal cord onto the deepseg discovery seg.

    Overwrites `discovery_seg_path` in place with the completed mask when it
    adds any slices. Returns the list of added slice indices ([] = no-op).
    Any failure (propseg missing/errored, empty output) is swallowed and
    leaves the deepseg mask untouched — the completion is strictly additive
    and must never make localization worse.
    """
    cfg = (
        policy.get("func_localization", {})
        .get("discover", {})
        .get("caudal_completion", {})
    )
    if not cfg.get("enabled", True):
        return []

    disc_img = nib.load(discovery_seg_path)
    disc_data = disc_img.get_fdata()
    zooms = np.sqrt((disc_img.affine[:3, :3] ** 2).sum(axis=0))
    in_plane_mm = float(min(zooms[0], zooms[1])) or 1.0
    lateral_tol_vox = float(cfg.get("lateral_tol_mm", 8.0)) / in_plane_mm
    max_gap = int(cfg.get("max_gap", 0))
    area_mult = float(cfg.get("area_mult", 3.0))
    axis_tol_vox = float(cfg.get("axis_tol_mm", 5.0)) / in_plane_mm

    propseg_path = qc_dir / "func_ref_fast_propseg.nii.gz"
    propseg_path.parent.mkdir(parents=True, exist_ok=True)
    contrast = str(cfg.get("propseg_contrast", "t2"))
    cmd = [
        "sct_propseg",
        "-i", str(func_ref_fast_path),
        "-c", contrast,
        "-o", str(propseg_path),
        "-v", "0",
    ]
    ok, _out = _run_command(cmd)
    if not ok or not propseg_path.exists():
        return []

    try:
        prop_img = nib.load(propseg_path)
        prop_data = prop_img.get_fdata()
        if prop_data.shape != disc_data.shape:
            return []
        completed, added = _caudal_union(
            disc_data, prop_data, disc_img.affine, lateral_tol_vox, max_gap,
            area_mult, axis_tol_vox,
        )
    except Exception:
        return []

    if added:
        nib.save(nib.Nifti1Image(completed, disc_img.affine, disc_img.header),
                 discovery_seg_path)
    return added


def _create_dummy_discovery(data: np.ndarray, affine: np.ndarray, seg_path: Path, roi_path: Path) -> None:
    """Fallback: Center-of-image dummy discovery."""
    discovery_seg_data = np.zeros_like(data)
    center_x = data.shape[0] // 2
    center_y = data.shape[1] // 2
    center_z = data.shape[2] // 2

    # Create a central box detection (approx 20x20x10 voxels)
    # This prevents the "horizontal bar" (full slice slab) appearance
    x_r, y_r, z_r = 10, 10, 5

    x_min, x_max = max(0, center_x - x_r), min(data.shape[0], center_x + x_r)
    y_min, y_max = max(0, center_y - y_r), min(data.shape[1], center_y + y_r)
    z_min, z_max = max(0, center_z - z_r), min(data.shape[2], center_z + z_r)

    discovery_seg_data[x_min:x_max, y_min:y_max, z_min:z_max] = 1

    nib.save(nib.Nifti1Image(discovery_seg_data, affine), seg_path)
    nib.save(nib.Nifti1Image(discovery_seg_data, affine), roi_path)


def _cleanup_epi_cordseg(seg_path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Clean the raw EPISeg (``sct_deepseg sc_epi``) cord mask in place.

    EPISeg follows the full cord (including the anterior cervical curve) but
    (a) can split the cord into two on-axis components across the low-SNR/
    high-distortion curve gap, and (b) emits a few off-axis specks up in the
    brain when the FOV includes it. A naive ``-largest 1`` would keep only the
    bigger cord fragment and re-truncate the cord — the exact failure this fix
    exists to remove. So instead we **bridge** the cord fragments along Z (a
    short Z-only dilation closes the 1-2 slice curve gap while leaving the
    superior, off-axis brain specks in separate components), pick the bridged
    group holding the most original cord voxels, and keep only the original
    voxels in that group. This preserves the exact cord voxels (no erosion),
    unions the upper+lower fragments, and drops the specks.

    Returns a small stats dict for the QC json; never raises on a degenerate
    mask (empty or single-component → no-op).
    """
    from scipy import ndimage

    bridge_z = int(
        policy.get("func_localization", {})
        .get("cleanup", {})
        .get("bridge_z_slices", 2)
    )
    img = nib.load(seg_path)
    data = np.asarray(img.get_fdata()) > 0
    stats: dict[str, Any] = {
        "cord_seg_model": "sc_epi",
        "bridge_z_slices": bridge_z,
        "n_components": 0,
        "components_kept": 0,
        "components_dropped": 0,
        "voxels_dropped": 0,
    }
    if data.sum() == 0:
        return stats

    struct26 = ndimage.generate_binary_structure(3, 3)
    lab0, n0 = ndimage.label(data, structure=struct26)
    stats["n_components"] = int(n0)
    if n0 <= 1:
        stats["components_kept"] = int(n0)
        return stats

    # Bridge along Z only, so cord fragments across the curve gap merge but
    # superior off-axis specks stay separate.
    z_struct = np.zeros((3, 3, 3), dtype=bool)
    z_struct[1, 1, :] = True
    bridged = ndimage.binary_dilation(data, structure=z_struct, iterations=bridge_z)
    lab_b, n_b = ndimage.label(bridged, structure=struct26)
    # Cord group = bridged component holding the most ORIGINAL cord voxels.
    orig_counts = ndimage.sum(data, lab_b, index=np.arange(1, n_b + 1))
    cord_group = int(np.argmax(orig_counts)) + 1
    keep = data & (lab_b == cord_group)

    kept_labels = set(int(v) for v in np.unique(lab0[keep])) - {0}
    stats["components_kept"] = len(kept_labels)
    stats["components_dropped"] = int(n0 - len(kept_labels))
    stats["voxels_dropped"] = int(data.sum() - keep.sum())

    nib.save(
        nib.Nifti1Image(keep.astype(np.uint8), img.affine, img.header), seg_path
    )
    return stats


# ---------------------------------------------------------------------------
# S3.1 main processing function
# ---------------------------------------------------------------------------


@subtask("S3.1")
def _process_s3_1_dummy_drop_and_localization(
    bold_path: Path,
    work_dir: Path,
    policy: dict[str, Any],
    subject: Optional[str] = None,
    session: Optional[str] = None,
    out_root: Optional[Path] = None,
    cordref_std_path: Optional[Path] = None,
    cordmask_dseg_path: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    S3.1: Dummy-volume drop + coarse functional reference + cord localization + func_ref0.

    The "coarse functional reference" (fMRIPrep terminology; on-disk
    filename `func_ref_fast.nii.gz` kept for the downstream contract
    with S4-S10) is the median over all dummy-dropped frames. It is
    cheap to compute and is later refined to the robust functional
    reference in S3.2 (median over non-outlier frames only).

    This function:
    1. Drops dummy volumes per policy
    2. Computes the coarse functional reference `func_ref_fast`
       (median of all frames; SCT batch_processing convention)
    3. Localizes cord in func space (S2 exact spec)
    4. Computes func_ref0 from cropped region
    5. Renders S3.1 figure (brain-contamination check is applied
       here; failure path emits a stub with the rejection reason)

    Returns:
        Dictionary with results including the coarse functional
        reference (`func_ref_fast`), func_ref0, localization results.
    """
    # Create init directory
    init_dir = work_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    # Define expected output paths
    func_ref_fast_path = init_dir / "func_ref_fast.nii.gz"
    func_ref0_path = init_dir / "func_ref0.nii.gz"
    localize_dir = init_dir / "localize"
    localize_dir.mkdir(parents=True, exist_ok=True)
    discovery_seg_path = localize_dir / "func_ref_fast_seg.nii.gz"
    roi_mask_path = localize_dir / "func_ref_fast_roi_mask.nii.gz"
    func_bold_coarse_path = init_dir / "func_bold_coarse.nii.gz"
    func_ref_fast_crop_path = localize_dir / "func_ref_fast_crop.nii.gz"

    ok = False
    out = ""

    # OPTIMIZATION: Check if S3.1 heavy outputs already exist to avoid expensive re-computation
    if func_ref_fast_path.exists() and discovery_seg_path.exists() and func_bold_coarse_path.exists():
         # Load func_ref_fast_data for bbox calculation/clipping limits
         func_ref_fast_img_tmp = nib.load(func_ref_fast_path)
         func_ref_fast_data = func_ref_fast_img_tmp.get_fdata()

         # Re-calculate bbox from discovery seg (fast, robust)
         disc_img = nib.load(discovery_seg_path)
         disc_data = disc_img.get_fdata()

         # Drift gate: reject runs where the segmentation has leaked into the brain.
         gate_ok, gate_msg, gate_info = _check_drift_gate(disc_data, disc_img.affine, policy)

         coords = np.argwhere(disc_data > 0)
         if coords.size > 0:
             pad_xy = 10
             pad_z = 0
             r_min, c_min, s_min = coords.min(axis=0) - [pad_xy, pad_xy, pad_z]
             r_max, c_max, s_max = coords.max(axis=0) + [pad_xy, pad_xy, pad_z]
             r_min, r_max = max(0, r_min), min(func_ref_fast_data.shape[0], r_max)
             c_min, c_max = max(0, c_min), min(func_ref_fast_data.shape[1], c_max)
             s_min, s_max = max(0, s_min), min(func_ref_fast_data.shape[2], s_max)
             crop_bbox = [int(r_min), int(r_max), int(c_min), int(c_max), int(s_min), int(s_max)]
         else:
             crop_bbox = None

         # Reconstruct figure path for dashboard consistency
         figure_prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
         if out_root:
             fig_path = out_root / "derivatives" / "spineprep" / f"sub-{subject}" / (f"ses-{session}" if session else "") / "figures" / f"{figure_prefix}_desc-S3_func_localization.png"
         else:
             fig_path = None

         # Re-render the reportlet so the drift-gate banner reflects the
         # current policy (the cached run may pre-date the gate or its
         # thresholds may have changed). Cheap: it only redraws from the
         # already-on-disk reference and seg.
         drift_gate_meta = {
             "status": "PASS" if gate_ok else "FAIL",
             "reason": gate_msg,
             "info": gate_info,
         }
         if fig_path is not None:
             rendered = _render_s3_1_simple_func_with_mask(
                 func_ref_fast_path,
                 discovery_seg_path,
                 fig_path,
                 policy,
                 crop_box=crop_bbox,
                 drift_gate=drift_gate_meta,
             )
             if rendered is not None:
                 fig_path = rendered

         return {
              "func_ref_fast_path": func_ref_fast_path,
              "func_ref0_path": func_ref0_path,
              "discovery_seg_path": discovery_seg_path,
              "roi_mask_path": roi_mask_path,
              "func_ref_fast_crop_path": func_ref_fast_crop_path,
              "func_bold_coarse_path": func_bold_coarse_path,
              "discovery_seg_crop_path": localize_dir / "func_ref_fast_seg_crop.nii.gz",
              "localization_status": "PASS" if gate_ok else "FAIL",
              "failure_message": None if gate_ok else f"S3.1 brain-contamination check: {gate_msg}",
              "figure_path": fig_path,
              "crop_bbox": crop_bbox,
              "drift_gate_info": gate_info,
         }

    # ELSE: Heavy Computation - Restore Logic

    # Load BOLD data
    bold_img = nib.load(bold_path)
    bold_affine = bold_img.affine
    bold_data = bold_img.get_fdata()

    # Get dummy volume count from policy. This is the ONE place dummies are
    # dropped — S3.2/S3.3 consume func_bold_coarse (already post-drop) and must
    # NOT drop again.
    dummy_volumes = policy.get("dummy", {}).get("drop_count", 4)

    # Drop dummy volumes
    if bold_data.ndim == 4:
        bold_data_dropped = bold_data[:, :, :, dummy_volumes:]
    else:
            bold_data_dropped = bold_data

    # Compute the coarse functional reference (median of all frames;
    # on-disk name `func_ref_fast.nii.gz` kept for the S4-S10 contract).
    if bold_data_dropped.ndim == 4:
        func_ref_fast_data = np.median(bold_data_dropped, axis=3)
    else:
        func_ref_fast_data = bold_data_dropped

    # Save the coarse functional reference
    func_ref_fast_img = nib.Nifti1Image(func_ref_fast_data, bold_affine)
    nib.save(func_ref_fast_img, func_ref_fast_path)

    # Save func_ref0 (first volume)
    if bold_data_dropped.ndim == 4:
        func_ref0_data = bold_data_dropped[:, :, :, 0]
    else:
        func_ref0_data = bold_data_dropped
    func_ref0_img = nib.Nifti1Image(func_ref0_data, bold_affine)
    nib.save(func_ref0_img, func_ref0_path)

    # Real localization: EPISeg (`sct_deepseg sc_epi`, Banerjee et al. 2025) — the
    # EPI-BOLD-specific cord model. It follows the anterior cervical curve
    # where the contrast-agnostic `spinalcord` model (trained on anatomical
    # scans) quits, so it segments the WHOLE imaged cord on the functional
    # reference instead of the upper ~half. Config-driven task with an
    # sc_epi default; the legacy `spinalcord` path keeps `-largest 1`.
    # See .claude/specs/s3-episeg-localization.md.
    seg_task = policy.get("func_localization", {}).get("task", "sc_epi")
    cmd_seg = [
        "sct_deepseg", seg_task,
        "-i", str(func_ref_fast_path),
        "-o", str(discovery_seg_path),
        "-qc", str(work_dir / "qc"),
        "-v", "0",
    ]
    if seg_task == "spinalcord":
        # Legacy contrast-agnostic path: SCT's own largest-component keep.
        cmd_seg += ["-largest", "1"]
    ok, out = _run_command(cmd_seg)

    if ok and discovery_seg_path.exists():
         roi_mask_path = discovery_seg_path
         # EPISeg cleanup: union the on-axis cord fragments across the curve
         # gap and drop off-axis brain specks WITHOUT a naive largest-component
         # keep (which would re-truncate the fragmented cord). No-op for a
         # single clean component. See _cleanup_epi_cordseg.
         if seg_task == "sc_epi":
             try:
                 clean_stats = _cleanup_epi_cordseg(discovery_seg_path, policy)
                 if clean_stats.get("components_dropped"):
                     print(
                         f"S3.1 EPISeg cleanup: kept "
                         f"{clean_stats['components_kept']} on-axis cord "
                         f"component(s), dropped "
                         f"{clean_stats['components_dropped']} off-axis "
                         f"speck(s), {clean_stats['voxels_dropped']} vox"
                     )
             except Exception:
                 pass  # best-effort; raw sc_epi mask still usable
         # Robust caudal completion: deepseg on the coarse full-FOV reference
         # under-segments the lower cord on low-SNR/low-coil-sensitivity runs,
         # so the cord-focused crop derived from this mask cuts off real caudal
         # cord. Union propseg's contiguous caudal cord onto the deepseg mask
         # (caudal-only, lateral-jump-guarded) before it drives the crop.
         try:
             added_caudal = _extend_caudal_via_propseg(
                 func_ref_fast_path, discovery_seg_path, work_dir / "qc", policy
             )
             if added_caudal:
                 print(f"S3.1 caudal completion (propseg): +{len(added_caudal)} "
                       f"slices (z={sorted(added_caudal)})")
         except Exception:
             pass  # strictly additive; never fail localization on completion
         # Second stage: trace the low-SNR caudal tail directly on the reference
         # where neither deepseg nor propseg re-activate. Additive, guarded so
         # it stops at the noise/CSF floor rather than grab CSF/airway/noise.
         try:
             added_trace = _extend_caudal_via_trace(
                 func_ref_fast_path, discovery_seg_path, policy
             )
             if added_trace:
                 print(f"S3.1 caudal completion (trace): +{len(added_trace)} "
                       f"slices (z={sorted(added_trace)})")
         except Exception:
             pass  # strictly additive; never fail localization on completion
    else:
         return {
             "func_ref_fast_path": func_ref_fast_path,
             "func_ref0_path": init_dir / "func_ref0.nii.gz",
             "discovery_seg_path": discovery_seg_path,
             "roi_mask_path": roi_mask_path,
             "func_ref_fast_crop_path": localize_dir / "func_ref_fast_crop.nii.gz",
             "localization_status": "FAIL",
             "failure_message": f"sct_deepseg {seg_task} failed: {out}",
             "figure_path": None,
             "crop_bbox": None,
         }

    # Calculate crop_bbox from discovery segmentation
    try:
        disc_img = nib.load(discovery_seg_path)
        disc_data = disc_img.get_fdata()
        coords = np.argwhere(disc_data > 0)
        if coords.size > 0:
            # ROI = bbox of cord pixels + padding
            pad_xy = 10  # 10 voxels padding around cord (approx 20mm total margin)
            pad_z = 0    # No Z padding
            r_min, c_min, s_min = coords.min(axis=0) - [pad_xy, pad_xy, pad_z]
            r_max, c_max, s_max = coords.max(axis=0) + [pad_xy, pad_xy, pad_z]

            # Clip to image bounds
            r_min, r_max = max(0, r_min), min(func_ref_fast_data.shape[0], r_max)
            c_min, c_max = max(0, c_min), min(func_ref_fast_data.shape[1], c_max)
            s_min, s_max = max(0, s_min), min(func_ref_fast_data.shape[2], s_max)

            crop_bbox = [int(r_min), int(r_max), int(c_min), int(c_max), int(s_min), int(s_max)]
        else:
             crop_bbox = [0, func_ref_fast_data.shape[0], 0, func_ref_fast_data.shape[1], 0, func_ref_fast_data.shape[2]]
    except Exception:
         crop_bbox = [0, func_ref_fast_data.shape[0], 0, func_ref_fast_data.shape[1], 0, func_ref_fast_data.shape[2]]

    # Crop the fast reference for func_ref_fast_crop_path
    func_ref_fast_crop_data = func_ref_fast_data[
        crop_bbox[0] : crop_bbox[1],
        crop_bbox[2] : crop_bbox[3],
        crop_bbox[4] : crop_bbox[5],
    ]
    func_ref_fast_crop_path = localize_dir / "func_ref_fast_crop.nii.gz"
    crop_affine = bold_affine.copy()
    crop_affine[:3, 3] = nib.affines.apply_affine(bold_affine, [crop_bbox[0], crop_bbox[2], crop_bbox[4]])
    nib.save(nib.Nifti1Image(func_ref_fast_crop_data, crop_affine), func_ref_fast_crop_path)


    # Save CROPPED discovery seg (EXACT match for crop_bbox)
    discovery_seg_crop_data = disc_data[
        crop_bbox[0] : crop_bbox[1],
        crop_bbox[2] : crop_bbox[3],
        crop_bbox[4] : crop_bbox[5],
    ]
    discovery_seg_crop_path = localize_dir / "func_ref_fast_seg_crop.nii.gz"
    nib.save(nib.Nifti1Image(discovery_seg_crop_data, crop_affine), discovery_seg_crop_path)

    # Compute func_ref0 from cropped region of 4D BOLD
    if bold_data_dropped.ndim == 4:
        bold_cropped = bold_data_dropped[
            crop_bbox[0] : crop_bbox[1],
            crop_bbox[2] : crop_bbox[3],
            crop_bbox[4] : crop_bbox[5],
            :,
        ]
        func_ref0_data = np.median(bold_cropped, axis=3)

        # Save coarse cropped BOLD (input for S3.3/S3.4)
        func_bold_coarse_path = init_dir / "func_bold_coarse.nii.gz"
        # Fix affine for crop
        new_affine = bold_affine.copy()
        new_affine[:3, 3] = nib.affines.apply_affine(bold_affine, [crop_bbox[0], crop_bbox[2], crop_bbox[4]])
        nib.save(nib.Nifti1Image(bold_cropped, new_affine), func_bold_coarse_path)
    else:
        func_ref0_data = func_ref_fast_crop_data
        func_bold_coarse_path = init_dir / "func_bold_coarse.nii.gz"
        # Handle 3D case
        new_affine = bold_affine.copy()
        new_affine[:3, 3] = nib.affines.apply_affine(bold_affine, [crop_bbox[0], crop_bbox[2], crop_bbox[4]])
        nib.save(nib.Nifti1Image(func_ref_fast_crop_data, new_affine), func_bold_coarse_path)

    # Save func_ref0
    func_ref0_path = init_dir / "func_ref0.nii.gz"
    func_ref0_img = nib.Nifti1Image(func_ref0_data, new_affine)  # Use corrected affine
    nib.save(func_ref0_img, func_ref0_path)

    # Try to use provided context, else extract
    if not (subject and out_root):
        extracted_sub, extracted_ses, extracted_root = _extract_subject_session_from_work_dir(work_dir)
        if not subject:
            subject = extracted_sub
        if not session:
            session = extracted_ses
        if not out_root:
            out_root = extracted_root

    # Determine figures directory (matching S2 structure)
    # Use run_id if available for unique per-run filenames
    if subject and out_root:
        if session:
            figures_dir = out_root / "derivatives" / "spineprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        else:
            figures_dir = out_root / "derivatives" / "spineprep" / f"sub-{subject}" / "figures"
        # Use run_id for unique filenames per functional run
        figure_prefix = run_id if run_id else (f"sub-{subject}_ses-{session}" if session else f"sub-{subject}")
        figure_name = f"{figure_prefix}_desc-S3_func_localization.png"
    else:
        # Fallback for test cases
        figures_dir = work_dir.parent.parent / "derivatives" / "spineprep" / "sub-test" / "ses-none" / "figures"
        figure_name = "test_desc-S3_func_localization.png"

    figures_dir.mkdir(parents=True, exist_ok=True)
    figure_path = figures_dir / figure_name

    # Drift gate verdict, used both to set the run status and to annotate
    # the rendered figure so the dashboard reportlet shows the reason.
    gate_ok, gate_msg, gate_info = _check_drift_gate(disc_data, disc_img.affine, policy)
    drift_gate_meta = {
        "status": "PASS" if gate_ok else "FAIL",
        "reason": gate_msg,
        "info": gate_info,
    }

    # Generate S3.1 Figure immediately
    rendered_path = _render_s3_1_simple_func_with_mask(
        func_ref_fast_path,
        discovery_seg_path,
        figure_path,
        policy,
        crop_box=crop_bbox,
        drift_gate=drift_gate_meta,
    )

    if rendered_path is None:
        return {
            "func_ref_fast_path": func_ref_fast_path,
            "func_ref0_path": func_ref0_path,
            "discovery_seg_path": discovery_seg_path,
            "roi_mask_path": roi_mask_path,
            "func_ref_fast_crop_path": func_ref_fast_crop_path,
            "localization_status": "FAIL",
            "failure_message": "Failed to render S3.1 figure",
            "figure_path": None,
            "crop_bbox": crop_bbox,
        }


    # Drift-gate verdict was already computed above (drift_gate_meta) so the
    # annotated reportlet stays consistent with the run status here.
    result = {
        "func_ref_fast_path": func_ref_fast_path,
        "func_ref0_path": func_ref0_path,
        "discovery_seg_path": discovery_seg_path,
        "roi_mask_path": roi_mask_path,
        "discovery_seg_crop_path": discovery_seg_crop_path,  # Cropped mask for S3.2/S3.3
        "func_ref_fast_crop_path": func_ref_fast_crop_path,
        "func_bold_coarse_path": func_bold_coarse_path,
        "localization_status": "PASS" if gate_ok else "FAIL",
        "failure_message": None if gate_ok else f"S3.1 brain-contamination check: {gate_msg}",
        "figure_path": rendered_path,
        "crop_bbox": crop_bbox,
        "drift_gate_info": gate_info,
    }

    # Check if we should exit after S3.1
    if should_exit_after_subtask("S3.1"):
        return result

    return result
