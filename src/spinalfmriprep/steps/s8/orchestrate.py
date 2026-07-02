"""Public API for S8 confounds + physio regressors: run, check, reportlets-only.

Filter discovery by S7's per-dataset qc.json (chain-aware), matching the
S6/S7 pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import run_S8_confounds_and_physio_regressors
from spinalfmriprep.lib.chain_scope import chain_scope

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
    """Both keyed and legacy func/ paths. S5/S6/S7 currently write to legacy."""
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    return [
        out_dir / "derivatives" / "spinalfmriprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "func",
        out_dir / "derivatives" / "spinalfmriprep"
            / f"sub-{subject}{ses_part}" / "func",
    ]


def _anat_dir_candidates(out_dir: Path, subject: str, session: Optional[str],
                         dataset_key: str) -> list[Path]:
    """Both keyed and legacy anat/ paths."""
    subject = _norm_sub(subject); session = _norm_ses(session)
    ses_part = f"/ses-{session}" if session else ""
    return [
        out_dir / "derivatives" / "spinalfmriprep" / dataset_key
            / f"sub-{subject}{ses_part}" / "anat",
        out_dir / "derivatives" / "spinalfmriprep"
            / f"sub-{subject}{ses_part}" / "anat",
    ]


def _find_s2_canal_dseg(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
    anat_modality: Optional[str] = None,
) -> Optional[Path]:
    mods = [anat_modality] if anat_modality else []
    for m in ("T2star", "T2w", "T1w"):
        if m not in mods:
            mods.append(m)
    for mod in mods:
        if not mod:
            continue
        p = _find_first(
            _anat_dir_candidates(out_dir, subject, session, dataset_key),
            f"*_desc-canal_dseg_{mod}.nii.gz",
        )
        if p is not None:
            return p
    return _find_first(
        _anat_dir_candidates(out_dir, subject, session, dataset_key),
        "*_desc-canal_dseg*.nii.gz",
    )


def _find_s2_cord_dseg(
    out_dir: Path, subject: str, session: Optional[str], dataset_key: str,
    anat_modality: Optional[str] = None,
) -> Optional[Path]:
    mods = [anat_modality] if anat_modality else []
    for m in ("T2star", "T2w", "T1w"):
        if m not in mods:
            mods.append(m)
    for mod in mods:
        if not mod:
            continue
        p = _find_first(
            _anat_dir_candidates(out_dir, subject, session, dataset_key),
            f"*_desc-cord_dseg_{mod}.nii.gz",
        )
        if p is not None:
            return p
    return _find_first(
        _anat_dir_candidates(out_dir, subject, session, dataset_key),
        "*_desc-cord_dseg*.nii.gz",
    )


def _anat_modality_from_s6(
    s6_qc: dict, subject: str, session: Optional[str],
) -> Optional[str]:
    subj = _norm_sub(subject); ses = _norm_ses(session)
    for r in s6_qc.get("runs", []):
        rs = _norm_sub(r.get("subject", ""))
        rses = _norm_ses(r.get("session"))
        if rs == subj and rses == ses:
            return r.get("anat_modality")
    return None


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


def _find_csf_mask(out_dir: Path, subject: str, session: Optional[str],
                   run_id: str, dataset_key: str) -> Optional[Path]:
    """S7 emits per-run PAM50csf_mask in native func."""
    return _find_first(
        _func_dir_candidates(out_dir, subject, session, dataset_key),
        f"{run_id}_desc-PAM50csf_mask.nii.gz",
    )


def _find_cord_mask(out_dir: Path, run_id: str) -> Optional[Path]:
    """S3's cord segmentation in BOLD geometry."""
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    rel = (Path("runs") / "S3_func_init_and_crop" / run_id
           / "init" / "localize" / "func_ref_fast_seg_crop.nii.gz")
    rel_local = (Path("S3_func_init_and_crop") / run_id
                 / "init" / "localize" / "func_ref_fast_seg_crop.nii.gz")
    for cand in (
        out_dir / rel,  # BIDS-App flat layout: <out>/runs/S3_.../.../seg_crop.nii.gz
        out_dir / "work" / rel_local,
        project_root / "work" / "done" / chain_scope(out_dir) / "S3" / rel,
        Path("work") / "done" / chain_scope(out_dir) / "S3" / rel,
    ):
        if cand.exists():
            return cand
    return None


def _find_moco_params(out_dir: Path, run_id: str) -> tuple[Optional[Path], Optional[Path]]:
    """S4 slicewise NIfTI moco params (moco_params_x.nii.gz, _y)."""
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    for base in (
        out_dir / "work" / "S4_func_motion_correction" / run_id,
        project_root / "work" / "done" / chain_scope(out_dir) / "S1" / "work" / "S4_func_motion_correction" / run_id,
        project_root / "work" / "done" / chain_scope(out_dir) / "S4" / "work" / "S4_func_motion_correction" / run_id,
    ):
        x = base / "moco_params_x.nii.gz"
        y = base / "moco_params_y.nii.gz"
        if x.exists() and y.exists():
            return x, y
    return None, None


