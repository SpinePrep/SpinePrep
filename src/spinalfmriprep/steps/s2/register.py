"""S2.4: PAM50 template registration."""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Optional

import numpy as np

from .io import _run_command, _write_json


def _run_register_to_template(
    cordref_path: Path,
    seg_path: Path,
    disc_labels_path: Optional[Path],
    rootlets_path: Optional[Path],
    contrast: str,
    work_dir: Path,
) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sct_register_to_template",
        "-i",
        str(cordref_path),
        "-s",
        str(seg_path),
        "-c",
        str(contrast),
        "-ofolder",
        str(work_dir),
    ]
    if disc_labels_path is not None:
        cmd.extend(["-ldisc", str(disc_labels_path)])
    if rootlets_path is not None:
        cmd.extend(["-lrootlet", str(rootlets_path)])
    ok, message = _run_command(cmd)
    if not ok:
        variant = "rootlet" if rootlets_path is not None else "disc"
        return {
            "status": "FAIL",
            "failure_message": f"{variant} registration failed: {message}",
        }

    warp_anat2template = work_dir / "warp_anat2template.nii.gz"
    warp_template2anat = work_dir / "warp_template2anat.nii.gz"
    anat2template = work_dir / "anat2template.nii.gz"
    template2anat = work_dir / "template2anat.nii.gz"
    if not warp_anat2template.exists() or not warp_template2anat.exists():
        return {
            "status": "FAIL",
            "failure_message": "Registration warps not found in output folder.",
        }

    return {
        "status": "PASS",
        "failure_message": None,
        "warp_anat2template": str(warp_anat2template),
        "warp_template2anat": str(warp_template2anat),
        "anat2template": str(anat2template) if anat2template.exists() else None,
        "template2anat": str(template2anat) if template2anat.exists() else None,
    }


def _resolve_pam50_dir() -> Optional[Path]:
    """Resolve PAM50 template directory from environment/SCT conventions."""
    candidates: list[Path] = []
    env_path = os.environ.get("PAM50_PATH")
    if env_path:
        candidates.append(Path(env_path))
    sct_dir = os.environ.get("SCT_DIR")
    if sct_dir:
        candidates.append(Path(sct_dir) / "data" / "PAM50")
    candidates.append(Path.home() / "sct_7.1" / "data" / "PAM50")
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_pam50_cord_mask(pam50_dir: Path) -> Optional[Path]:
    """Find PAM50 cord mask template file."""
    for name in ("PAM50_cord.nii.gz", "PAM50_cordseg.nii.gz", "PAM50_cord_mask.nii.gz"):
        for candidate in (pam50_dir / "template" / name, pam50_dir / name):
            if candidate.exists():
                return candidate
    return None


def compute_pam50_cord_dice(
    native_cord_seg: Path,
    warp_template2anat: Path,
    work_dir: Path,
) -> Optional[float]:
    """3D Dice between native cord_dseg and PAM50_cord warped into the
    native anat geometry. This is S2's step-local registration-quality
    metric (SpinalfMRIprep dev principle §3): a high Dice means the
    PAM50 cord landed exactly where the native cord seg places the
    cord. Low Dice flags a registration that visually looks fine but
    is geometrically off, which the existing PAM50 overlay reportlet
    cannot quantify.

    Returns None on any sub-step failure; never raises.
    """
    try:
        import nibabel as nib  # local import: keeps register.py importable without nib

        pam50_dir = _resolve_pam50_dir()
        if pam50_dir is None:
            return None
        pam50_cord = _find_pam50_cord_mask(pam50_dir)
        if pam50_cord is None or not warp_template2anat.exists():
            return None
        work_dir.mkdir(parents=True, exist_ok=True)
        pam50_in_native = work_dir / "pam50_cord_in_native.nii.gz"
        ok, _ = _run_command([
            "sct_apply_transfo",
            "-i", str(pam50_cord),
            "-d", str(native_cord_seg),
            "-w", str(warp_template2anat),
            "-x", "nn",
            "-o", str(pam50_in_native),
        ])
        if not ok or not pam50_in_native.exists():
            return None
        a = nib.load(native_cord_seg).get_fdata() > 0
        b = nib.load(pam50_in_native).get_fdata() > 0
        if a.shape != b.shape:
            return None
        sa, sb = int(a.sum()), int(b.sum())
        if sa + sb == 0:
            return None
        inter = int((a & b).sum())
        return float(2.0 * inter / (sa + sb))
    except Exception:
        return None


