"""Public API for S6 func->anat registration: run, check, reportlets-only.

Filter discovery by S5's per-dataset qc.json (chain-aware), matching the
A2/A4/A5 pattern. Aggregate top-level status PASS/WARN/FAIL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import run_S6_func_to_anat_registration

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str] = None
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _load_s5_qc(out_path: Path, dataset_key: str) -> dict:
    qc = out_path / "logs" / "S5_func_distortion_correction" / dataset_key / "qc.json"
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


def _find_funcref(out_dir: Path, subject: str, session: Optional[str], run_id: str) -> Optional[Path]:
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    p = (out_dir / "derivatives" / "spinalfmriprep" / f"sub-{subject}{ses_part}"
         / "func" / f"{run_id}_desc-undistorted_funcref.nii.gz")
    return p if p.exists() else None


def _find_bold(out_dir: Path, subject: str, session: Optional[str], run_id: str) -> Optional[Path]:
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    p = (out_dir / "derivatives" / "spinalfmriprep" / f"sub-{subject}{ses_part}"
         / "func" / f"{run_id}_desc-undistorted_bold.nii.gz")
    return p if p.exists() else None


def _find_funccrop_mask(out_dir: Path, run_id: str) -> Optional[Path]:
    """EPI cord seg in the SAME geometry as the funcref passed to S6.

    Priority:
      1. S5 ``cospine/bold_after_cord_seg.nii.gz`` — sct_deepseg sc_epi
         on the POST-S5 mean BOLD. This matches the post-S5 funcref
         that S6 actually uses.
      2. S3.1 ``func_ref_fast_seg_crop.nii.gz`` — fallback, PRE-S5
         geometry. Only correct if S5 made minimal cord-position
         changes (e.g. SyN-fallback). On topup runs the cord can shift
         5–10 mm in A-P due to physical field correction and this
         seg lands off-cord.

    Audit context: cospine_motorL S6 reportlets showed both cord
    contours offset from the actual cord because S6 was using the
    S3.1 (pre-S5) seg on the post-S5 funcref. Verified with per-Z
    centroid comparison: 1.5–10 mm A-P offset across the cord.
    """
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())

    # Priority 1: S5's post-correction cord seg from sct_deepseg sc_epi.
    s5_rel = (Path("S5_func_distortion_correction") / run_id / "cospine"
              / "bold_after_cord_seg.nii.gz")
    for cand in (
        out_dir / "work" / s5_rel,
        project_root / "work" / "done" / "reg" / "S5" / "work" / s5_rel,
        Path("work") / "done" / "reg" / "S5" / "work" / s5_rel,
    ):
        if cand.exists():
            return cand

    # Priority 2 (fallback): S3.1 pre-S5 cord seg.
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


def _anat_search_roots(subject: str, session: Optional[str],
                       out_path: Path, dataset_key: str) -> list[Path]:
    """S6 reuses the S5 anat-search pattern."""
    subject = _norm_sub(subject); session = _norm_ses(session)
    roots: list[Path] = []
    bases = [out_path]
    s2_done = out_path / "work" / "done" / "reg" / "S2"
    project_done = Path("work") / "done" / "reg" / "S2"
    for cand in (s2_done, project_done, out_path.parent / "done" / "reg" / "S2"):
        if cand.exists():
            try:
                bases.append(cand.resolve())
            except Exception:
                pass

    for base in bases:
        roots.append(base / "derivatives" / "spinalfmriprep" / dataset_key
                     / f"sub-{subject}" / (f"ses-{session}" if session else "")
                     / "anat")
        roots.append(base / "derivatives" / "spinalfmriprep"
                     / f"sub-{subject}" / (f"ses-{session}" if session else "")
                     / "anat")
    return [r for r in roots if r.exists()]


def _find_anat_and_dseg(subject: str, session: Optional[str],
                        out_path: Path, dataset_key: str
                        ) -> tuple[Optional[Path], Optional[Path]]:
    """Find S2 cordref + cord_dseg. Prefer T2star (MEGRE) -> T2w -> T1w
    to match the same-contrast-as-EPI rule (and S2's selection preference).
    Without this, S6 picks the legacy T1w even when S2 produced a T2star
    cordref alongside it (inverted contrast hurts cord registration)."""
    for root in _anat_search_roots(subject, session, out_path, dataset_key):
        for mod in ("T2star", "T2w", "T1w"):
            cordref_hits = sorted(root.glob(f"*_desc-cordref_{mod}.nii.gz"))
            dseg_hits = sorted(root.glob(f"*_desc-cord_dseg_{mod}.nii.gz"))
            if cordref_hits and dseg_hits:
                return cordref_hits[0], dseg_hits[0]
        # Modality-agnostic fallback
        cordref_hits = sorted(root.glob("*_desc-cordref*.nii.gz"))
        dseg_hits = sorted(root.glob("*_desc-cord_dseg*.nii.gz"))
        if cordref_hits and dseg_hits:
            return cordref_hits[0], dseg_hits[0]
    return None, None


# ---------------------------------------------------------------------------
# run_S6: process every PASS/WARN BOLD run from S5
# ---------------------------------------------------------------------------


def run_S6(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S6_func_to_anat_registration.yaml")
    policy: dict = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    s5_qc = _load_s5_qc(out_path, dataset_key)
    s5_runs = [r for r in s5_qc.get("runs", []) if r.get("status") != "FAIL"]
    if not s5_runs:
        return StepResult("FAIL",
                          f"No PASS/WARN S5 runs for dataset {dataset_key}")

    results: list[dict] = []
    for s5_run in s5_runs:
        run_id = s5_run.get("run_id")
        subject = s5_run.get("subject")
        session = s5_run.get("session")
        s5_mode = s5_run.get("distortion_correction_mode") or s5_run.get("mode")

        funcref = _find_funcref(out_path, subject, session, run_id)
        bold = _find_bold(out_path, subject, session, run_id)
        funccrop_mask = _find_funccrop_mask(out_path, run_id)
        anat, anat_dseg = _find_anat_and_dseg(subject, session, out_path, dataset_key)

        missing = []
        if funcref is None: missing.append("funcref")
        if bold is None: missing.append("bold")
        if funccrop_mask is None: missing.append("funccrop_mask")
        if anat is None: missing.append("anat")
        if anat_dseg is None: missing.append("anat_dseg")
        if missing:
            results.append({
                "status": "FAIL",
                "step_code": "S6_func_to_anat_registration",
                "dataset_key": dataset_key,
                "subject": subject, "session": session, "run_id": run_id,
                "failure_message": f"missing inputs: {missing}",
                "failure_reasons": [f"missing: {m}" for m in missing],
                "metrics": {}, "reportlets": {},
                "distortion_correction_mode_inherited": s5_mode,
            })
            continue

        bold_run = {"subject": subject, "session": session,
                    "run_id": run_id, "path": f"{run_id}_bold.nii.gz"}
        res = run_S6_func_to_anat_registration(
            funcref_path=funcref,
            bold_path=bold,
            funccrop_mask_path=funccrop_mask,
            anat_path=anat,
            anat_dseg_path=anat_dseg,
            bold_run=bold_run,
            out_dir=out_path,
            work_dir=out_path / "work",
            dataset_key=dataset_key,
            policy=policy,
            s5_mode=s5_mode,
        )
        results.append(res)

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

    qc_dir = out_path / "logs" / "S6_func_to_anat_registration" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "dataset_key": dataset_key,
        "step_code": "S6_func_to_anat_registration",
        "status": top_status,
        "failure_message": msg,
        "runs": results,
    }, indent=2, default=str))

    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    if top_status == "FAIL":
        return StepResult("FAIL", msg, qc_path=qc_path)
    return StepResult(top_status, msg, qc_path=qc_path)


# ---------------------------------------------------------------------------
# check_S6
# ---------------------------------------------------------------------------


def check_S6_func_to_anat_registration(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required for S6 check")
    out_path = Path(out).resolve()
    qc_dir = out_path / "logs" / "S6_func_to_anat_registration"
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


# ---------------------------------------------------------------------------
# reportlets-only
# ---------------------------------------------------------------------------


def run_S6_func_to_anat_registration_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """v1.0: rerun the full pipeline."""
    if not out:
        return StepResult("FAIL", "--out is required")
    return run_S6(dataset_key=dataset_key, datasets_local=datasets_local, out=out)


def run_S6_func_to_anat_registration_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: str | Path,
) -> dict[str, StepResult]:
    results = {}
    for key in dataset_keys:
        results[key] = run_S6_func_to_anat_registration_reportlets_only(
            dataset_key=key, out=str(out_base),
        )
    return results