def _find_frame_metrics(out_dir: Path, run_id: str) -> Optional[Path]:
    """S3 frame_metrics.tsv with dvars + ref_rms + outlier flag."""
    project_root = (out_dir.parent.parent if out_dir.name.startswith("wf_")
                    else Path.cwd())
    rel = (Path("S3_func_init_and_crop") / run_id / "metrics" / "frame_metrics.tsv")
    for base in (
        out_dir / "runs",
        project_root / "work" / "done" / chain_scope(out_dir) / "S3" / "runs",
        Path("work") / "done" / chain_scope(out_dir) / "S3" / "runs",
    ):
        p = base / rel
        if p.exists():
            return p
    return None


def _find_physio(bids_root: Optional[Path], subject: str,
                 session: Optional[str], run_id: str
                 ) -> list[tuple[Path, Path]]:
    """BIDS source: <bids_root>/sub-XX/[ses-YY]/func/*_physio.tsv.gz + json.

    Returns a list of (tsv_gz, json) pairs. BIDS allows multi-recording
    convention where pulse and respiratory live in separate files, named
    `*_recording-{pulse|cardiac|ecg}_physio.tsv.gz` and `_recording-
    {respiratory|resp}_physio.tsv.gz`. We return all matching pairs and
    the process layer merges them.
    """
    if not bids_root:
        return []
    subject = _norm_sub(subject); session = _norm_ses(session)
    func_dir = bids_root / f"sub-{subject}"
    if session:
        func_dir = func_dir / f"ses-{session}"
    func_dir = func_dir / "func"
    if not func_dir.exists():
        return []
    pairs: list[tuple[Path, Path]] = []
    for tsv in sorted(func_dir.glob(f"{run_id}*_physio.tsv.gz")):
        js = tsv.with_suffix("").with_suffix(".json")
        if not js.exists():
            stem = tsv.name.replace("_physio.tsv.gz", "_physio.json")
            js = func_dir / stem
        if js.exists():
            pairs.append((tsv, js))
    return pairs


def _find_bold_json(bids_root: Optional[Path], subject: str,
                    session: Optional[str], run_id: str) -> Optional[Path]:
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
    return hits[0] if hits else None


def _bids_root_from_qc(qc: dict) -> Optional[Path]:
    br = qc.get("bids_root")
    return Path(br) if br else None


def _tr_and_slicetiming(bold_json_path: Optional[Path]
                        ) -> tuple[Optional[float], Optional[list[float]]]:
    """Read RepetitionTime + SliceTiming from BIDS bold sidecar."""
    if bold_json_path is None or not bold_json_path.exists():
        return None, None
    try:
        meta = json.loads(bold_json_path.read_text())
    except Exception:
        return None, None
    tr = meta.get("RepetitionTime")
    st = meta.get("SliceTiming")
    if tr is not None:
        tr = float(tr)
    if isinstance(st, list):
        st = [float(x) for x in st]
    else:
        st = None
    return tr, st


def _slicetiming_for_bold(
    bids_slicetiming: Optional[list[float]],
    tr_s: float, n_slices: int,
    slice_order: str = "interleaved",
) -> tuple[list[float], str]:
    """Return slice-timing array of length n_slices, plus a provenance label.

    Strategy:
      1. BIDS SliceTiming length matches BOLD n_slices → use as-is.
      2. Otherwise (S3 z-cropped BOLD): generate uniform interleaved
         approximation TR/n_slices. Brooks 2008 cord-RETROICOR convention;
         within-TR error on cardiac phase is ~5-10% which is acceptable
         for cord at 2-3 s TR.
    """
    if bids_slicetiming is not None and len(bids_slicetiming) == n_slices:
        return bids_slicetiming, "bids_exact"
    # Uniform approximation
    times = [0.0] * n_slices
    if slice_order == "ascending":
        for i in range(n_slices):
            times[i] = i * tr_s / n_slices
    else:
        # Siemens interleaved default: odd-first when N odd, even-first when N even
        if n_slices % 2 == 1:
            order = list(range(0, n_slices, 2)) + list(range(1, n_slices, 2))
        else:
            order = list(range(1, n_slices, 2)) + list(range(0, n_slices, 2))
        for i, s in enumerate(order):
            times[s] = i * tr_s / n_slices
    return times, "approx_uniform_interleaved"


# ---------------------------------------------------------------------------
# run_S8
# ---------------------------------------------------------------------------


