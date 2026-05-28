"""Public API for S10 ROI timeseries + connectivity + reliability."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import run_S10_roi_timeseries_and_connectivity

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str] = None
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


def _load_qc(out_path: Path, step: str, dataset_key: str) -> dict:
    qc = out_path / "logs" / step / dataset_key / "qc.json"
    if not qc.exists():
        return {}
    try:
        return json.loads(qc.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _norm_sub(subject: str) -> str:
    s = str(subject or "")
    return s[4:] if s.startswith("sub-") else s


def _norm_ses(session: Optional[str]) -> Optional[str]:
    if not session:
        return None
    s = str(session)
    return s[4:] if s.startswith("ses-") else s


def _func_dir_candidates(out_dir: Path, subject: str, session: Optional[str],
                         dataset_key: str) -> list[Path]:
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    return [
        out_dir / "derivatives" / "spinalfmriprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "func",
        out_dir / "derivatives" / "spinalfmriprep"
            / f"sub-{subject}{ses_part}" / "func",
    ]


def _find_first(roots: list[Path], pattern: str) -> Optional[Path]:
    for root in roots:
        if not root.exists():
            continue
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None


def _find_bold(out_dir: Path, subject: str, session: Optional[str],
               run_id: str, dataset_key: str, source: str) -> Optional[Path]:
    name = (f"{run_id}_desc-undistorted_bold.nii.gz"
            if source == "S5_undistorted"
            else f"{run_id}_desc-preproc_bold.nii.gz")
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key), name,
    )


def _find_cord_mask(out_dir: Path, run_id: str) -> Optional[Path]:
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    rel = (Path("runs") / "S3_func_init_and_crop" / run_id
           / "init" / "localize" / "func_ref_fast_seg_crop.nii.gz")
    rel_local = (Path("S3_func_init_and_crop") / run_id
                 / "init" / "localize" / "func_ref_fast_seg_crop.nii.gz")
    for cand in (
        out_dir / "work" / rel_local,
        project_root / "work" / "done" / "reg" / "S3" / rel,
        Path("work") / "done" / "reg" / "S3" / rel,
    ):
        if cand.exists():
            return cand
    return None


def _find_warp_pam50_to_bold(out_dir: Path, subject: str, session: Optional[str],
                             run_id: str, dataset_key: str) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_from-PAM50_to-bold_xfm.nii.gz",
    )


def _find_s7_atlas_dir(out_dir: Path, dataset_key: str, run_id: str) -> Optional[Path]:
    """S7 emits the full PAM50 atlas (post-sct_warp_template) at
    `<S7-chain>/work/S7_template_normalization/<ds>/<run_id>/label/atlas/`.
    S7 used sct_warp_template (correct warp direction); we prefer that
    over re-warping via sct_apply_transfo at S10 time.
    """
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    rel = (Path("work") / "S7_template_normalization" / dataset_key
           / run_id / "label" / "atlas")
    for base in (
        project_root / "work" / "done" / "reg" / "S7",
        Path("work") / "done" / "reg" / "S7",
    ):
        cand = base / rel
        if cand.exists():
            return cand
    return None


def _find_spinal_levels(out_dir: Path, subject: str, session: Optional[str],
                        run_id: str, dataset_key: str) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_desc-PAM50spinallevels.nii.gz",
    )


def _find_confounds(out_dir: Path, subject: str, session: Optional[str],
                    run_id: str, dataset_key: str) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_desc-confounds_timeseries.tsv",
    )


def _bids_root_from_qc(qc: dict) -> Optional[Path]:
    br = qc.get("bids_root")
    return Path(br) if br else None


def _tr_from_bold_json(bids_root: Optional[Path], subject: str,
                      session: Optional[str], run_id: str) -> Optional[float]:
    if not bids_root:
        return None
    subject = _norm_sub(subject); session = _norm_ses(session)
    func_dir = bids_root / f"sub-{subject}"
    if session:
        func_dir = func_dir / f"ses-{session}"
    func_dir = func_dir / "func"
    if not func_dir.exists():
        return None
    hits = sorted(func_dir.glob(f"{run_id}*_bold.json"))
    if not hits:
        return None
    try:
        meta = json.loads(hits[0].read_text())
        tr = meta.get("RepetitionTime")
        return float(tr) if tr is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# run_S10
# ---------------------------------------------------------------------------


def run_S10(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S10_roi_timeseries_and_connectivity.yaml")
    policy: dict = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    # Filter by S9 (or S8, S7) PASS/WARN
    upstream_runs: list[dict] = []
    for step in ("S9_primary_functional_derivatives",
                 "S8_confounds_and_physio_regressors",
                 "S7_template_normalization"):
        qc = _load_qc(out_path, step, dataset_key)
        if qc:
            upstream_runs = [r for r in qc.get("runs", []) if r.get("status") != "FAIL"]
            break
    if not upstream_runs:
        return StepResult("FAIL", f"No PASS/WARN upstream runs for {dataset_key}")

    s2_qc = _load_qc(out_path, "S2_anat_cordref", dataset_key)
    bids_root = _bids_root_from_qc(s2_qc)
    bold_source = str(policy.get("bold_source", "S5_undistorted"))

    results: list[dict] = []
    for u in upstream_runs:
        run_id = u.get("run_id")
        subject = u.get("subject")
        session = u.get("session")

        bold = _find_bold(out_path, subject, session, run_id, dataset_key, bold_source)
        cord_mask = _find_cord_mask(out_path, run_id)
        warp = _find_warp_pam50_to_bold(out_path, subject, session, run_id, dataset_key)
        spinal_levels = _find_spinal_levels(out_path, subject, session, run_id, dataset_key)
        confounds = _find_confounds(out_path, subject, session, run_id, dataset_key)
        tr_s = _tr_from_bold_json(bids_root, subject, session, run_id)
        s7_atlas_dir = _find_s7_atlas_dir(out_path, dataset_key, run_id)

        missing = []
        if bold is None: missing.append("bold")
        if cord_mask is None: missing.append("cord_mask")
        if warp is None: missing.append("from-PAM50_to-bold_xfm")
        if spinal_levels is None: missing.append("PAM50spinallevels")
        if tr_s is None: missing.append("tr")
        if missing:
            results.append({
                "status": "FAIL",
                "step_code": "S10_roi_timeseries_and_connectivity",
                "dataset_key": dataset_key,
                "subject": subject, "session": session, "run_id": run_id,
                "failure_message": f"missing inputs: {missing}",
                "failure_reasons": [f"missing: {m}" for m in missing],
                "metrics": {}, "reportlets": {},
            })
            continue

        bold_run = {"subject": subject, "session": session,
                    "run_id": run_id, "path": f"{run_id}_bold.nii.gz"}
        res = run_S10_roi_timeseries_and_connectivity(
            bold_path=bold, cord_mask_path=cord_mask,
            warp_pam50_to_bold=warp,
            spinal_levels_in_func=spinal_levels,
            confounds_tsv=confounds, tr_s=tr_s,
            bold_run=bold_run, out_dir=out_path,
            work_dir=out_path / "work",
            dataset_key=dataset_key, policy=policy,
            s7_atlas_dir=s7_atlas_dir,
        )
        results.append(res)

    # Per-subject reliability + summary JSON
    subject_summaries = _emit_subject_summaries(
        out_path, dataset_key, results, policy,
    )

    # Aggregate
    n_pass = sum(1 for r in results if r.get("status") == "PASS")
    n_warn = sum(1 for r in results if r.get("status") == "WARN")
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    if results and n_pass + n_warn == len(results) and n_fail == 0:
        top_status = "PASS" if n_warn == 0 else "WARN"
        msg = None if n_warn == 0 else f"{n_warn} runs WARN out of {len(results)}"
    elif n_pass + n_warn > 0:
        top_status = "WARN"
        msg = f"{n_fail} failed, {n_warn} warned out of {len(results)} runs"
    else:
        top_status = "FAIL"
        msg = f"all {len(results)} runs failed" if results else "no runs processed"

    qc_dir = out_path / "logs" / "S10_roi_timeseries_and_connectivity" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "dataset_key": dataset_key,
        "step_code": "S10_roi_timeseries_and_connectivity",
        "status": top_status,
        "failure_message": msg,
        "runs": results,
        "subject_summaries": subject_summaries,
    }, indent=2, default=str))

    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    if top_status == "FAIL":
        return StepResult("FAIL", msg, qc_path=qc_path)
    return StepResult(top_status, msg, qc_path=qc_path)


def _emit_subject_summaries(
    out_path: Path, dataset_key: str, results: list[dict], policy: dict,
) -> list[dict]:
    """Per subject: emit summary.json + (multi-session) reliability.json."""
    import nibabel as nib
    import numpy as np
    import pandas as pd
    from .process import (
        _icc_pooled_across_connections, _icc_per_connection,
        _seed_to_voxel_map, _spatial_dice,
    )

    # Group results by (subject, task) — task derived from run_id
    by_subj: dict[str, list[dict]] = {}
    for r in results:
        if r.get("status") == "FAIL":
            continue
        sub = r.get("subject")
        if not sub:
            continue
        by_subj.setdefault(sub, []).append(r)

    out: list[dict] = []
    for sub, runs in by_subj.items():
        # Subject-level summary path
        sub_dir = (out_path / "derivatives" / "spinalfmriprep" / dataset_key
                   / f"sub-{sub}")
        sub_dir.mkdir(parents=True, exist_ok=True)
        summary_path = sub_dir / f"sub-{sub}_summary.json"

        # Build connectivity matrices per session for hemicord_pearson
        per_session_pearson: dict[str, pd.DataFrame] = {}
        for r in runs:
            ses = r.get("session") or "none"
            cn_tsv_rel = r.get("output_paths", {}).get("hemicord_pearson_connectivity_tsv")
            if not cn_tsv_rel:
                continue
            p = out_path / cn_tsv_rel
            if not p.exists():
                continue
            try:
                mat = pd.read_csv(p, sep="\t", index_col=0)
                per_session_pearson[ses] = mat
            except Exception:
                continue

        summary = {
            "subject": sub,
            "dataset_key": dataset_key,
            "n_runs": len(runs),
            "n_sessions_with_matrix": len(per_session_pearson),
            "sessions": sorted(per_session_pearson.keys()),
        }
        summary_path.write_text(json.dumps(summary, indent=2, default=str))

        rel_cfg = policy.get("reliability", {})
        min_ses = int(rel_cfg.get("min_sessions", 2))
        reliability_json_path: Optional[Path] = None
        icc_good_frac: Optional[float] = None
        if len(per_session_pearson) >= min_ses:
            sessions = sorted(per_session_pearson.keys())
            mats_raw = [per_session_pearson[s] for s in sessions]
            # Restrict to ROIs common to ALL sessions (cord coverage / horn
            # threshold quirks can yield different ROI sets per session).
            common_labels = set(mats_raw[0].columns)
            for m in mats_raw[1:]:
                common_labels &= set(m.columns)
            common = sorted(common_labels)
            if len(common) < 2:
                mats: list = []
            else:
                mats = [m.loc[common, common] for m in mats_raw]
            # Pooled ICC(3,1) across connections
            pooled_icc = _icc_pooled_across_connections(mats) if mats else None
            # Per-connection cross-session agreement (Pearson r as proxy)
            per_conn = _icc_per_connection(mats) if mats else pd.DataFrame()
            # Cicchetti bands
            bands = rel_cfg.get("cicchetti_bands", {})
            poor_max = float(bands.get("poor", 0.4))
            fair_max = float(bands.get("fair", 0.59))
            good_max = float(bands.get("good", 0.74))
            if not per_conn.empty:
                vals = per_conn["icc"].dropna().to_numpy()
                if vals.size:
                    icc_good_frac = float(((vals > fair_max)).mean())
            rel_path = sub_dir / f"sub-{sub}_reliability.json"
            rel_path.write_text(json.dumps({
                "subject": sub, "n_sessions": len(sessions),
                "sessions": sessions,
                "n_common_rois": len(common),
                "pooled_icc31": pooled_icc,
                "per_connection": per_conn.to_dict(orient="records") if not per_conn.empty else [],
                "cicchetti_bands": bands,
                "icc_good_or_excellent_fraction": icc_good_frac,
            }, indent=2, default=str))
            reliability_json_path = rel_path

            # Per-subject reliability reportlet — figures dir at subject root,
            # not per-session. Kaptan 2023 cord rs-fMRI ICC visual standard.
            # Attach the resulting PNG path back into each per-run dict so the
            # flat per-run dashboard surfaces it (same PNG for every run of
            # this subject).
            try:
                fig_dir = sub_dir / "figures"
                fig_dir.mkdir(parents=True, exist_ok=True)
                rel_fig = fig_dir / f"sub-{sub}_desc-S10_reliability_icc.png"
                from .reportlets import render_s10_reliability_icc
                per_conn_records = (per_conn.to_dict(orient="records")
                                    if not per_conn.empty else [])
                rel_status = "PASS"
                if icc_good_frac is not None and icc_good_frac < 0.25:
                    rel_status = "WARN"
                render_s10_reliability_icc(
                    per_conn_records, bands, rel_fig,
                    status=rel_status,
                    n_sessions=len(sessions),
                    pooled_icc=pooled_icc,
                )
                if rel_fig.exists():
                    rel_rel = str(rel_fig.relative_to(out_path))
                    for r in runs:
                        r.setdefault("reportlets", {})["reliability_icc"] = rel_rel
            except Exception as e:
                logger.warning("reliability_icc reportlet failed for sub-%s: %s",
                               sub, e)

        out.append({
            "subject": sub,
            "n_sessions": len(per_session_pearson),
            "reliability_computed": reliability_json_path is not None,
            "icc_good_or_excellent_fraction": icc_good_frac,
            "mean_spatial_dice": None,
            "summary_json_path": str(summary_path.relative_to(out_path)),
            "reliability_json_path": (str(reliability_json_path.relative_to(out_path))
                                     if reliability_json_path else None),
        })
    return out


def check_S10_roi_timeseries_and_connectivity(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required for S10 check")
    out_path = Path(out).resolve()
    qc_dir = out_path / "logs" / "S10_roi_timeseries_and_connectivity"
    if dataset_key:
        qc_path = qc_dir / dataset_key / "qc.json"
    else:
        candidates = list(qc_dir.rglob("qc.json")) if qc_dir.exists() else []
        qc_path = candidates[0] if candidates else None
    if qc_path is None or not qc_path.exists():
        return StepResult("FAIL", f"QC JSON not found: {qc_path or qc_dir}")
    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult("FAIL", f"Failed to read QC JSON: {err}")
    return StepResult(qc.get("status", "UNKNOWN"), qc.get("failure_message"))


def run_S10_roi_timeseries_and_connectivity_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    return run_S10(dataset_key=dataset_key, datasets_local=datasets_local, out=out)


def run_S10_roi_timeseries_and_connectivity_reportlets_only_batch(
    dataset_keys: list[str], out_base: str | Path,
) -> dict[str, StepResult]:
    return {
        k: run_S10_roi_timeseries_and_connectivity_reportlets_only(
            dataset_key=k, out=str(out_base),
        ) for k in dataset_keys
    }