def _ensure_rpi_orientation(image_path: Path, work_dir: Path) -> Optional[Path]:
    """Ensure image is in RPI orientation using sct_image.

    Checks orientation using sct_image -header, and if not RPI, uses sct_image -setorient RPI.
    Returns path to properly oriented image (may be original if already RPI).

    Args:
        image_path: Path to input image
        work_dir: Working directory for output if reorientation needed

    Returns:
        Path to RPI-oriented image, or None if orientation check/set fails
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    # Check current orientation
    ok, output = _run_command(["sct_image", "-i", str(image_path), "-header"])
    if not ok:
        return None

    # Parse orientation from header output (look for "orientation" or "qform" info)
    # sct_image -header typically shows orientation in the output
    # If output contains "RPI" or orientation is already correct, return original
    if "RPI" in output.upper() or "orientation.*RPI" in output:
        return image_path

    # Reorient to RPI
    rpi_path = work_dir / f"{image_path.stem}_rpi{image_path.suffix}"
    ok, _ = _run_command([
        "sct_image",
        "-i", str(image_path),
        "-setorient", "RPI",
        "-o", str(rpi_path),
    ])
    if not ok or not rpi_path.exists():
        return None

    return rpi_path


def _extract_centerline_csv(cord_mask_path: Path, work_dir: Path) -> Optional[Path]:
    """Extract centerline CSV using sct_get_centerline.

    Runs sct_get_centerline -i <cord_mask> -method fitseg and returns path to CSV.
    CSV contains float centerline coordinates in RPI orientation (x, y, z in mm).
    sct_get_centerline automatically outputs CSV with same base name as output image.

    Args:
        cord_mask_path: Path to cord mask image
        work_dir: Working directory for centerline output

    Returns:
        Path to centerline CSV file, or None if extraction fails
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    centerline_img = work_dir / "centerline.nii.gz"
    centerline_csv = work_dir / "centerline.csv"  # sct_get_centerline outputs CSV with same base name

    ok, _ = _run_command([
        "sct_get_centerline",
        "-i", str(cord_mask_path),
        "-method", "fitseg",
        "-o", str(centerline_img),
    ])

    if not ok:
        return None

    # sct_get_centerline outputs CSV automatically with same base name as output image
    # Check primary location first
    if centerline_csv.exists():
        return centerline_csv

    # Also check alternative locations (in case output goes to input directory)
    csv_candidates = [
        centerline_img.parent / f"{centerline_img.stem}.csv",
        cord_mask_path.parent / f"{cord_mask_path.stem}_centerline.csv",
        cord_mask_path.parent / f"{centerline_img.stem}.csv",
    ]

    for csv_path in csv_candidates:
        if csv_path.exists():
            return csv_path

    # If CSV not found, return None (diagnostics will be skipped)
    return None


