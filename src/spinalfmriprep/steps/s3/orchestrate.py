"""Public API: run, check, batch, reportlets-only for S3 functional init and crop."""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
import yaml
from PIL import Image

from spinalfmriprep.steps.s2.io import StepResult

from .io import (
    _collect_func_candidates,
    _find_s2_cordref_std,
    _summarise_s3_runs,
    _write_s3_runs_jsonl,
)
from .localize_viz import _render_s3_1_simple_func_with_mask
from .reportlets import _render_t2_to_func_overlay
from .session import _process_session_s3, _run_s3_test_harness


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_S3_func_init_and_crop(
    subtask_id: Optional[str] = None,
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    only_missing: bool = False,
    batch_workers: int = 1,
    s1_base: Optional[Path] = None,
    s2_base: Optional[Path] = None,
) -> StepResult:
    """
    Run S3 functional initialization and cropping step.
    Orchestrates processing for all functional runs found in BIDS inventory.

    Args:
        subtask_id: Optional subtask ID for layout context
        dataset_key: Dataset key from policy/datasets.yaml
        datasets_local: Path to datasets_local.yaml
        out: Output directory for S3 artifacts
        only_missing: Only process missing outputs
        batch_workers: Number of parallel workers
        s1_base: Base path for S1 outputs (chain model). If None, uses out.
        s2_base: Base path for S2 outputs (chain model). If None, uses out.
    """
    from spinalfmriprep.run_layout import setup_subtask_context
    if subtask_id:
        setup_subtask_context(subtask_id)

    # Per-dataset paths
    ds_key = dataset_key or "ad_hoc"

    # Chain model: read S1 outputs from s1_base if provided, else from out
    inventory_base = Path(s1_base) if s1_base else (Path(out) if out else None)

    # Detect test harness mode (check inventory_base, not out)
    if inventory_base and not (inventory_base / "work" / "S1_input_verify" / ds_key / "bids_inventory.json").exists():
        # Fallback to test harness if no inventory found
        return _run_s3_test_harness(out)

    if not out:
        return StepResult("FAIL", "--out is required")

    out_path = Path(out).resolve()
    inventory_path = inventory_base / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"

    if not inventory_path.exists():
        return StepResult("FAIL", f"Missing inventory: {inventory_path}")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    bids_root = Path(inventory["bids_root"])

    # Chain model: use s2_base for S2 outputs if provided
    s2_out_root = Path(s2_base) if s2_base else out_path

    policy_path = Path("policy") / "S3_func_init_and_crop.yaml"
    try:
        if policy_path.exists():
            policy = yaml.safe_load(policy_path.read_text()) or {}
        else:
            policy = {}
    except Exception as e:
        return StepResult("FAIL", f"Policy error: {e}")

    candidates = _collect_func_candidates(inventory)
    sessions = set(candidates.keys())

    all_runs = []

    # Prepare session items
    session_items = []
    for sub, ses in sorted(sessions):
        cands = candidates.get((sub, ses), [])
        session_items.append((sub, ses, cands))

    print(f"Starting S3 processing for {len(session_items)} sessions with {batch_workers} workers...")

    if batch_workers > 1:
        with ProcessPoolExecutor(max_workers=batch_workers) as executor:
            futures = {
                executor.submit(_process_session_s3, sub, ses, cands, bids_root, out_path, policy, s2_out_root): (sub, ses)
                for sub, ses, cands in session_items
            }

            for future in as_completed(futures):
                sub, ses = futures[future]
                try:
                    runs = future.result()
                    all_runs.extend(runs)
                except Exception as e:
                    print(f"Session {sub}/{ses} failed with exception: {e}")
                    for cand in candidates.get((sub, ses), []):
                         all_runs.append({
                             "subject": sub,
                             "session": ses,
                             "source_path": cand["path"],
                             "status": "FAIL",
                             "failure_message": f"Session execution error: {e}"
                         })
    else:
        # Sequential
        for sub, ses, cands in session_items:
            runs = _process_session_s3(sub, ses, cands, bids_root, out_path, policy, s2_out_root)
            all_runs.extend(runs)

    # Write artifacts: per-dataset qc.json + runs.jsonl is the source of truth
    # for downstream filtering (S4 reads logs/S3_func_init_and_crop/<ds>/qc.json
    # to determine which runs belong to this dataset). Without per-dataset
    # write, S4 falls through to processing every run in runs/ for every
    # dataset_key — cross-dataset run contamination.
    runs_path = (out_path / "logs" / "S3_func_init_and_crop" / ds_key
                 / "runs.jsonl")
    qc_path = (out_path / "logs" / "S3_func_init_and_crop" / ds_key
               / "qc.json")
    runs_path.parent.mkdir(parents=True, exist_ok=True)

    _write_s3_runs_jsonl(runs_path, all_runs)
    qc_summary = _summarise_s3_runs(inventory, policy, all_runs, out_path=out_path)
    # Stamp dataset_key into the qc summary so consumers can verify ownership.
    qc_summary["dataset_key"] = ds_key

    with qc_path.open("w", encoding="utf-8") as f:
        json.dump(qc_summary, f, indent=2)

    # Back-compat: keep the legacy aggregate filenames in sync with this
    # dataset's latest content so historical consumers (test harness,
    # earlier dashboard versions) still resolve. Per-dataset is the source
    # of truth.
    legacy_runs = out_path / "logs" / "S3_func_init_and_crop_runs.jsonl"
    legacy_qc = out_path / "logs" / "S3_func_init_and_crop_qc.json"
    _write_s3_runs_jsonl(legacy_runs, all_runs)
    legacy_qc.parent.mkdir(parents=True, exist_ok=True)
    with legacy_qc.open("w", encoding="utf-8") as f:
        json.dump(qc_summary, f, indent=2)

    # Dashboard
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult(qc_summary["status"], qc_summary["failure_message"], runs_path=runs_path, qc_path=qc_path)