def run_S8(
    dataset_key: str,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S8_confounds.yaml")
    policy: dict = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    # Filter by S7 PASS/WARN; fall back to S6 if S7 missing
    s7_qc = _load_qc(out_path, "S7_template_normalization", dataset_key)
    s6_qc = _load_qc(out_path, "S6_func_to_anat_registration", dataset_key)
    if s7_qc:
        upstream_runs = [r for r in s7_qc.get("runs", []) if r.get("status") != "FAIL"]
        upstream_qc = s7_qc
        upstream_name = "S7"
    else:
        upstream_runs = [r for r in s6_qc.get("runs", []) if r.get("status") != "FAIL"]
        upstream_qc = s6_qc
        upstream_name = "S6"
    if not upstream_runs:
        return StepResult("FAIL",
                          f"No PASS/WARN {upstream_name} runs for dataset {dataset_key}")

    # Need bids_root from S1 or S2 qc for physio lookup
    s2_qc = _load_qc(out_path, "S2_anat_cordref", dataset_key)
    bids_root = _bids_root_from_qc(s2_qc) or _bids_root_from_qc(upstream_qc)

    results: list[dict] = []
    for u in upstream_runs:
        run_id = u.get("run_id")
        subject = u.get("subject")
        session = u.get("session")

        bold = _find_bold(out_path, subject, session, run_id, dataset_key)
        cord_mask = _find_cord_mask(out_path, run_id)
        csf_mask = _find_csf_mask(out_path, subject, session, run_id, dataset_key)
        moco_x, moco_y = _find_moco_params(out_path, run_id)
        frame_metrics = _find_frame_metrics(out_path, run_id)
        physio_pairs = _find_physio(bids_root, subject, session, run_id)
        bold_json = _find_bold_json(bids_root, subject, session, run_id)
        tr_s, bids_slice_timing = _tr_and_slicetiming(bold_json)
        # Subject-specific CSF source: S2 canal − cord (warped to func)
        anat_mod = _anat_modality_from_s6(s6_qc, subject, session)
        s2_canal = _find_s2_canal_dseg(out_path, subject, session, dataset_key, anat_mod)
        s2_cord = _find_s2_cord_dseg(out_path, subject, session, dataset_key, anat_mod)
        s6_warp_anat_to_bold = _find_first(
            _func_dir_candidates(out_path, subject, session, dataset_key),
            f"{run_id}_from-anat_to-bold_xfm.nii.gz",
        )
        # Determine actual BOLD n_slices for SliceTiming reconciliation
        slice_timing = None
        slice_timing_source = None
        if bold is not None and tr_s is not None:
            import nibabel as nib  # local import to avoid top-level overhead
            n_slices_bold = int(nib.load(bold).shape[2])
            slice_timing, slice_timing_source = _slicetiming_for_bold(
                bids_slice_timing, tr_s, n_slices_bold,
            )

        missing = []
        if bold is None: missing.append("bold")
        if cord_mask is None: missing.append("cord_mask")
        if tr_s is None: missing.append("tr")
        if missing:
            results.append({
                "status": "FAIL",
                "step_code": "S8_confounds_and_physio_regressors",
                "dataset_key": dataset_key,
                "subject": subject, "session": session, "run_id": run_id,
                "failure_message": f"missing inputs: {missing}",
                "failure_reasons": [f"missing: {m}" for m in missing],
                "metrics": {}, "reportlets": {},
                "physio_present": False,
                "spinalcompcor_enabled": bool(policy.get("spinalcompcor", {}).get("enabled", False)),
            })
            continue

        bold_run = {"subject": subject, "session": session,
                    "run_id": run_id, "path": f"{run_id}_bold.nii.gz"}
        res = run_S8_confounds_and_physio_regressors(
            bold_path=bold,
            cord_mask_path=cord_mask,
            csf_mask_path=csf_mask,
            moco_x_path=moco_x, moco_y_path=moco_y,
            frame_metrics_path=frame_metrics,
            tr_s=tr_s,
            slice_timing_s=slice_timing,
            physio_pairs=physio_pairs,
            bold_run=bold_run,
            out_dir=out_path,
            work_dir=out_path / "work",
            dataset_key=dataset_key,
            policy=policy,
            s2_canal_dseg=s2_canal,
            s2_cord_dseg=s2_cord,
            s6_warp_anat_to_bold=s6_warp_anat_to_bold,
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

    qc_dir = out_path / "logs" / "S8_confounds_and_physio_regressors" / dataset_key
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "dataset_key": dataset_key,
        "step_code": "S8_confounds_and_physio_regressors",
        "status": top_status,
        "failure_message": msg,
        "runs": results,
    }, indent=2, default=str))

    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    if top_status == "FAIL":
        return StepResult("FAIL", msg, qc_path=qc_path)
    return StepResult(top_status, msg, qc_path=qc_path)


def check_S8_confounds_and_physio_regressors(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required for S8 check")
    out_path = Path(out).resolve()
    qc_dir = out_path / "logs" / "S8_confounds_and_physio_regressors"
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


def run_S8_confounds_and_physio_regressors_reportlets_only(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    return run_S8(dataset_key=dataset_key, datasets_local=datasets_local, out=out)


def run_S8_confounds_and_physio_regressors_reportlets_only_batch(
    dataset_keys: list[str], out_base: str | Path,
) -> dict[str, StepResult]:
    return {
        k: run_S8_confounds_and_physio_regressors_reportlets_only(
            dataset_key=k, out=str(out_base),
        ) for k in dataset_keys
    }
