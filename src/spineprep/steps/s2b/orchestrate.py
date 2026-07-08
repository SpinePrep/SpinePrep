"""S2B_func_denoise: optional MP-PCA thermal-noise denoising as its own step.

Runs on the raw per-run 4D BOLD (after S1 inventory, before S3 localize/crop and
S4 moco) -- MP-PCA needs the rawest, non-interpolated data (see lib/denoise.py).
OFF by default; when disabled the step is a clean passthrough (qc PASS, no
outputs) and S3 falls back to the raw BOLD.

Outputs per run, under the workfolder:
  denoise/<run_id>/desc-denoised_bold.nii.gz   (S3 consumes this when present)
  denoise/<run_id>/denoise_noise_map.nii.gz
  derivatives/spineprep/<ds>/sub-XX/figures/  (3 QC reportlets)
  logs/S2B_func_denoise/<ds>/qc.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import nibabel as nib
import numpy as np
import yaml

from spineprep.lib.denoise import mppca_denoise
from spineprep.steps.s2.io import StepResult
from spineprep.steps.s3.io import _collect_func_candidates
from .reportlets import render_denoise_reportlets


POLICY_PATH = Path("policy") / "S2B_func_denoise.yaml"


def _residual_structure_corr(raw: np.ndarray, den: np.ndarray) -> Optional[float]:
    """Pearson corr between removed-noise SD and the temporal-mean image.
    High positive correlation => anatomy leaked into the residual => signal was
    removed (over-denoising). Near-zero is the healthy, structureless case."""
    removed_sd = (raw - den).std(axis=3).ravel()
    mean_img = raw.mean(axis=3).ravel()
    m = mean_img > np.percentile(mean_img[mean_img > 0], 50) if (mean_img > 0).any() else None
    if m is None or m.sum() < 10:
        return None
    a, b = removed_sd[m], mean_img[m]
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _load_policy() -> dict:
    if POLICY_PATH.exists():
        try:
            return yaml.safe_load(POLICY_PATH.read_text()) or {}
        except Exception:
            return {}
    return {}


def _process_run(bold_path: Path, run_id: str, subject: str, session: Optional[str],
                 out_path: Path, dataset_key: str, cfg: dict) -> dict:
    denoise_dir = out_path / "denoise" / run_id
    work_dir = denoise_dir / "work"
    out_bold = denoise_dir / "desc-denoised_bold.nii.gz"
    ok, noise_map, meta = mppca_denoise(bold_path, out_bold, work_dir, cfg)
    res: dict[str, Any] = {
        "subject": subject, "session": session, "run_id": run_id,
        "status": "PASS" if ok else "FAIL",
        "denoise": meta,
        "metrics": {k: meta.get(k) for k in
                    ("tsnr_pre", "tsnr_post", "tsnr_gain_pct", "noise_median")},
        "reportlets": {},
    }
    if not ok:
        res["failure_message"] = meta.get("error", "denoise failed")
        return res

    raw = nib.load(str(bold_path)).get_fdata(dtype=np.float32)
    den = nib.load(str(out_bold)).get_fdata(dtype=np.float32)
    rstruct = _residual_structure_corr(raw, den)
    res["metrics"]["residual_structure_corr"] = rstruct

    # Gate: tSNR must improve, and the residual must stay structureless.
    qt = cfg.get("qc_thresholds", {})
    reasons = []
    gain = meta.get("tsnr_gain_pct")
    if gain is not None and gain < qt.get("warn_min_tsnr_gain_pct", 0.0):
        reasons.append(f"tSNR gain {gain:.0f}% below expectation")
    if rstruct is not None and rstruct > qt.get("fail_residual_corr", 0.6):
        res["status"] = "FAIL"
        reasons.append(f"residual structure corr {rstruct:.2f} -> over-denoising")
    elif rstruct is not None and rstruct > qt.get("warn_residual_corr", 0.4):
        if res["status"] == "PASS":
            res["status"] = "WARN"
        reasons.append(f"residual structure corr {rstruct:.2f}")
    if reasons and res["status"] == "PASS":
        res["status"] = "WARN"
    res["failure_reasons"] = reasons

    # Reportlets
    sub_dir = f"sub-{subject}" + (f"/ses-{session}" if session else "")
    fig_dir = out_path / "derivatives" / "spineprep" / dataset_key / sub_dir / "figures"
    try:
        figs = render_denoise_reportlets(
            bold_path, out_bold, noise_map, fig_dir, run_id,
            status=res["status"], tsnr_gain_pct=gain)
        res["reportlets"] = {k: str(v.relative_to(out_path)) for k, v in figs.items()}
    except Exception as e:
        res.setdefault("failure_reasons", []).append(f"reportlet failed: {e}")
    return res


def run_S2B_func_denoise(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
    s1_base: Optional[Path] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()
    ds_key = dataset_key or "ad_hoc"
    inv_base = Path(s1_base) if s1_base else out_path
    inv_path = inv_base / "work" / "S1_input_verify" / ds_key / "bids_inventory.json"
    if not inv_path.exists():
        return StepResult("FAIL", f"Missing inventory: {inv_path}")
    inventory = json.loads(inv_path.read_text(encoding="utf-8"))
    bids_root = Path(inventory["bids_root"])
    cfg = _load_policy()

    qc_dir = out_path / "logs" / "S2B_func_denoise" / ds_key
    qc_dir.mkdir(parents=True, exist_ok=True)

    # Disabled => clean passthrough. Chain advances; S3 reads raw BOLD.
    if not cfg.get("enabled", False):
        qc = {"status": "PASS", "dataset_key": ds_key,
              "bids_root": str(bids_root), "enabled": False,
              "counts": {"total": 0, "pass": 0, "fail": 0},
              "failure_message": "denoise disabled (passthrough)", "runs": []}
        (qc_dir / "qc.json").write_text(json.dumps(qc, indent=2))
        return StepResult("PASS", "denoise disabled (passthrough)")

    candidates = _collect_func_candidates(inventory)
    runs: list[dict] = []
    items = [(sub, ses, c) for (sub, ses), cands in sorted(candidates.items()) for c in cands]

    def _do(sub, ses, cand):
        rel = cand["path"]
        run_id = Path(rel).name.replace(".nii.gz", "").replace(".nii", "").replace("_bold", "")
        return _process_run(bids_root / rel, run_id, sub, ses, out_path, ds_key, cfg)

    if batch_workers > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=batch_workers) as ex:
            futs = {ex.submit(_do, s, e, c): (s, e, c) for s, e, c in items}
            for f in as_completed(futs):
                try:
                    runs.append(f.result())
                except Exception as exc:
                    s, e, c = futs[f]
                    runs.append({"subject": s, "session": e, "status": "FAIL",
                                 "failure_message": f"worker error: {exc}"})
    else:
        for s, e, c in items:
            runs.append(_do(s, e, c))

    n_pass = sum(1 for r in runs if r.get("status") == "PASS")
    n_warn = sum(1 for r in runs if r.get("status") == "WARN")
    n_fail = sum(1 for r in runs if r.get("status") == "FAIL")
    top = "PASS" if n_fail == 0 and (n_pass + n_warn) > 0 else (
        "WARN" if (n_pass + n_warn) > 0 else "FAIL")
    qc = {"status": top, "dataset_key": ds_key, "bids_root": str(bids_root),
          "enabled": True,
          "counts": {"total": len(runs), "pass": n_pass, "warn": n_warn, "fail": n_fail},
          "failure_message": None if n_fail == 0 else f"{n_fail} runs failed",
          "runs": runs}
    (qc_dir / "qc.json").write_text(json.dumps(qc, indent=2, default=str))
    return StepResult(top, qc["failure_message"])


def check_S2B_func_denoise(dataset_key: Optional[str] = None,
                           datasets_local: Optional[str] = None,
                           out: Optional[str] = None, **_) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    qc = Path(out).resolve() / "logs" / "S2B_func_denoise" / (dataset_key or "ad_hoc") / "qc.json"
    if not qc.exists():
        return StepResult("FAIL", f"No S2B qc: {qc}")
    j = json.loads(qc.read_text())
    return StepResult(j.get("status", "UNKNOWN"), j.get("failure_message"))