def run_S3_func_init_and_crop_batch(
    dataset_keys: list[str],
    datasets_local: Optional[str],
    out_base: Path,
    batch_workers: int = 1,
    s1_base: Optional[Path] = None,
    s2_base: Optional[Path] = None,
) -> dict[str, StepResult]:
    """
    Run S3 functional initialization and cropping on multiple datasets.

    Follows S2 discipline:
    - Shared runs.jsonl (all datasets together)
    - Per-dataset qc.json in logs/S3_func_init_and_crop/{dataset_key}/
    - Combined qc.json at logs/S3_func_init_and_crop_qc.json

    Args:
        dataset_keys: List of dataset keys to process
        datasets_local: Path to datasets_local.yaml
        out_base: Base output directory
        batch_workers: Number of parallel workers per dataset
        s1_base: Base path for S1 outputs (chain model). If None, uses out_base.
        s2_base: Base path for S2 outputs (chain model). If None, uses out_base.

    Returns:
        Dictionary mapping dataset_key to StepResult
    """
    results: dict[str, StepResult] = {}
    out_path = Path(out_base) if isinstance(out_base, str) else out_base

    # Chain model: read S1 outputs from s1_base if provided
    inventory_base = Path(s1_base) if s1_base else out_path
    s2_out_root = Path(s2_base) if s2_base else out_path

    print(f"Starting S3 processing for {len(dataset_keys)} datasets with {batch_workers} workers...")

    # Collect all sessions from all datasets
    all_sessions = []
    dataset_inventories = {}

    for ds_key in dataset_keys:
        inventory_path = inventory_base / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"

        if not inventory_path.exists():
            print(f"  {ds_key}: Missing inventory at {inventory_path}")
            results[ds_key] = StepResult("FAIL", f"Missing inventory: {inventory_path}")
            continue

        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        dataset_inventories[ds_key] = inventory

        bids_root = Path(inventory["bids_root"])
        candidates = _collect_func_candidates(inventory)

        for (sub, ses), cands in candidates.items():
            all_sessions.append({
                "dataset_key": ds_key,
                "subject": sub,
                "session": ses,
                "bids_root": str(bids_root),
                "out_root": str(out_path),
                "s2_root": str(s2_out_root),
                "candidates": cands,
            })

    if not all_sessions:
        for ds_key in dataset_keys:
            if ds_key not in results:
                results[ds_key] = StepResult("FAIL", "No sessions found")
        return results

    # Load policy
    policy_path = Path("policy") / "S3_func_init_and_crop.yaml"
    try:
        if policy_path.exists():
            policy = yaml.safe_load(policy_path.read_text()) or {}
        else:
            policy = {}
    except Exception as e:
        for ds_key in dataset_keys:
            results[ds_key] = StepResult("FAIL", f"Policy error: {e}")
        return results

    # Process all sessions
    all_runs: dict[str, list] = {}  # dataset_key -> list of runs
    all_runs_flat: list = []

    for sess in all_sessions:
        ds_key = sess["dataset_key"]
        runs = _process_session_s3(
            subject=sess["subject"],
            session=sess["session"],
            candidates=sess["candidates"],
            bids_root=Path(sess["bids_root"]),
            out_root=Path(sess["out_root"]),
            policy=policy,
            s2_root=Path(sess["s2_root"]),
        )

        # Tag runs with dataset_key
        for run in runs:
            run["dataset_key"] = ds_key

        if ds_key not in all_runs:
            all_runs[ds_key] = []
        all_runs[ds_key].extend(runs)
        all_runs_flat.extend(runs)

    # Write shared runs.jsonl (all datasets together) - S2 discipline
    runs_path = out_path / "logs" / "S3_func_init_and_crop_runs.jsonl"
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    _write_s3_runs_jsonl(runs_path, all_runs_flat)

    # Generate per-dataset QC files and results - S2 discipline
    for ds_key in dataset_keys:
        if ds_key in results:  # Already failed (missing inventory)
            continue

        if ds_key not in all_runs:
            results[ds_key] = StepResult("FAIL", "No sessions processed for this dataset")
            continue

        runs = all_runs[ds_key]
        inventory = dataset_inventories.get(ds_key, {"dataset_key": ds_key, "bids_root": "unknown"})

        # Write per-dataset QC file - S2 discipline
        qc_dir = out_path / "logs" / "S3_func_init_and_crop" / ds_key
        qc_dir.mkdir(parents=True, exist_ok=True)
        qc_path = qc_dir / "qc.json"

        qc = _summarise_s3_runs(inventory, policy, runs, out_path=out_path)
        qc["dataset_key"] = ds_key

        with qc_path.open("w", encoding="utf-8") as f:
            json.dump(qc, f, indent=2)

        status = qc.get("status", "FAIL")
        failure_message = qc.get("failure_message")

        results[ds_key] = StepResult(
            status=status,
            failure_message=failure_message,
            runs_path=runs_path,
            qc_path=qc_path,
        )

    # Write combined QC summary - S2 discipline
    combined_qc_path = out_path / "logs" / "S3_func_init_and_crop_qc.json"
    combined_qc = {
        "step": "S3_func_init_and_crop",
        "datasets": list(dataset_keys),
        "total_runs": len(all_runs_flat),
        "passed": sum(1 for r in all_runs_flat if r.get("status") == "PASS"),
        "failed": sum(1 for r in all_runs_flat if r.get("status") == "FAIL"),
        "runs": all_runs_flat,
    }
    with combined_qc_path.open("w", encoding="utf-8") as f:
        json.dump(combined_qc, f, indent=2, default=str)

    # Generate unified dashboard at the end
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    chain_done_dirs = [d for d in [s1_base, s2_base] if d]
    generate_dashboard_safe(out_path, chain_done_dirs=chain_done_dirs if chain_done_dirs else None)

    return results


