"""S4 orchestration: top-level entry, checking, and reportlet-only regeneration.

Contains ``run_S4`` (the top-level entry point that discovers runs and
dispatches ``run_S4_func_motion_correction``), validation helpers, and
reportlet-only regeneration utilities.
"""

import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Any, Dict

import numpy as np
import pandas as pd
import nibabel as nib
import yaml

from spinalfmriprep.lib import moco

from .process import run_S4_func_motion_correction

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str] = None


# ---------------------------------------------------------------------------
# run_S4 -- top-level entry point
# ---------------------------------------------------------------------------

def run_S4(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    """
    High-level entry point for S4 motion correction.
    Discovers runs from S3 output directory and orchestrates processing.
    """
    if not out:
        return StepResult("FAIL", "--out is required")

    out_path = Path(out).resolve()

    # Load Policy
    policy_path = Path("policy/S4_func_motion_correction.yaml")
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text())
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")
    else:
        policy = {}

    # Discover runs from S3 output directory
    s3_runs_dir = out_path / "runs" / "S3_func_init_and_crop"
    if not s3_runs_dir.exists():
        return StepResult("FAIL", f"Missing S3 runs directory: {s3_runs_dir}")

    # CRITICAL: filter by dataset_key. S3's per-dataset qc.json is the truth
    # for "this run belongs to dataset X". Without this filter, S4 reprocesses
    # every run in the (chain-merged) S3 runs directory for every dataset
    # it is invoked for, inflating the dashboard count and tagging the same
    # physical run under multiple dataset_keys.
    s3_qc_path = (
        out_path / "logs" / "S3_func_init_and_crop" / dataset_key / "qc.json"
    )
    allowed_run_ids: Optional[set[str]] = None
    if s3_qc_path.exists():
        try:
            s3_qc = json.loads(s3_qc_path.read_text(encoding="utf-8"))
            allowed_run_ids = {
                r["run_id"]
                for r in s3_qc.get("runs", [])
                # Only process runs that survived S3 (PASS or WARN). FAIL
                # means S3 dropped them (e.g. via the S3.1 drift gate).
                if r.get("run_id") and r.get("status") != "FAIL"
            }
            logger.info(
                f"S4 dataset_key={dataset_key}: S3 qc.json restricts to "
                f"{len(allowed_run_ids)} run_ids"
            )
        except Exception as e:
            logger.warning(f"Could not read S3 qc.json at {s3_qc_path}: {e}")

    # Collect run directories: must exist, must have funccrop_bold, and (when
    # an S3-qc restriction exists) must belong to this dataset.
    runs_to_process = []
    for run_dir in sorted(s3_runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        if allowed_run_ids is not None and run_dir.name not in allowed_run_ids:
            continue
        bold_path = run_dir / "funccrop_bold.nii.gz"
        if bold_path.exists():
            runs_to_process.append(run_dir)
        else:
            logger.warning(f"Skipping {run_dir.name}: missing funccrop_bold.nii.gz")

    logger.info(f"Found {len(runs_to_process)} S3 runs to process for S4")

    if not runs_to_process:
        return StepResult("FAIL", "No valid S3 runs found with funccrop_bold.nii.gz")

    # Run in parallel
    results = []
    with ProcessPoolExecutor(max_workers=batch_workers) as executor:
        futures = {
            executor.submit(
                run_S4_func_motion_correction,
                s3_run_dir=run_dir,
                policy=policy,
                out_dir=out_path,
                work_dir=out_path / "work",
                dataset_key=dataset_key,
            ): run_dir for run_dir in runs_to_process
        }

        for future in as_completed(futures):
            run_dir = futures[future]
            try:
                res = future.result()
                results.append(res)
                logger.info(f"S4 completed for {run_dir.name}: {res.get('status', 'UNKNOWN')}")
            except Exception as e:
                import traceback
                logger.error(f"S4 failed for {run_dir.name}: {e}\n{traceback.format_exc()}")
                results.append({"status": "FAIL", "reason": str(e), "failure_reasons": [str(e)]})

    # Save aggregated QC
    qc_dir = out_path / "logs" / "S4_func_motion_correction" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"

    # Aggregate top-level status from per-run results so consumers
    # (mark_done, dashboard step cards, downstream chain) don't see
    # UNKNOWN. Conventions match S3:
    #   PASS  all runs PASS
    #   WARN  some FAIL or WARN but at least one PASS - partial success
    #   FAIL  no PASS, or no runs at all
    n_pass = sum(1 for r in results if r.get("status") == "PASS")
    n_warn = sum(1 for r in results if r.get("status") == "WARN")
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    if results and n_pass == len(results):
        top_status = "PASS"
        top_msg = None
    elif n_pass > 0:
        top_status = "WARN"
        parts = []
        if n_fail: parts.append(f"{n_fail} failed")
        if n_warn: parts.append(f"{n_warn} warned")
        top_msg = ", ".join(parts) + f" out of {len(results)} runs"
    else:
        top_status = "FAIL"
        top_msg = f"all {len(results)} runs failed" if results else "no runs processed"

    aggregated_qc = {
        "dataset_key": dataset_key,
        "step_code": "S4_func_motion_correction",
        "status": top_status,
        "failure_message": top_msg,
        "runs": results,
    }

    with open(qc_path, "w") as f:
        json.dump(aggregated_qc, f, indent=2)

    # Return value mirrors the top-level status so the orchestrator's caller
    # sees the same verdict that landed in qc.json.
    if top_status == "FAIL":
        return StepResult("FAIL", top_msg)

    # Build dashboard (matches S1/S2/S3 pattern)
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult("PASS")


# ---------------------------------------------------------------------------
# check_S4_func_motion_correction -- validate existing outputs
# ---------------------------------------------------------------------------

def check_S4_func_motion_correction(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """
    Validate S4 motion correction outputs.

    Checks:
    - QC JSON exists and is valid
    - Per-run derivative files exist (mocoref BOLD, moco params, tSNR)
    - Per-run reportlets exist (motion traces, tSNR comparison, DVARS, GIF)
    - Aggregated status from QC JSON
    """
    if not out:
        return StepResult(status="FAIL", failure_message="--out is required for S4 check")

    out_path = Path(out).resolve()

    # --- 1. Check QC JSON ---
    if dataset_key:
        qc_dir = out_path / "logs" / "S4_func_motion_correction" / dataset_key
    else:
        qc_dir = out_path / "logs" / "S4_func_motion_correction"

    qc_path = None
    if dataset_key:
        qc_path = qc_dir / "qc.json"
    else:
        # Find any qc.json under S4 logs
        if qc_dir.exists():
            candidates = list(qc_dir.rglob("qc.json"))
            if candidates:
                qc_path = candidates[0]

    if qc_path is None or not qc_path.exists():
        return StepResult(
            status="FAIL",
            failure_message=f"QC JSON not found: {qc_path or qc_dir / '*/qc.json'}",
        )

    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult(status="FAIL", failure_message=f"Failed to read QC JSON: {err}")

    if dataset_key and qc.get("dataset_key") != dataset_key:
        return StepResult(
            status="FAIL",
            failure_message=f"QC dataset_key mismatch: expected {dataset_key}, got {qc.get('dataset_key')}",
        )

    # --- 2. Validate per-run outputs ---
    runs = qc.get("runs", [])
    if not runs:
        return StepResult(status="FAIL", failure_message="QC JSON has no runs")

    missing_outputs: List[str] = []
    missing_reportlets: List[str] = []

    for run in runs:
        run_label = f"{run.get('subject', '?')}/{run.get('session', '?')}/{run.get('run_id', '?')}"

        # Check reportlets
        reportlets = run.get("reportlets", {})
        required_reportlets = [
            "S4_motion_traces",
            "S4_tsnr_comparison",
            "S4_dvars_plot",
        ]
        for key in required_reportlets:
            rel = reportlets.get(key)
            if not rel:
                missing_reportlets.append(f"{key} missing for {run_label}")
                continue
            path = Path(rel) if Path(rel).is_absolute() else out_path / rel
            if not path.exists() or path.stat().st_size == 0:
                missing_reportlets.append(f"{key}: {path}")

        # Check metrics exist
        metrics = run.get("metrics")
        if not metrics:
            missing_outputs.append(f"metrics missing for {run_label}")

    issues: List[str] = []
    if missing_outputs:
        issues.append(f"Missing outputs: {'; '.join(missing_outputs)}")
    if missing_reportlets:
        issues.append(f"Missing reportlets: {'; '.join(missing_reportlets)}")

    if issues:
        return StepResult(status="FAIL", failure_message=" | ".join(issues))

    # --- 3. Check aggregate status ---
    failed_runs = [r for r in runs if r.get("status") == "FAIL"]
    warn_runs = [r for r in runs if r.get("status") == "WARN"]

    if failed_runs:
        return StepResult(
            status="FAIL",
            failure_message=f"{len(failed_runs)}/{len(runs)} runs FAIL",
        )

    if warn_runs:
        return StepResult(
            status="WARN",
            failure_message=f"{len(warn_runs)}/{len(runs)} runs WARN",
        )

    return StepResult(status="PASS", failure_message=None)


# ---------------------------------------------------------------------------
# Reportlets-only regeneration
# ---------------------------------------------------------------------------

def run_S4_func_motion_correction_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """Regenerate only QC reportlets from existing S4 outputs, skipping all processing."""
    if not out:
        return StepResult(status="FAIL", failure_message="--out is required for --reportlets-only")

    out_path = Path(out).resolve()
    ds_key = dataset_key or "ad_hoc"

    # Load QC JSON
    qc_path = out_path / "logs" / "S4_func_motion_correction" / ds_key / "qc.json"
    if not qc_path.exists():
        return StepResult(status="FAIL", failure_message=f"Missing qc.json: {qc_path}. Run the full step first.")

    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult(status="FAIL", failure_message=f"Failed to read QC JSON: {err}")

    # Load policy
    policy_path = Path("policy/S4_func_motion_correction.yaml")
    if policy_path.exists():
        policy = yaml.safe_load(policy_path.read_text())
    else:
        return StepResult(status="FAIL", failure_message="Missing policy file")

    from spinalfmriprep.lib import viz_s4

    runs = qc.get("runs", [])
    for run in runs:
        subject = run.get("subject")
        session = run.get("session")
        run_id = run.get("run_id")
        if not subject or not run_id:
            continue

        # Locate work dir. run_id is the full S3 run-dir name (qc.json schema
        # since the run_id-mismatch fix), e.g. "sub-02_task-motor_run-01".
        s4_work_dir = out_path / "work" / "S4_func_motion_correction" / run_id

        # Prefix used for figure / param filenames is the same as run_id by
        # convention (matches S3 and the work-dir name).
        prefix = run_id
        if session:
            figures_dir = out_path / "derivatives" / "spinalfmriprep" / subject / session / "figures"
            func_dir = out_path / "derivatives" / "spinalfmriprep" / subject / session / "func"
        else:
            figures_dir = out_path / "derivatives" / "spinalfmriprep" / subject / "figures"
            func_dir = out_path / "derivatives" / "spinalfmriprep" / subject / "func"
        figures_dir.mkdir(parents=True, exist_ok=True)

        # Load persisted intermediates
        tsnr_before_path = s4_work_dir / "tsnr_before.nii.gz"
        tsnr_after_path = s4_work_dir / "tsnr_after.nii.gz"
        params_path = func_dir / f"{prefix}_moco_params.tsv"

        # Find cord mask
        mask_path = None
        mask_candidates = list(s4_work_dir.glob("*seg*.nii.gz")) + list(s4_work_dir.glob("*mask*.nii.gz"))
        if mask_candidates:
            mask_path = mask_candidates[0]

        fd_threshold = policy.get("qc_thresholds", {}).get("fd_threshold_mm", 0.5)

        # 1. Motion traces
        if params_path.exists():
            try:
                params_df = pd.read_csv(params_path, sep="\t")
                viz_s4.render_motion_traces(
                    params_df,
                    fd_threshold=fd_threshold,
                    output_path=figures_dir / f"{prefix}_desc-S4_motion_traces.png",
                    figsize=tuple(policy.get("qc", {}).get("motion_traces", {}).get("figsize", [10, 4])),
                    dpi=policy.get("qc", {}).get("motion_traces", {}).get("dpi", 100),
                    colors=policy.get("qc", {}).get("motion_traces", {}).get("colors", {}),
                )
            except Exception:
                pass

        # 2. tSNR comparison
        if tsnr_before_path.exists() and tsnr_after_path.exists():
            try:
                tsnr_before_img = nib.load(tsnr_before_path)
                tsnr_before_data = tsnr_before_img.get_fdata()
                tsnr_after_data = nib.load(tsnr_after_path).get_fdata()
                zooms = tsnr_before_img.header.get_zooms()[:3]
                mask_data = nib.load(mask_path).get_fdata() > 0 if mask_path and mask_path.exists() else tsnr_before_data > 0
                viz_s4.render_tsnr_comparison(
                    tsnr_before_data,
                    tsnr_after_data,
                    mask_data,
                    zooms=zooms,
                    output_path=figures_dir / f"{prefix}_desc-S4_tsnr_comparison.png",
                    colormap=policy.get("qc", {}).get("tsnr_comparison", {}).get("colormap", "viridis"),
                )
            except Exception:
                pass

        # 3. DVARS plot
        if params_path.exists():
            try:
                moco_bold_path = func_dir / f"{prefix}_desc-mocoref_bold.nii.gz"
                if moco_bold_path.exists() and mask_path and mask_path.exists():
                    mask_data = nib.load(mask_path).get_fdata() > 0
                    bold_data = nib.load(moco_bold_path).get_fdata()
                    dvars = moco.compute_dvars(bold_data, mask_data)
                    threshold = np.percentile(dvars, 75) + 1.5 * (np.percentile(dvars, 75) - np.percentile(dvars, 25))
                    viz_s4.render_dvars_plot(
                        dvars,
                        threshold=threshold,
                        output_path=figures_dir / f"{prefix}_desc-S4_dvars_plot.png",
                    )
            except Exception:
                pass

    # Regenerate dashboard
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult(status="PASS", failure_message=None)


def run_S4_func_motion_correction_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: str | Path,
) -> dict[str, StepResult]:
    """Batch reportlets-only for multiple datasets."""
    results = {}
    for key in dataset_keys:
        results[key] = run_S4_func_motion_correction_reportlets_only(
            dataset_key=key,
            out=str(out_base),
        )
    return results
