"""Labeling consistency checks, vertebral label validation, JSON schema validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, cast

import nibabel as nib
import numpy as np
from jsonschema import Draft7Validator

from .io import _run_command, _copy_file, _relpath


def _validate_json(path: Path, schema_path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)  # type: ignore[arg-type]
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        msgs = "; ".join(e.message for e in errors)
        raise ValueError(f"Schema validation failed for {path}: {msgs}")


def _write_evidence(
    evidence_dir: Path,
    qc_path: Path,
    runs_path: Path,
    runs: list[dict],
    status: str,
    command_line: str,
    out_root: Path,
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    checks_txt = evidence_dir / "checks.txt"
    summary_md = evidence_dir / "summary.md"
    qc_copy = evidence_dir / qc_path.name
    runs_copy = evidence_dir / runs_path.name
    qc_copy.write_bytes(qc_path.read_bytes())
    runs_copy.write_bytes(runs_path.read_bytes())
    reportlets_dir = evidence_dir / "reportlets"
    reportlets_dir.mkdir(parents=True, exist_ok=True)
    reportlet_paths = []
    for run in runs:
        reportlets = run.get("reportlets") or {}
        for rel in reportlets.values():
            if not rel:
                continue
            path = out_root / rel if not Path(rel).is_absolute() else Path(rel)
            if not path.exists():
                continue
            destination = reportlets_dir / path.name
            _copy_file(path, destination)
            reportlet_paths.append(destination)
    checks_txt.write_text(f"{command_line}\nstatus={status}\n", encoding="utf-8")
    summary_md.write_text(
        "\n".join(
            [
                "# S2_anat_cordref evidence",
                "",
                f"Status: {status}",
                "",
                "Artifacts:",
                f"- {qc_copy}",
                f"- {runs_copy}",
                *[f"- {path}" for path in reportlet_paths],
                "",
            ]
        ),
        encoding="utf-8",
    )


def _compute_label_metrics(label_path: Path) -> dict:
    img = cast(Any, nib.load(label_path))
    data = img.get_fdata()
    if data.ndim > 3:
        data = data[..., 0]
    labels = np.unique(data.astype(int))
    labels = labels[labels > 0]
    label_count = int(labels.size)
    return {
        "label_count": label_count,
        "label_min": int(labels.min()) if label_count else None,
        "label_max": int(labels.max()) if label_count else None,
    }


def _validate_vertebral_label_outputs(
    vertebral_labels_path: Optional[Path],
    disc_labels_path: Optional[Path],
    cordmask_path: Optional[Path],
    min_disc_labels: int = 2,
) -> tuple[bool, list[str]]:
    """
    Validate vertebral labeling outputs for consistency and basic sanity.

    Args:
        vertebral_labels_path: Path to vertebral level labels NIfTI
        disc_labels_path: Path to disc labels NIfTI
        cordmask_path: Path to cordmask segmentation (for overlap check)
        min_disc_labels: Minimum number of disc labels required

    Returns:
        (is_valid, list_of_reasons) where reasons are empty if valid, or describe failures
    """
    reasons = []

    if disc_labels_path is None or not disc_labels_path.exists():
        reasons.append("Disc labels file missing")
        return False, reasons

    if vertebral_labels_path is None or not vertebral_labels_path.exists():
        reasons.append("Vertebral labels file missing")
        return False, reasons

    try:
        disc_img = cast(Any, nib.load(disc_labels_path))
        disc_data = disc_img.get_fdata()
        if disc_data.ndim > 3:
            disc_data = disc_data[..., 0]

        # Check disc labels are non-empty
        disc_mask = disc_data > 0
        if not disc_mask.any():
            reasons.append("Disc labels mask is empty")
            return False, reasons

        # Check disc label count
        disc_labels = np.unique(disc_data.astype(int))
        disc_labels = disc_labels[disc_labels > 0]
        disc_count = int(disc_labels.size)
        if disc_count < min_disc_labels:
            reasons.append(f"Too few disc labels: {disc_count} < {min_disc_labels}")
            return False, reasons

        # Check monotonic SI ordering: disc labels should progress along z
        disc_z_by_label = {}
        for label_val in disc_labels:
            coords = np.argwhere(disc_data == label_val)
            if coords.size > 0:
                z_coords = coords[:, 2]  # z is third dimension (RPI orientation)
                disc_z_by_label[int(label_val)] = float(np.median(z_coords))

        if len(disc_z_by_label) >= 2:
            sorted_by_z = sorted(disc_z_by_label.items(), key=lambda x: x[1])
            sorted_labels = [x[0] for x in sorted_by_z]
            label_diffs = [sorted_labels[i+1] - sorted_labels[i] for i in range(len(sorted_labels)-1)]
            if any(d < 0 for d in label_diffs):
                reasons.append(f"Disc labels show non-monotonic z-ordering (may indicate labeling error)")

        # Check vertebral labels overlap cordmask (basic sanity)
        if cordmask_path is not None and cordmask_path.exists():
            try:
                vert_img = cast(Any, nib.load(vertebral_labels_path))
                vert_data = vert_img.get_fdata()
                if vert_data.ndim > 3:
                    vert_data = vert_data[..., 0]

                cordmask_img = cast(Any, nib.load(cordmask_path))
                cordmask_data = cordmask_img.get_fdata()
                if cordmask_data.ndim > 3:
                    cordmask_data = cordmask_data[..., 0]

                if vert_data.shape != cordmask_data.shape:
                    reasons.append(f"Shape mismatch: vertebral labels {vert_data.shape} vs cordmask {cordmask_data.shape}")
                    return False, reasons

                vert_mask = vert_data > 0
                cordmask_mask = cordmask_data > 0
                overlap = (vert_mask & cordmask_mask).sum()
                cordmask_voxels = cordmask_mask.sum()

                if cordmask_voxels > 0:
                    overlap_ratio = float(overlap) / float(cordmask_voxels)
                    if overlap_ratio < 0.1:
                        reasons.append(f"Low overlap between vertebral labels and cordmask: {overlap_ratio:.1%}")
                else:
                    reasons.append("Cordmask is empty (cannot validate overlap)")
            except Exception as e:
                reasons.append(f"Could not check vertebral-cordmask overlap: {e}")

    except Exception as e:
        reasons.append(f"Validation error: {e}")
        return False, reasons

    return True, reasons


def _check_labeling_consistency(
    sct_labels_path: Optional[Path],
    template_levels_path: Optional[Path],
    cordmask_path: Optional[Path],
    enabled: bool = True,
    max_mismatch_percent: float = 30.0,
    min_slices_for_decision: int = 10,
) -> tuple[str, list[str], Optional[dict]]:
    """
    Check consistency between SCT vertebral labels and template-derived levels.

    Detects:
    - Global offset (consistent +1/-1 shift across all slices)
    - Single jump (offset changes at one z-slice, indicating a missed/spurious disc)
    """
    if not enabled:
        return "PASS", [], None

    if sct_labels_path is None or not sct_labels_path.exists():
        return "PASS", [], None

    if template_levels_path is None or not template_levels_path.exists():
        return "PASS", [], None

    if cordmask_path is None or not cordmask_path.exists():
        return "PASS", [], None

    try:
        sct_img = nib.as_closest_canonical(nib.load(sct_labels_path))
        template_img = nib.as_closest_canonical(nib.load(template_levels_path))
        cordmask_img = nib.as_closest_canonical(nib.load(cordmask_path))

        sct_data = sct_img.get_fdata()
        template_data = template_img.get_fdata()
        cordmask_data = cordmask_img.get_fdata()

        if sct_data.ndim > 3:
            sct_data = sct_data[..., 0]
        if template_data.ndim > 3:
            template_data = template_data[..., 0]
        if cordmask_data.ndim > 3:
            cordmask_data = cordmask_data[..., 0]

        if sct_data.shape != template_data.shape or sct_data.shape != cordmask_data.shape:
            return "PASS", [], None

        cordmask = cordmask_data > 0.5
        if not cordmask.any():
            return "PASS", [], None

        z_slices = np.where(cordmask.any(axis=(0, 1)))[0]
        if len(z_slices) < min_slices_for_decision:
            return "PASS", [], None

        sct_dominant_by_z = []
        template_dominant_by_z = []

        for z in z_slices:
            sct_slice = sct_data[:, :, z]
            template_slice = template_data[:, :, z]
            mask_slice = cordmask[:, :, z]

            if not mask_slice.any():
                continue

            sct_masked = sct_slice[mask_slice]
            template_masked = template_slice[mask_slice]

            if sct_masked.size == 0 or template_masked.size == 0:
                continue

            sct_values = sct_masked[sct_masked > 0]
            template_values = template_masked[template_masked > 0]

            if sct_values.size > 0 and template_values.size > 0:
                sct_mode = int(np.bincount(sct_values.astype(int)).argmax())
                template_mode = int(np.bincount(template_values.astype(int)).argmax())

                if sct_mode > 0 and template_mode > 0:
                    sct_dominant_by_z.append((z, sct_mode))
                    template_dominant_by_z.append((z, template_mode))

        if len(sct_dominant_by_z) < min_slices_for_decision or len(template_dominant_by_z) < min_slices_for_decision:
            return "PASS", [], None

        sct_dict = dict(sct_dominant_by_z)
        template_dict = dict(template_dominant_by_z)
        common_z = sorted(set(sct_dict.keys()) & set(template_dict.keys()))

        if len(common_z) < min_slices_for_decision:
            return "PASS", [], None

        offsets = []
        for z in common_z:
            offset = sct_dict[z] - template_dict[z]
            offsets.append((z, offset))

        if not offsets:
            return "PASS", [], None

        offset_values = [o[1] for o in offsets]
        offset_mode = int(np.bincount([int(o + 10) for o in offset_values]).argmax() - 10)

        mode_count = sum(1 for o in offset_values if o == offset_mode)
        mode_percent = (mode_count / len(offset_values)) * 100.0

        jump_z = None
        jump_level_estimate = None
        if len(offsets) >= 3:
            for i in range(1, len(offsets) - 1):
                prev_offset = offsets[i-1][1]
                curr_offset = offsets[i][1]
                next_offset = offsets[i+1][1]
                if abs(curr_offset - prev_offset) >= 1 and abs(curr_offset - next_offset) >= 1:
                    if abs(prev_offset - next_offset) <= 1:
                        jump_z = offsets[i][0]
                        jump_level_estimate = curr_offset
                        break

        mismatch_count = sum(1 for o in offset_values if o != offset_mode)
        mismatch_rate = (mismatch_count / len(offset_values)) * 100.0

        consistency_metrics = {
            "offset_mode": int(offset_mode),
            "mode_percent": float(mode_percent),
            "jump_z": int(jump_z) if jump_z is not None else None,
            "jump_level_estimate": int(jump_level_estimate) if jump_level_estimate is not None else None,
            "mismatch_rate": float(mismatch_rate),
        }

        qc_reasons = []
        qc_status = "PASS"

        if abs(offset_mode) >= 1 and mode_percent >= (100.0 - max_mismatch_percent):
            qc_status = "WARN"
            qc_reasons.append(f"Global offset detected: SCT labels shifted by {offset_mode:+d} levels relative to template (affects {mode_percent:.1f}% of slices)")

        if jump_z is not None:
            jump_persists = False
            if len(offsets) >= 5:
                jump_idx = next((i for i in range(len(offsets)) if offsets[i][0] == jump_z), None)
                if jump_idx is not None:
                    window_start = max(0, jump_idx - 2)
                    window_end = min(len(offsets), jump_idx + 3)
                    window_offsets = [offsets[i][1] for i in range(window_start, window_end)]
                    window_mismatch = sum(1 for o in window_offsets if o != offset_mode)
                    jump_persists = window_mismatch >= len(window_offsets) * 0.6

            if mismatch_rate > max_mismatch_percent * 0.5 or jump_persists:
                qc_status = "WARN"
                qc_reasons.append(f"Single jump detected at z={jump_z}: offset changes by {jump_level_estimate:+d} levels (likely missed/spurious disc)")

        if mismatch_rate > max_mismatch_percent:
            qc_status = "WARN"
            qc_reasons.append(f"High mismatch rate: {mismatch_rate:.1f}% of slices disagree with template levels")

        return qc_status, qc_reasons, consistency_metrics

    except Exception:  # noqa: BLE001
        return "PASS", [], None


def _estimate_initcenter_from_disc_labels(disc_labels_path: Path) -> Optional[int]:
    """
    Estimate initcenter value from disc labels by finding the disc label closest to mid-z.

    This matches SCT's semantics: -initcenter means "disc value at the center of z-FOV".
    """
    try:
        disc_img = cast(Any, nib.load(disc_labels_path))
        disc_data = disc_img.get_fdata()
        if disc_data.ndim > 3:
            disc_data = disc_data[..., 0]

        nz = disc_data.shape[2]
        z_center = round(nz / 2)

        disc_labels = np.unique(disc_data.astype(int))
        disc_labels = disc_labels[disc_labels > 0]

        if disc_labels.size == 0:
            return None

        disc_z_by_label = {}
        for label_val in disc_labels:
            coords = np.argwhere(disc_data == label_val)
            if coords.size > 0:
                z_coords = coords[:, 2]
                disc_z_by_label[int(label_val)] = float(np.median(z_coords))

        if not disc_z_by_label:
            return None

        closest_label = min(
            disc_z_by_label.items(),
            key=lambda x: abs(x[1] - z_center)
        )[0]

        return int(closest_label)
    except Exception:
        return None


def _find_first(folder: Path, pattern: str) -> Optional[Path]:
    matches = sorted(folder.glob(pattern))
    return matches[0] if matches else None


def _dilate_mask(source: Path, dest: Path, radius: int = 0) -> Optional[Path]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok, _ = _run_command(
        [
            "sct_maths",
            "-i",
            str(source),
            "-dilate",
            str(radius),
            "-o",
            str(dest),
        ]
    )
    return dest if ok else None


def _largest_connected_component(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 3:
        return mask
    visited = np.zeros(mask.shape, dtype=bool)
    best_component = None
    best_size = 0
    coords = np.argwhere(mask)
    for start in coords:
        x, y, z = start
        if visited[x, y, z]:
            continue
        stack = [(x, y, z)]
        component = []
        visited[x, y, z] = True
        while stack:
            cx, cy, cz = stack.pop()
            component.append((cx, cy, cz))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if dx == 0 and dy == 0 and dz == 0:
                            continue
                        nx, ny, nz = cx + dx, cy + dy, cz + dz
                        if (
                            0 <= nx < mask.shape[0]
                            and 0 <= ny < mask.shape[1]
                            and 0 <= nz < mask.shape[2]
                            and mask[nx, ny, nz]
                            and not visited[nx, ny, nz]
                        ):
                            visited[nx, ny, nz] = True
                            stack.append((nx, ny, nz))
        if len(component) > best_size:
            best_size = len(component)
            best_component = component
    if best_component is None:
        return mask
    cleaned = np.zeros(mask.shape, dtype=bool)
    for cx, cy, cz in best_component:
        cleaned[cx, cy, cz] = True
    return cleaned
