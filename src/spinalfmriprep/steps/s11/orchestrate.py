"""Public API for S11 QC aggregation + release readiness.

S11 is global: walks the entire chain, emits release deliverables at
`derivatives/spinalfmriprep/` (top level) plus per-subject HTML reports.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .process import (
    _build_citation_cff,
    _build_cohort_coverage_matrix,
    _build_cohort_tsnr_heatmap,
    _build_dataset_description,
    _build_group_dashboard_data,
    _build_methods_manifest,
    _build_metrics_index,
    _build_metrics_index_tsv,
    _build_participants_tsv,
    _build_per_subject_html,
    _build_references_bib,
    _build_release_report,
    _build_reproducibility_receipt,
    _build_run_inventory,
    _flat_run_records,
    _render_group_dashboard_html,
    _walk_chain_qc,
)

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str] = None
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


def run_S11(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    """S11 is global. dataset_key is ignored for aggregation but
    accepted for CLI uniformity. Emits at derivatives/spinalfmriprep/.
    """
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S11_qc_aggregation_and_release.yaml")
    policy: dict = {}
    if policy_path.exists():
        try:
            policy = yaml.safe_load(policy_path.read_text()) or {}
        except Exception as e:
            return StepResult("FAIL", f"Policy error: {e}")

    # 1. Walk chain QC
    chain_qc = _walk_chain_qc(out_path)
    records = _flat_run_records(chain_qc)
    if not records:
        return StepResult("FAIL", "No qc.json files found on chain")

    # Destination scoping (audit B15): chain-runner sets
    # ``out_dir/derivatives`` as a symlink to the immediate predecessor's
    # derivatives. If we wrote here we'd mutate the upstream-locked
    # workfolder. When derivatives is a symlink, S11 owns
    # ``out_dir/release/`` instead — the upstream tree stays immutable.
    deriv_link = out_path / "derivatives"
    if deriv_link.is_symlink():
        deriv_root = out_path / "release"
    else:
        deriv_root = deriv_link / "spinalfmriprep"
    deriv_root.mkdir(parents=True, exist_ok=True)
    logs_root = deriv_root / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    deliverables: dict[str, str] = {}
    failures: list[str] = []

    # 2. metrics_index.jsonl + metrics_index.tsv (MRIQC long-format)
    try:
        idx = deriv_root / "metrics_index.jsonl"
        n_idx = _build_metrics_index(records, idx)
        deliverables["metrics_index_jsonl"] = str(idx.relative_to(out_path))
    except Exception as e:
        failures.append(f"metrics_index: {e}")
        n_idx = 0
    try:
        idx_tsv = deriv_root / "metrics_index.tsv"
        _build_metrics_index_tsv(records, idx_tsv)
        deliverables["metrics_index_tsv"] = str(idx_tsv.relative_to(out_path))
    except Exception as e:
        failures.append(f"metrics_index_tsv: {e}")

    # 3. Run inventory
    try:
        rinv_tsv = deriv_root / "run_inventory.tsv"
        rinv_png = deriv_root / "run_inventory.png"
        n_runs = _build_run_inventory(records, rinv_tsv, rinv_png)
        deliverables["run_inventory_tsv"] = str(rinv_tsv.relative_to(out_path))
        deliverables["run_inventory_png"] = str(rinv_png.relative_to(out_path))
    except Exception as e:
        failures.append(f"run_inventory: {e}")
        n_runs = 0

    # 4. Group QC dashboard
    try:
        gdata = _build_group_dashboard_data(records, policy)
        gdash = deriv_root / "group_qc_dashboard.html"
        _render_group_dashboard_html(gdata, gdash)
        deliverables["group_dashboard"] = str(gdash.relative_to(out_path))
    except Exception as e:
        failures.append(f"group_dashboard: {e}")

    # Per-subject HTML is delayed until after the methods boilerplate
    # has been built, so each report can embed it (NiPreps convention).
    subjects = {(r.get("dataset_key"), r.get("subject")) for r in records
                if r.get("subject")}
    n_subjects = len(subjects)

    # 6. Cord-novel cohort views
    try:
        cov_tsv = deriv_root / "cohort_coverage_matrix.tsv"
        cov_png = deriv_root / "cohort_coverage_matrix.png"
        _build_cohort_coverage_matrix(out_path, records, policy, cov_tsv, cov_png)
        deliverables["coverage_matrix_tsv"] = str(cov_tsv.relative_to(out_path))
        deliverables["coverage_matrix_png"] = str(cov_png.relative_to(out_path))
    except Exception as e:
        failures.append(f"coverage_matrix: {e}")
    try:
        ts_tsv = deriv_root / "cohort_tsnr_heatmap.tsv"
        ts_png = deriv_root / "cohort_tsnr_heatmap.png"
        _build_cohort_tsnr_heatmap(out_path, records, policy, ts_tsv, ts_png)
        deliverables["tsnr_heatmap_tsv"] = str(ts_tsv.relative_to(out_path))
        deliverables["tsnr_heatmap_png"] = str(ts_png.relative_to(out_path))
    except Exception as e:
        failures.append(f"tsnr_heatmap: {e}")
    # cohort FC summary removed 2026-06-11 with S10 (analyst-owned analysis).

    # 7. Reproducibility receipt (needs to be computed before CITATION + manifest)
    try:
        rec_path = deriv_root / "reproducibility_receipt.json"
        recipe = _build_reproducibility_receipt(out_path, chain_qc, rec_path, policy)
        deliverables["reproducibility_receipt"] = str(rec_path.relative_to(out_path))
    except Exception as e:
        failures.append(f"reproducibility_receipt: {e}")
        recipe = {}

    # 8. CITATION.cff (top level) + CITATION.bib (logs/, NiPreps convention)
    try:
        cff_path = deriv_root / "CITATION.cff"
        _build_citation_cff(cff_path, recipe, policy)
        deliverables["citation_cff"] = str(cff_path.relative_to(out_path))
    except Exception as e:
        failures.append(f"citation_cff: {e}")
    try:
        bib_path = logs_root / "CITATION.bib"
        _build_references_bib(bib_path)
        deliverables["citation_bib"] = str(bib_path.relative_to(out_path))
    except Exception as e:
        failures.append(f"citation_bib: {e}")

    # 9. dataset_description.json
    try:
        dd_path = deriv_root / "dataset_description.json"
        _build_dataset_description(out_path, chain_qc, recipe, dd_path)
        deliverables["dataset_description"] = str(dd_path.relative_to(out_path))
    except Exception as e:
        failures.append(f"dataset_description: {e}")

    # 10. participants.tsv + .json
    try:
        p_tsv = deriv_root / "participants.tsv"
        p_json = deriv_root / "participants.json"
        n_part = _build_participants_tsv(out_path, records, policy, p_tsv, p_json)
        deliverables["participants_tsv"] = str(p_tsv.relative_to(out_path))
        deliverables["participants_json"] = str(p_json.relative_to(out_path))
    except Exception as e:
        failures.append(f"participants_tsv: {e}")

    # 11. CITATION.{md,tex,html} (NiPreps convention; was methods_manifest.*)
    try:
        m_md = logs_root / "CITATION.md"
        m_tex = logs_root / "CITATION.tex"
        m_html = logs_root / "CITATION.html"
        methods_md_text = _build_methods_manifest(out_path, recipe, policy,
                                                  m_md, m_tex, m_html)
        deliverables["citation_md"] = str(m_md.relative_to(out_path))
        deliverables["citation_tex"] = str(m_tex.relative_to(out_path))
        deliverables["citation_html"] = str(m_html.relative_to(out_path))
    except Exception as e:
        failures.append(f"citation_md: {e}")
        methods_md_text = ""

    # 12. (was sidecar_audit; dropped per audit B11 / F10 — function
    # was misnamed and bids-validator isn't installed.)

    # 12b. Per-subject HTML reports — NOW we have methods_md_text to embed.
    subject_report_paths: list[Path] = []
    for ds, sub in sorted(subjects):
        try:
            p = _build_per_subject_html(
                out_path, ds, sub, records, policy,
                citation_md=methods_md_text,
            )
            if p:
                subject_report_paths.append(p)
        except Exception as e:
            failures.append(f"per_subject {ds}/{sub}: {e}")
    n_subject_reports = len(subject_report_paths)
    fraction = (n_subject_reports / n_subjects) if n_subjects else 0.0

    # 13. release_report.html
    try:
        rr_path = deriv_root / "release_report.html"
        _build_release_report(out_path, subject_report_paths, deliverables, rr_path)
        deliverables["release_report"] = str(rr_path.relative_to(out_path))
    except Exception as e:
        failures.append(f"release_report: {e}")

    # QC classification
    thr = policy.get("qc_thresholds", {})
    pass_min = float(thr.get("pass_min_subject_report_fraction", 0.80))
    warn_min = float(thr.get("warn_min_subject_report_fraction", 0.50))
    if fraction >= pass_min and not failures:
        status = "PASS"
        msg = None
    elif fraction >= warn_min:
        status = "WARN"
        msg = (f"{n_subject_reports}/{n_subjects} per-subject reports "
               f"({fraction*100:.0f}%)" + (f"; {len(failures)} failures" if failures else ""))
    else:
        status = "FAIL"
        msg = (f"only {n_subject_reports}/{n_subjects} per-subject reports "
               f"({fraction*100:.0f}%)")

    metrics = {
        "n_subjects_aggregated": int(n_subjects),
        "n_runs_aggregated": int(n_runs),
        "n_datasets": len({r.get("dataset_key") for r in records}),
        "n_subject_reports": int(n_subject_reports),
        "subject_report_fraction": float(fraction),
        "missing_step_qc_count": 0,
    }

    qc_dir = out_path / "logs" / "S11_qc_aggregation_and_release"
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "step_code": "S11_qc_aggregation_and_release",
        "status": status,
        "failure_message": msg,
        "failure_reasons": failures,
        "deliverables": deliverables,
        "metrics": metrics,
    }, indent=2, default=str))

    from spinalfmriprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult(status, msg, qc_path=qc_path)


def check_S11_qc_aggregation_and_release(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()
    qc_path = out_path / "logs" / "S11_qc_aggregation_and_release" / "qc.json"
    if not qc_path.exists():
        return StepResult("FAIL", f"QC JSON not found: {qc_path}")
    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult("FAIL", f"Failed to read QC JSON: {err}")
    return StepResult(qc.get("status", "UNKNOWN"), qc.get("failure_message"))
