"""Public API for S7 template normalization: run, check, reportlets-only.

Filter discovery by S6's per-dataset qc.json (chain-aware). Aggregate
top-level status PASS/WARN/FAIL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import run_S7_template_normalization

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


def _load_s6_qc(out_path: Path, dataset_key: str) -> dict:
    qc = out_path / "logs" / "S6_func_to_anat_registration" / dataset_key / "qc.json"
    if not qc.exists():
        return {}
    try:
        return json.loads(qc.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_s2_qc(out_path: Path, dataset_key: str) -> dict:
    qc = out_path / "logs" / "S2_anat_cordref" / dataset_key / "qc.json"
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


def _func_dir_candidates(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
) -> list[Path]:
    """Both keyed and legacy (unkeyed) func/ paths. S5/S6 currently write
    to the legacy aggregate path; S2 writes to the keyed path. We try
    keyed first so a future migration is automatic."""
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    return [
        out_dir / "derivatives" / "spinalfmriprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "func",
        out_dir / "derivatives" / "spinalfmriprep"
            / f"sub-{subject}{ses_part}" / "func",
    ]


def _xfm_dir_candidates(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
) -> list[Path]:
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    return [
        out_dir / "derivatives" / "spinalfmriprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "xfm",
        out_dir / "derivatives" / "spinalfmriprep"
            / f"sub-{subject}{ses_part}" / "xfm",
    ]


def _anat_dir_candidates(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
) -> list[Path]:
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    return [
        out_dir / "derivatives" / "spinalfmriprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "anat",
        out_dir / "derivatives" / "spinalfmriprep"
            / f"sub-{subject}{ses_part}" / "anat",
    ]


def _find_first(roots: list[Path], pattern: str) -> Optional[Path]:
    for root in roots:
        if not root.exists():
            continue
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None


def _find_funcref(out_dir: Path, subject: str, session: Optional[str],
                  run_id: str, dataset_key: str) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_desc-undistorted_funcref.nii.gz",
    )


def _find_s6_warps(
    out_dir: Path, subject: str, session: Optional[str],
    run_id: str, dataset_key: str,
) -> tuple[Optional[Path], Optional[Path]]:
    fwd = _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_from-bold_to-anat_xfm.nii.gz",
    )
    inv = _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_from-anat_to-bold_xfm.nii.gz",
    )
    return fwd, inv


def _find_s2_pam50_warps(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
    s2_qc: Optional[dict] = None,
) -> tuple[Optional[Path], Optional[Path]]:
    """S2 anat<->PAM50 warps. Lookup priority:

      1. Keyed derivatives xfm/ — `<ds>/sub-XX/[ses-YY]/xfm/`.
      2. S2 qc.json `registration.<selected>.warp_{anat2template,template2anat}`
         absolute paths in S2's work tree. This is needed because S2 only
         writes the keyed derivative copy for the most recently re-run
         dataset (legacy `sub-XX/xfm/` is shared across datasets and gets
         overwritten by the last S2 run, so we cannot fall back to it).

    Filenames use "cordref" not "anat" because S2 registers the cropped
    cordref image to PAM50.
    """
    # 1. Keyed derivatives path (preferred)
    anat_to_PAM50 = _find_first(
        _xfm_dir_candidates(out_dir, subject, session, dataset_key)[:1],
        "*_from-cordref_to-PAM50_warp.nii.gz",
    )
    PAM50_to_anat = _find_first(
        _xfm_dir_candidates(out_dir, subject, session, dataset_key)[:1],
        "*_from-PAM50_to-cordref_warp.nii.gz",
    )
    if anat_to_PAM50 and PAM50_to_anat:
        return anat_to_PAM50, PAM50_to_anat

    # 2. Fall back to S2 qc.json absolute paths in work tree
    if s2_qc is None:
        return None, None
    subj = _norm_sub(subject); ses = _norm_ses(session)
    for r in s2_qc.get("runs", []):
        rs = _norm_sub(r.get("subject", ""))
        rses = _norm_ses(r.get("session"))
        if rs != subj or rses != ses:
            continue
        reg = r.get("registration") or {}
        selected = reg.get("selected")
        if not selected:
            continue
        chosen = reg.get(selected) or {}
        a2p = chosen.get("warp_anat2template")
        p2a = chosen.get("warp_template2anat")
        if a2p and p2a and Path(a2p).exists() and Path(p2a).exists():
            return Path(a2p), Path(p2a)
    return None, None


def _find_subject_vertebral_labels(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
) -> Optional[Path]:
    """S2 vertebral labels — optional, used for label-offset QC.
    Prefer modality matching S6's chosen anat: T2star -> T2w -> T1w."""
    for mod in ("T2star", "T2w", "T1w"):
        p = _find_first(
            _anat_dir_candidates(out_dir, subject, session, dataset_key),
            f"*_desc-vertebral_labels_{mod}.nii.gz",
        )
        if p is not None:
            return p
    return _find_first(
        _anat_dir_candidates(out_dir, subject, session, dataset_key),
        "*_desc-vertebral_labels*.nii.gz",
    )


