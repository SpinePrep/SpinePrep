"""Public API for S5 distortion correction: run, check, reportlets-only.

Filter discovery by S4's per-dataset qc.json (chain-aware), matching the
A2/A4 pattern used by S4. Aggregate top-level status PASS/WARN/FAIL.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import run_S5_func_distortion_correction
from spinalfmriprep.lib.chain_scope import chain_scope

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Mirrors S2-S4 StepResult shape."""
    status: str
    failure_message: Optional[str] = None
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_s4_qc(out_path: Path, dataset_key: str) -> dict:
    qc = out_path / "logs" / "S4_func_motion_correction" / dataset_key / "qc.json"
    if not qc.exists():
        return {}
    try:
        return json.loads(qc.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_s1_inventory(out_path: Path, dataset_key: str) -> dict:
    inv = out_path / "work" / "S1_input_verify" / dataset_key / "bids_inventory.json"
    if not inv.exists():
        return {}
    try:
        return json.loads(inv.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _anat_search_roots(
    subject: str, session: Optional[str],
    out_path: Path, dataset_key: str,
) -> list[Path]:
    """Where to look for S2 anat outputs. S2 stores anat under varying
    layouts (with/without dataset_key prefix, with/without session) and
    typically under a different workfolder than S4's derivatives chain.
    Walk both the current workfolder AND the S2 chain done dir."""
    roots: list[Path] = []
    # Try the current workfolder first (in case S2 ran in-place or was
    # symlinked into derivatives)
    bases = [out_path]
    # Also the S2 chain target (scope-aware, derived from the workfolder name).
    _scope = chain_scope(out_path)
    s2_done = out_path / "work" / "done" / _scope / "S2"
    # Fallback: project-relative work/done
    project_done = Path("work") / "done" / _scope / "S2"
    for cand in (s2_done, project_done, out_path.parent / "done" / _scope / "S2"):
        if cand.exists():
            try:
                bases.append(cand.resolve())
            except Exception:
                pass

    # Normalize subject/session: callers occasionally pass "sub-02" / "ses-01"
    # already prefixed; without stripping we'd build paths like "sub-sub-02".
    sub_norm = subject[4:] if subject and subject.startswith("sub-") else subject
    ses_norm = (session[4:] if session and str(session).startswith("ses-")
                else session)
    ses_part = f"ses-{ses_norm}/" if ses_norm else ""
    for base in bases:
        # Layout A: derivatives/spinalfmriprep/<dataset_key>/sub-XX/[ses-YY]/anat/
        roots.append(base / "derivatives" / "spinalfmriprep" / dataset_key
                     / f"sub-{sub_norm}" / (f"ses-{ses_norm}" if ses_norm else "") / "anat")
        # Layout B: derivatives/spinalfmriprep/sub-XX/[ses-YY]/anat/
        roots.append(base / "derivatives" / "spinalfmriprep"
                     / f"sub-{sub_norm}" / (f"ses-{ses_norm}" if ses_norm else "") / "anat")
    return [r for r in roots if r.exists()]


def _find_anat_for(
    subject: str, session: Optional[str],
    out_path: Path, dataset_key: str = "",
) -> Optional[Path]:
    """Best-effort lookup of the S2 anat (T2star -> T2w -> T1w preferred).

    Match the same-contrast-as-EPI rule: T2*-weighted EPI registers
    cleanly against T2*/T2 anats; inverted-contrast T1w hurts SyN
    convergence. Prefer S2 cordref outputs (already cropped to cord)
    over raw BIDS anats.
    """
    for root in _anat_search_roots(subject, session, out_path, dataset_key):
        for pat in (
            "*_desc-cordref_T2star.nii.gz",
            "*_desc-cordref_T2w.nii.gz",
            "*_desc-cordref_T1w.nii.gz",
            "*_T2star.nii.gz",
            "*_T2w.nii.gz",
            "*_T1w.nii.gz",
        ):
            hits = sorted(p for p in root.glob(pat)
                          if "_desc-" not in p.name or "cordref" in p.name)
            if hits:
                return hits[0]
    return None


def _find_cord_mask_for(
    subject: str, session: Optional[str],
    out_path: Path, dataset_key: str = "",
) -> Optional[Path]:
    for root in _anat_search_roots(subject, session, out_path, dataset_key):
        # S2 names them desc-cord_dseg with modality suffix. Prefer T2star
        # to match the EPI contrast direction.
        for pat in ("*_desc-cord_dseg_T2star.nii.gz",
                    "*_desc-cord_dseg_T2w.nii.gz",
                    "*_desc-cord_dseg_T1w.nii.gz",
                    "*_desc-cord_dseg.nii.gz"):
            hits = sorted(root.glob(pat))
            if hits:
                return hits[0]
    return None


# ---------------------------------------------------------------------------
# run_S5: process every PASS/WARN BOLD run from S4
# ---------------------------------------------------------------------------


def run_S5(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S5_func_distortion_correction.yaml")
    policy = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    # S4 qc determines which runs to do S5 on
    s4_qc = _load_s4_qc(out_path, dataset_key)
    s4_runs = [r for r in s4_qc.get("runs", []) if r.get("status") != "FAIL"]
    if not s4_runs:
        return StepResult("FAIL",
                          f"No PASS/WARN S4 runs for dataset {dataset_key}")

    # S1 inventory gives us BIDS root + fmap acquisition metadata
    inv = _load_s1_inventory(out_path, dataset_key)
    bids_root = Path(inv.get("bids_root", "")) if inv else None
    fmap_runs = [r for r in inv.get("runs", []) if r.get("modality") == "fmap"]

    # Process each run
    results: list[dict] = []
    for s4_run in s4_runs:
        run_id = s4_run.get("run_id")
        # subject field is sometimes "02" (bare) and sometimes "sub-02"
        # (already prefixed). Normalize before building the path.
        subj_raw = str(s4_run.get("subject") or "")
        subj = subj_raw[4:] if subj_raw.startswith("sub-") else subj_raw
        ses_raw = s4_run.get("session")
        if ses_raw:
            ses = str(ses_raw)
            ses = ses[4:] if ses.startswith("ses-") else ses
        else:
            ses = None
        # The S4 run_id equals the S3 run dir name. Recover the original
        # BOLD via S1 inventory + funccrop_bold for the cropped input,
        # but for S5 we operate on the S4 mocoref output (already cropped).
        if ses:
            mocoref = (out_path / "derivatives" / "spinalfmriprep"
                       / f"sub-{subj}"
                       / f"ses-{ses}" / "func"
                       / f"{run_id}_desc-mocoref_bold.nii.gz")
        else:
            mocoref = (out_path / "derivatives" / "spinalfmriprep"
                       / f"sub-{subj}" / "func"
                       / f"{run_id}_desc-mocoref_bold.nii.gz")
        if not mocoref.exists():
            results.append({
                "status": "FAIL",
                "run_id": run_id,
                "subject": s4_run.get("subject"),
                "session": s4_run.get("session"),
                "failure_message": f"missing S4 mocoref: {mocoref}",
                "reportlets": {},
            })
            continue

        # Build a stub "bold_run" dict carrying acquisition metadata if we
        # can find it in the inventory.
        #
        # CRITICAL: S4's qc.json stores subject as "sub-02" (BIDS-prefixed)
        # but the S1 inventory uses the bare label "02". The orchestrator
        # has already stripped both in `subj` / `ses`. Match the inventory
        # using those bare labels — previously this comparison used the
        # raw `s4_run` value and failed for every run, falling through
        # to a stub with empty `acquisition`; downstream select_mode
        # then filtered every fmap out (subject mismatch) and silently
        # collapsed mode to SyN for datasets that DO have topup-eligible
        # reversed-PE fmaps (ds005883_cospine_pain, ds005884_cospine_motor).
        def _bare_sub(r):
            v = str(r.get("subject") or "")
            return v[4:] if v.startswith("sub-") else v

        def _bare_ses(r):
            v = r.get("session")
            if v is None or v == "":
                return None
            s = str(v)
            return s[4:] if s.startswith("ses-") else s

        bold_run = next(
            (r for r in inv.get("runs", [])
             if r.get("modality") == "func"
             and _bare_sub(r) == subj
             and _bare_ses(r) == ses
             and Path(r["path"]).name.replace("_bold.nii.gz", "")
                 .replace("_bold.nii", "") == run_id),
            None,
        )
        if bold_run is None:
            # Last-resort stub: empty acquisition means topup gets
            # skipped, fall through to SyN. Use bare subject/session
            # so any downstream filter operating on bare ids works.
            bold_run = {
                "subject": subj,
                "session": ses,
                "path": f"sub-{subj}/func/{run_id}_bold.nii.gz",
                "acquisition": {},
            }

        # Same normalization for the fmap pool — restrict to fmaps that
        # belong to THIS run's bare subject/session before handing them
        # to select_mode. (select_mode does its own sub/ses filter too,
        # but it compares against bold_run's subject/session; pre-filtering
        # by the canonical bare id makes the chain robust.)
        sub_fmaps = [
            f for f in fmap_runs
            if _bare_sub(f) == subj and _bare_ses(f) == ses
        ]

        anat = _find_anat_for(s4_run.get("subject"), s4_run.get("session"),
                              out_path, dataset_key)
        cord_mask = _find_cord_mask_for(s4_run.get("subject"), s4_run.get("session"),
                                        out_path, dataset_key)

        res = run_S5_func_distortion_correction(
            bold_path=mocoref,
            bold_run=bold_run,
            fmap_runs=sub_fmaps,
            bids_root=bids_root or out_path,
            cord_mask_path=cord_mask,
            anat_path=anat,
            out_dir=out_path,
            work_dir=out_path / "work",
            dataset_key=dataset_key,
            policy=policy,
        )
        results.append(res)

    # Aggregate top-level status (matches A3 pattern)
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

    qc_dir = out_path / "logs" / "S5_func_distortion_correction" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "dataset_key": dataset_key,
        "step_code": "S5_func_distortion_correction",
        "status": top_status,
        "failure_message": msg,
        "runs": results,
    }, indent=2, default=str))

    # Auto-regen dashboard so the new card lights up
    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    if top_status == "FAIL":
        return StepResult("FAIL", msg, qc_path=qc_path)
    return StepResult(top_status, msg, qc_path=qc_path)


# ---------------------------------------------------------------------------
# check_S5: validate existing outputs
# ---------------------------------------------------------------------------


def check_S5_func_distortion_correction(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required for S5 check")
    out_path = Path(out).resolve()
    qc_dir = out_path / "logs" / "S5_func_distortion_correction"
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
# reportlets-only and batch variants (thin wrappers - v1.0 minimal)
# ---------------------------------------------------------------------------


def run_S5_func_distortion_correction_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    """v1.0: rerun the full pipeline. v1.x: render from qc_metrics.json only."""
    if not out:
        return StepResult("FAIL", "--out is required")
    # In v1.0 there are no expensive intermediate caches to skip yet for S5
    # (topup is fast and already idempotent). Future versions can short-
    # circuit to re-render reportlets from work/qc_metrics.json + cached
    # warp files.
    return run_S5(dataset_key=dataset_key,
                  datasets_local=datasets_local, out=out)


def run_S5_func_distortion_correction_reportlets_only_batch(
    dataset_keys: list[str],
    out_base: str | Path,
) -> dict[str, StepResult]:
    results = {}
    for key in dataset_keys:
        results[key] = run_S5_func_distortion_correction_reportlets_only(
            dataset_key=key, out=str(out_base),
        )
    return results