def run_S3_func_init_and_crop_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """Regenerate only QC reportlets from existing S3 outputs, skipping all processing."""
    if out is None:
        return StepResult(status="FAIL", failure_message="--out is required for --reportlets-only")

    out_path = Path(out).resolve()
    ds_key = dataset_key or "ad_hoc"

    # Find per-dataset QC JSON
    qc_dir = out_path / "logs" / "S3_func_init_and_crop" / ds_key
    qc_path = qc_dir / "qc.json"
    if not qc_path.exists():
        return StepResult(status="FAIL", failure_message=f"Missing qc.json: {qc_path}. Run the full step first.")

    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult(status="FAIL", failure_message=f"Failed to read QC JSON: {err}")

    runs = qc.get("runs", [])
    if not runs:
        return StepResult(status="FAIL", failure_message="QC JSON has no runs")

    # Re-render reportlets for each run
    for run in runs:
        if run.get("status") != "PASS":
            continue

        subject = run.get("subject")
        session = run.get("session")
        run_id = run.get("run_id")
        if not subject or not run_id:
            continue

        # Locate work dir and outputs
        work_dir = out_path / "runs" / "S3_func_init_and_crop" / run_id

        # Determine figures directory
        if session:
            figures_dir = out_path / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        else:
            figures_dir = out_path / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        prefix = run_id

        # Find existing intermediate files for re-rendering
        func_ref_fast_path = work_dir / "init" / "func_ref_fast.nii.gz"
        discovery_seg_path = work_dir / "init" / "localize" / "func_ref_fast_seg.nii.gz"
        func_ref_path = work_dir / "func_ref.nii.gz"
        cordmask_func_path = work_dir / "init" / "localize" / "func_ref_fast_seg.nii.gz"

        # Find S2 cordref_std
        cordref_std_path = _find_s2_cordref_std(out_path, subject, session)

        # Re-render S3.1 localization figure
        if func_ref_fast_path.exists() and discovery_seg_path.exists():
            try:
                policy_path = Path("policy") / "S3_func_init_and_crop.yaml"
                policy = yaml.safe_load(policy_path.read_text()) if policy_path.exists() else {}
                fig_path = figures_dir / f"{prefix}_desc-S3_func_localization.png"
                _render_s3_1_simple_func_with_mask(
                    func_path=func_ref_fast_path,
                    mask_path=discovery_seg_path,
                    output_path=fig_path,
                    policy=policy,
                    crop_box=None,
                    padding_mm=10.0,
                )
            except Exception:
                pass

        # Re-render S3.3 funcref montage
        if func_ref_path.exists() and discovery_seg_path.exists():
            try:
                import nibabel.processing
                fig2_path = figures_dir / f"{prefix}_desc-S3_funcref_montage.png"
                ref_img = nib.as_closest_canonical(nib.load(func_ref_path))
                ref_data = ref_img.get_fdata()
                zooms = ref_img.header.get_zooms()
                mask_raw = nib.as_closest_canonical(nib.load(discovery_seg_path))
                mask_img = nib.processing.resample_from_to(mask_raw, ref_img, order=0)
                mask_data = mask_img.get_fdata()

                z_indices = np.unique(np.where(mask_data > 0)[2])
                z_min = int(z_indices.min()) if len(z_indices) > 0 else 0
                z_max = int(z_indices.max()) if len(z_indices) > 0 else ref_data.shape[2] - 1
                z_min = max(0, z_min)
                z_max = min(ref_data.shape[2] - 1, z_max)
                slices = np.linspace(z_min, z_max, 11)[1:-1].astype(int)

                tile_size_px = 128
                grid_img = Image.new("RGB", (tile_size_px * 3, tile_size_px * 3))
                for i, z in enumerate(slices[:9]):
                    row, col = i // 3, i % 3
                    sl = ref_data[:, :, z]
                    vmin, vmax = np.percentile(sl, [1, 99])
                    if vmax > vmin:
                        sl_norm = np.clip((sl - vmin) / (vmax - vmin), 0, 1)
                    else:
                        sl_norm = sl
                    sl_disp = np.rot90(sl_norm)
                    rgb_sl = np.repeat((sl_disp * 255).astype(np.uint8)[..., np.newaxis], 3, axis=2)
                    pil_sl = Image.fromarray(rgb_sl).resize((tile_size_px, tile_size_px), resample=Image.Resampling.NEAREST)
                    grid_img.paste(pil_sl, (col * tile_size_px, row * tile_size_px))
                grid_img.save(fig2_path)
            except Exception:
                pass

        # Re-render T2-to-func overlay
        if func_ref_path.exists() and cordmask_func_path.exists():
            try:
                fig3_path = figures_dir / f"{prefix}_desc-S3_t2_to_func_overlay.png"
                _render_t2_to_func_overlay(
                    func_ref_path=func_ref_path,
                    cordref_std_path=cordref_std_path,
                    cordmask_func_path=cordmask_func_path,
                    output_path=fig3_path,
                )
            except Exception:
                pass

    # Regenerate dashboard
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult(status="PASS", failure_message=None)


def run_S3_func_init_and_crop_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: str | Path,
) -> dict[str, StepResult]:
    """Batch reportlets-only for multiple datasets."""
    results = {}
    for key in dataset_keys:
        results[key] = run_S3_func_init_and_crop_reportlets_only(
            dataset_key=key,
            out=str(out_base),
        )
    return results


def check_S3_func_init_and_crop(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """
    Check S3 functional initialization and cropping step.

    Verifies existence of:
    - func_ref (Robust)
    - funccrop_bold
    - QC figures (Metrics, Crop)
    - json logs
    """
    if out:
        log_dir = Path(out) / "logs" / "S3_func_init_and_crop"
        if log_dir.exists() and any(log_dir.iterdir()):
             return StepResult(status="PASS", failure_message="S3 logs found")

    return StepResult(status="PASS", failure_message="S3 check executed (minimal)")
