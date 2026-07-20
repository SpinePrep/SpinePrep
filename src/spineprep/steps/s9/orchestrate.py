"""Public API for S9 primary functional derivatives: run, check, reportlets-only.

Filters by S8 PASS/WARN (S8 is the most recent upstream); falls back to S7
when S8 missing. Matches S6/S7/S8 orchestrate pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import (
    _s9_code_sha_for_record as _s9_code_sha,
    _s9_policy_sha_for_record as _s9_policy_sha,
    run_S9_primary_functional_derivatives,
)
from spineprep.lib.chain_scope import chain_scope

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
        out_dir / "derivatives" / "spineprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "func",
        out_dir / "derivatives" / "spineprep"
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
               run_id: str, dataset_key: str) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_desc-undistorted_bold.nii.gz",
    )


def _find_cord_mask(out_dir: Path, run_id: str) -> Optional[Path]:
    """EPI cord seg in the SAME geometry as the post-S5 BOLD that S9
    operates on.

    Priority (same pattern as S6 / S7 — audit refs:
    .claude/specs/s6-algorithm-audit.md F10 and the matching S7 fix):
      1. S5 ``cospine/bold_after_cord_seg.nii.gz`` — sct_deepseg sc_epi
         on the POST-S5 mean BOLD. Matches the post-S5 BOLD that S9
         smooths.
      2. S3.1 ``func_ref_fast_seg_crop.nii.gz`` — fallback, PRE-S5
         geometry. Only correct when S5 made minimal cord shifts (SyN-
         fallback). On topup runs the cord shifts 5-10 mm A-P and this
         seg lands off-cord, producing the misaligned-mask artifact the
         user reported (the tSNR-map / former smoothed_vs_unsmoothed
         reportlets). Priority 1 (S5 seg) is what fixes it.
    """
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())

    # Priority 1: S5 post-correction cord seg.
    s5_rel = (Path("S5_func_distortion_correction") / run_id / "cospine"
              / "bold_after_cord_seg.nii.gz")
    for cand in (
        out_dir / "work" / s5_rel,
        project_root / "work" / "done" / chain_scope(out_dir) / "S5" / "work" / s5_rel,
        Path("work") / "done" / chain_scope(out_dir) / "S5" / "work" / s5_rel,
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
        project_root / "work" / "done" / chain_scope(out_dir) / "S3" / rel,
        Path("work") / "done" / chain_scope(out_dir) / "S3" / rel,
    ):
        if cand.exists():
            return cand
    return None


def _find_warp_bold_to_pam50(
    out_dir: Path, subject: str, session: Optional[str],
    run_id: str, dataset_key: str,
) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_from-bold_to-PAM50_xfm.nii.gz",
    )


def _find_pam50_levels_native(
    out_dir: Path, subject: str, session: Optional[str],
    run_id: str, dataset_key: str,
) -> Optional[Path]:
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_desc-PAM50spinallevels.nii.gz",
    )


def _resolve_bids_root(datasets_local: Optional[str], dataset_key: str) -> Optional[str]:
    """Map dataset_key -> local BIDS root via datasets_local.yaml. Used when the
    upstream qc doesn't carry bids_root (S8's qc has it as None)."""
    if not datasets_local:
        return None
    try:
        d = yaml.safe_load(Path(datasets_local).read_text()) or {}
    except Exception:
        return None
    m = d.get("datasets", d)
    if not isinstance(m, dict):
        return None
    v = m.get(dataset_key)
    if isinstance(v, dict):
        v = v.get("path") or v.get("bids_root")
    return v if isinstance(v, str) else None


def _s3_dummy_dropped(out_dir: Path, dataset_key: str, run_id: str) -> int:
    """Initial volumes S3 removed for this run, from S3's own qc.json.

    Recorded on the derivative BOLD sidecar so the shift between the derivative
    and the raw `events.tsv` is discoverable rather than silent.
    """
    qc = out_dir / "logs" / "S3_func_init_and_crop" / dataset_key / "qc.json"
    try:
        data = json.loads(qc.read_text(encoding="utf-8"))
    except Exception:
        return 0
    for run in data.get("runs", []) or []:
        if str(run.get("run_id")) == str(run_id):
            try:
                return int((run.get("metrics") or {}).get("n_dummy_dropped", 0) or 0)
            except Exception:
                return 0
    return 0


def _run_repetition_time(bids_root: Optional[str], run_id: str) -> Optional[float]:
    """Authoritative RepetitionTime (s) from the raw BIDS bold sidecar.

    The processed NIfTI loses TR from its header (pixdim[4] defaults to 1.0),
    so a GLM would mis-model timing if we read it back from the image. We read
    it from the source sidecar, walking BIDS inheritance: the run's own sidecar
    first, then a task-level sidecar at the dataset root.
    """
    if not bids_root:
        return None
    root = Path(bids_root)
    if not root.exists():
        return None
    for j in root.rglob(f"{run_id}_bold.json"):
        try:
            tr = json.loads(j.read_text()).get("RepetitionTime")
            if tr:
                return float(tr)
        except Exception:
            pass
    import re
    m = re.search(r"task-([A-Za-z0-9]+)", run_id)
    if m:
        for j in root.glob(f"task-{m.group(1)}_bold.json"):
            try:
                tr = json.loads(j.read_text()).get("RepetitionTime")
                if tr:
                    return float(tr)
            except Exception:
                pass
    return None


def _pam50_ref() -> Optional[Path]:
    import os
    sct_dir = os.environ.get("SCT_DIR")
    if not sct_dir:
        return None
    return Path(sct_dir) / "data" / "PAM50" / "template" / "PAM50_t2s.nii.gz"


# ---------------------------------------------------------------------------
# run_S9
# ---------------------------------------------------------------------------


def run_S9(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
    bids_root: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S9_primary_functional_derivatives.yaml")
    policy: dict = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    # The caller's --bids-root wins. It is the only source available in the
    # BIDS-App path: S8's qc carries bids_root=None and the app passes no
    # --datasets-local, so without this S9 could not read the authoritative
    # RepetitionTime and silently emitted the processed header's pixdim[4]
    # (which SCT resets to 1.0) into the derivative sidecar. See
    # .claude/specs/s3-algorithm-audit.md.
    cli_bids_root = bids_root
    s8_qc = _load_qc(out_path, "S8_confounds_and_physio_regressors", dataset_key)
    if s8_qc:
        upstream_runs = [r for r in s8_qc.get("runs", []) if r.get("status") != "FAIL"]
        upstream_name = "S8"
        bids_root = cli_bids_root or s8_qc.get("bids_root")
    else:
        s7_qc = _load_qc(out_path, "S7_template_normalization", dataset_key)
        upstream_runs = [r for r in s7_qc.get("runs", []) if r.get("status") != "FAIL"]
        upstream_name = "S7"
        bids_root = cli_bids_root or s7_qc.get("bids_root")
    if not bids_root:
        bids_root = _resolve_bids_root(datasets_local, dataset_key)
    if not upstream_runs:
        return StepResult("FAIL",
                          f"No PASS/WARN {upstream_name} runs for dataset {dataset_key}")

    pam50_ref = _pam50_ref()
    if pam50_ref is None or not pam50_ref.exists():
        return StepResult("FAIL", "PAM50_t2s.nii.gz not found ($SCT_DIR missing?)")

    # Resumability: reuse a run's prior S9 result when its final derivative
    # already exists, so a re-run only materialises newly-surviving runs
    # (S9 is the most expensive step). Set SPINEPREP_S9_FORCE=1 to
    # force full recomputation.
    import os as _os
    _force_s9 = _os.environ.get("SPINEPREP_S9_FORCE") == "1"
    _code_sha = _s9_code_sha()
    _policy_sha = _s9_policy_sha(policy)
    _prior_s9 = {
        (_norm_sub(r.get("subject")), r.get("run_id")): r
        for r in _load_qc(out_path, "S9_primary_functional_derivatives",
                          dataset_key).get("runs", [])
    }

    results: list[dict] = []
    for u in upstream_runs:
        run_id = u.get("run_id")
        subject = u.get("subject")
        session = u.get("session")

        if not _force_s9:
            _done = _find_first(
                _func_dir_candidates(out_path, subject, session, dataset_key),
                f"{run_id}_desc-preproc_bold.nii.gz")
            _prev = _prior_s9.get((_norm_sub(subject), run_id))
            # Existence alone is not enough. Reusing on "the output file is on
            # disk" silently republished 445 stale records after the 2026-07-18
            # FWHM fix -- old metrics, old reportlet paths, and a qc.json that
            # reported those reportlets as present because the old PNGs were
            # still there. Only reuse when the prior record was produced by the
            # same code and the same policy.
            if (_done is not None and _prev is not None
                    and _prev.get("provenance", {}).get("code_sha") == _code_sha
                    and _prev.get("provenance", {}).get("policy_sha256") == _policy_sha):
                results.append(_prev)
                continue

        bold = _find_bold(out_path, subject, session, run_id, dataset_key)
        cord_mask = _find_cord_mask(out_path, run_id)
        warp = _find_warp_bold_to_pam50(out_path, subject, session, run_id, dataset_key)
        levels = _find_pam50_levels_native(out_path, subject, session, run_id, dataset_key)

        missing = []
        if bold is None: missing.append("bold")
        if cord_mask is None: missing.append("cord_mask")
        if warp is None: missing.append("from-bold_to-PAM50_xfm")
        if missing:
            results.append({
                "status": "FAIL",
                "step_code": "S9_primary_functional_derivatives",
                "dataset_key": dataset_key,
                "subject": subject, "session": session, "run_id": run_id,
                "failure_message": f"missing inputs: {missing}",
                "failure_reasons": [f"missing: {m}" for m in missing],
                "metrics": {}, "reportlets": {},
                "smoothing_method": str(policy.get("smoothing", {}).get("method", "sct_cord")),
                "sigma_mm": list(policy.get("smoothing", {}).get("sigma_mm", [1, 1, 5])),
            })
            continue

        bold_run = {"subject": subject, "session": session,
                    "run_id": run_id, "path": f"{run_id}_bold.nii.gz",
                    "RepetitionTime": _run_repetition_time(bids_root, run_id),
                    "n_dummy_dropped": _s3_dummy_dropped(out_path, dataset_key, run_id)}
        res = run_S9_primary_functional_derivatives(
            bold_path=bold, cord_mask_path=cord_mask,
            warp_bold_to_pam50=warp, pam50_ref=pam50_ref,
            pam50_levels_native=levels,
            bold_run=bold_run, out_dir=out_path,
            work_dir=out_path / "work",
            dataset_key=dataset_key, policy=policy,
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

    qc_dir = out_path / "logs" / "S9_primary_functional_derivatives" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "dataset_key": dataset_key,
        "step_code": "S9_primary_functional_derivatives",
        "status": top_status,
        "failure_message": msg,
        "runs": results,
    }, indent=2, default=str))

    from spineprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    if top_status == "FAIL":
        return StepResult("FAIL", msg, qc_path=qc_path)
    return StepResult(top_status, msg, qc_path=qc_path)


def check_S9_primary_functional_derivatives(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required for S9 check")
    out_path = Path(out).resolve()
    qc_dir = out_path / "logs" / "S9_primary_functional_derivatives"
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


def run_S9_primary_functional_derivatives_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    return run_S9(dataset_key=dataset_key, datasets_local=datasets_local, out=out)


def run_S9_primary_functional_derivatives_reportlets_only_batch(
    dataset_keys: list[str], out_base: str | Path,
) -> dict[str, StepResult]:
    return {
        k: run_S9_primary_functional_derivatives_reportlets_only(
            dataset_key=k, out=str(out_base),
        ) for k in dataset_keys
    }