def _find_func_cord_seg(out_dir: Path, run_id: str) -> Optional[Path]:
    """Cord seg in BOLD geometry — S3.1 output (matches S6's _find_funccrop_mask)."""
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


def _s2_init_method_from_qc(s2_qc: dict, subject: str, session: Optional[str]
                            ) -> Optional[str]:
    """Read which init (rootlet|disc|auto) S2 used for this subject."""
    subj = _norm_sub(subject); ses = _norm_ses(session)
    for r in s2_qc.get("runs", []):
        rs = _norm_sub(r.get("subject", ""))
        rses = _norm_ses(r.get("session"))
        if rs == subj and rses == ses:
            reg = r.get("registration") or {}
            return reg.get("selected") or r.get("pam50_init_method") \
                   or r.get("init_method")
    return None


# ---------------------------------------------------------------------------
# run_S7
# ---------------------------------------------------------------------------


def run_S7(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S7_template_normalization.yaml")
    policy: dict = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    s6_qc = _load_s6_qc(out_path, dataset_key)
    s2_qc = _load_s2_qc(out_path, dataset_key)
    s6_runs = [r for r in s6_qc.get("runs", []) if r.get("status") != "FAIL"]
    if not s6_runs:
        return StepResult("FAIL",
                          f"No PASS/WARN S6 runs for dataset {dataset_key}")

    results: list[dict] = []
    for s6_run in s6_runs:
        run_id = s6_run.get("run_id")
        subject = s6_run.get("subject")
        session = s6_run.get("session")
        s2_init_method = _s2_init_method_from_qc(s2_qc, subject, session)

        funcref = _find_funcref(out_path, subject, session, run_id, dataset_key)
        func_cord_seg = _find_func_cord_seg(out_path, run_id)
        s6_fwd, s6_inv = _find_s6_warps(out_path, subject, session, run_id, dataset_key)
        s2_anat2pam50, s2_pam502anat = _find_s2_pam50_warps(
            out_path, subject, session, dataset_key, s2_qc=s2_qc,
        )
        subject_labels = _find_subject_vertebral_labels(
            out_path, subject, session, dataset_key,
        )

        missing = []
        if funcref is None: missing.append("funcref")
        if func_cord_seg is None: missing.append("func_cord_seg")
        if s6_fwd is None: missing.append("s6_warp_func_to_anat")
        if s6_inv is None: missing.append("s6_warp_anat_to_func")
        if s2_anat2pam50 is None: missing.append("s2_warp_anat_to_PAM50")
        if s2_pam502anat is None: missing.append("s2_warp_PAM50_to_anat")
        if missing:
            results.append({
                "status": "FAIL",
                "step_code": "S7_template_normalization",
                "dataset_key": dataset_key,
                "subject": subject, "session": session, "run_id": run_id,
                "failure_message": f"missing inputs: {missing}",
                "failure_reasons": [f"missing: {m}" for m in missing],
                "metrics": {}, "reportlets": {},
                "anat_to_pam50_init_method": s2_init_method,
                "refinement_enabled": bool(
                    policy.get("refinement", {}).get("enable", True)),
            })
            continue

        bold_run = {"subject": subject, "session": session,
                    "run_id": run_id, "path": f"{run_id}_bold.nii.gz"}
        res = run_S7_template_normalization(
            funcref_path=funcref,
            func_cord_seg_path=func_cord_seg,
            s6_warp_func_to_anat=s6_fwd,
            s6_warp_anat_to_func=s6_inv,
            s2_warp_anat_to_PAM50=s2_anat2pam50,
            s2_warp_PAM50_to_anat=s2_pam502anat,
            bold_run=bold_run,
            out_dir=out_path,
            work_dir=out_path / "work",
            dataset_key=dataset_key,
            policy=policy,
            s2_init_method=s2_init_method,
            subject_vertebral_labels=subject_labels,
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

    qc_dir = out_path / "logs" / "S7_template_normalization" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "dataset_key": dataset_key,
        "step_code": "S7_template_normalization",
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
# check_S7
# ---------------------------------------------------------------------------


def check_S7_template_normalization(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required for S7 check")
    out_path = Path(out).resolve()
    qc_dir = out_path / "logs" / "S7_template_normalization"
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


def run_S7_template_normalization_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """v1.0: rerun the full pipeline."""
    if not out:
        return StepResult("FAIL", "--out is required")
    return run_S7(dataset_key=dataset_key, datasets_local=datasets_local, out=out)


def run_S7_template_normalization_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: str | Path,
) -> dict[str, StepResult]:
    results = {}
    for key in dataset_keys:
        results[key] = run_S7_template_normalization_reportlets_only(
            dataset_key=key, out=str(out_base),
        )
    return results