def _compute_si_mismatch_from_centerlines(subj_csv: Path, pam_csv: Path) -> dict:
    """Compute SI (superior-inferior) mismatch metrics from centerline CSVs.

    Reads centerline CSV files (assumes RPI orientation, columns include z in mm),
    computes z-ranges, coverage, overlap, and SI shift.
    Detects shift type: systematic z-translation vs scaling/nonlinear mismatch.

    Args:
        subj_csv: Path to subject centerline CSV
        pam_csv: Path to PAM50 centerline CSV

    Returns:
        Diagnostic dict with keys:
        - subj_z_min_mm, subj_z_max_mm: Subject z-range in mm
        - pam_z_min_mm, pam_z_max_mm: PAM50 z-range in mm
        - subj_range_mm, pam_range_mm: Range lengths
        - coverage_pct: pam_range_mm / subj_range_mm * 100
        - overlap_min_mm, overlap_max_mm: Overlap z-range
        - overlap_mm: Overlap length
        - overlap_pct: Overlap percentage of subject range
        - si_shift_mm: Mean(z_pam - z_subj) over overlapping portion
        - shift_type: "systematic" if constant, "scaling" if varying, "none" if zero
        - warnings: List of warning messages
    """
    diagnostics: dict = {
        "subj_z_min_mm": None,
        "subj_z_max_mm": None,
        "pam_z_min_mm": None,
        "pam_z_max_mm": None,
        "subj_range_mm": None,
        "pam_range_mm": None,
        "coverage_pct": None,
        "overlap_min_mm": None,
        "overlap_max_mm": None,
        "overlap_mm": None,
        "overlap_pct": None,
        "si_shift_mm": None,
        "shift_type": "unknown",
        "warnings": [],
    }

    try:
        # Read subject centerline CSV
        subj_z_values = _read_centerline_z_values(subj_csv, diagnostics, "Subject")
        if subj_z_values is None:
            return diagnostics

        # Read PAM50 centerline CSV
        pam_z_values = _read_centerline_z_values(pam_csv, diagnostics, "PAM50")
        if pam_z_values is None:
            return diagnostics

        # Compute z-ranges
        subj_z_min = float(min(subj_z_values))
        subj_z_max = float(max(subj_z_values))
        pam_z_min = float(min(pam_z_values))
        pam_z_max = float(max(pam_z_values))

        subj_range = subj_z_max - subj_z_min
        pam_range = pam_z_max - pam_z_min

        diagnostics["subj_z_min_mm"] = subj_z_min
        diagnostics["subj_z_max_mm"] = subj_z_max
        diagnostics["pam_z_min_mm"] = pam_z_min
        diagnostics["pam_z_max_mm"] = pam_z_max
        diagnostics["subj_range_mm"] = subj_range
        diagnostics["pam_range_mm"] = pam_range

        # Compute coverage
        if subj_range > 0:
            diagnostics["coverage_pct"] = (pam_range / subj_range) * 100.0
        else:
            diagnostics["warnings"].append("Subject z-range is zero")

        # Compute overlap
        overlap_min = max(subj_z_min, pam_z_min)
        overlap_max = min(subj_z_max, pam_z_max)
        overlap = max(0.0, overlap_max - overlap_min)

        diagnostics["overlap_min_mm"] = overlap_min
        diagnostics["overlap_max_mm"] = overlap_max
        diagnostics["overlap_mm"] = overlap

        if subj_range > 0:
            diagnostics["overlap_pct"] = (overlap / subj_range) * 100.0

        # Compute SI shift over overlapping portion
        if overlap > 0:
            subj_overlap = [z for z in subj_z_values if overlap_min <= z <= overlap_max]
            pam_overlap = [z for z in pam_z_values if overlap_min <= z <= overlap_max]

            if subj_overlap and pam_overlap:
                subj_overlap_sorted = sorted(subj_overlap)
                pam_overlap_sorted = sorted(pam_overlap)

                min_len = min(len(subj_overlap_sorted), len(pam_overlap_sorted))
                if min_len > 0:
                    shifts = [
                        pam_overlap_sorted[i] - subj_overlap_sorted[i]
                        for i in range(min_len)
                    ]
                    mean_shift = float(np.mean(shifts))
                    diagnostics["si_shift_mm"] = mean_shift

                    if abs(mean_shift) < 0.1:
                        diagnostics["shift_type"] = "none"
                    else:
                        shift_std = float(np.std(shifts))
                        if shift_std < abs(mean_shift) * 0.1:
                            diagnostics["shift_type"] = "systematic"
                        else:
                            diagnostics["shift_type"] = "scaling_or_nonlinear"
                else:
                    diagnostics["warnings"].append("No matching points in overlap region for SI shift computation")
            else:
                diagnostics["warnings"].append("No z values in overlap region")
        else:
            diagnostics["warnings"].append("No overlap between subject and PAM50 z-ranges")
            diagnostics["shift_type"] = "no_overlap"

        # Add warnings for significant issues
        if diagnostics.get("coverage_pct") is not None and diagnostics["coverage_pct"] < 80:
            diagnostics["warnings"].append(f"PAM50 coverage is only {diagnostics['coverage_pct']:.1f}% of subject range")

        if diagnostics.get("overlap_pct") is not None and diagnostics["overlap_pct"] < 50:
            diagnostics["warnings"].append(f"Overlap is only {diagnostics['overlap_pct']:.1f}% of subject range")

        if diagnostics.get("si_shift_mm") is not None and abs(diagnostics["si_shift_mm"]) > 5.0:
            diagnostics["warnings"].append(f"Large SI shift detected: {diagnostics['si_shift_mm']:.2f}mm")

    except Exception as err:  # noqa: BLE001
        diagnostics["warnings"].append(f"Error computing SI mismatch: {err}")

    return diagnostics


def _read_centerline_z_values(csv_path: Path, diagnostics: dict, label: str) -> Optional[list[float]]:
    """Read z values from a centerline CSV file.

    Helper for _compute_si_mismatch_from_centerlines.
    """
    z_values: list[float] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        first_line = next(reader, None)
        if first_line is None:
            diagnostics["warnings"].append(f"{label} CSV is empty")
            return None

        try:
            float(first_line[0])
            # First line is data, no header - format is x,y,z
            z_col_idx = 2
            if len(first_line) > z_col_idx:
                try:
                    z_values.append(float(first_line[z_col_idx]))
                except (ValueError, IndexError):
                    pass
            for row in reader:
                if len(row) > z_col_idx:
                    try:
                        z_values.append(float(row[z_col_idx]))
                    except (ValueError, IndexError):
                        continue
        except ValueError:
            # First line is header - use DictReader
            f.seek(0)
            reader_dict = csv.DictReader(f)
            for row in reader_dict:
                z_key = None
                for key in row.keys():
                    if key.lower() == "z":
                        z_key = key
                        break
                if z_key is None:
                    diagnostics["warnings"].append(f"{label} CSV missing z column: {list(row.keys())}")
                    return None
                try:
                    z_val = float(row[z_key])
                    z_values.append(z_val)
                except (ValueError, KeyError):
                    continue

    if not z_values:
        diagnostics["warnings"].append(f"{label} centerline CSV has no valid z values")
        return None

    return z_values
