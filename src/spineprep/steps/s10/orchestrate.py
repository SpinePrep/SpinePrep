"""Public API for S10 QC aggregation + release readiness.

S10 is global: walks the entire chain, emits release deliverables at
`derivatives/spineprep/` (top level) plus per-subject HTML reports.
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
    _build_references_bib,
    _build_reproducibility_receipt,
    _build_run_inventory,
    _flat_run_records,
    _render_group_dashboard_html,
    _walk_chain_qc,
)
from . import reports

logger = logging.getLogger(__name__)

# Per-run participant steps a completed run should have a QC record for.
# S1 is dataset-level and S2 is anatomy-level, so neither is per-run.
_PARTICIPANT_STEPS = ("S3", "S4", "S5", "S6", "S7", "S8", "S9")


def _run_key(rec: dict) -> tuple:
    """Identity of a run. Keyed on (dataset, subject, session, run_id) because
    subject labels collide across datasets -- sub-01 exists in six of them."""
    return (rec.get("dataset_key"), rec.get("subject"),
            rec.get("session"), rec.get("run_id"))


def _rollup_run_status(records: list[dict]) -> dict[str, int]:
    """Worst per-run status across the participant steps, counted by verdict.

    A run is FAIL if any step FAILed, WARN if any WARNed, else PASS. This is
    what the release actually contains, and until 2026-07-19 it never reached
    S10's verdict at all.
    """
    worst: dict[tuple, str] = {}
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    for rec in records:
        if rec.get("step") not in _PARTICIPANT_STEPS:
            continue
        if not rec.get("run_id"):
            continue
        st = rec.get("status")
        if st not in rank:
            continue
        k = _run_key(rec)
        if k not in worst or rank[st] > rank[worst[k]]:
            worst[k] = st
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for st in worst.values():
        counts[st] += 1
    return counts


def _count_missing_step_qc(records: list[dict]) -> int:
    """(run, step) pairs with no QC record where one is expected.

    A run is only expected to have records up to the last step it reached: once
    a step FAILs, downstream steps legitimately skip it. So this counts gaps
    BELOW a run's high-water mark, which is what "missing QC" should mean --
    a step that silently produced nothing, not a step correctly skipped.
    """
    seen: dict[tuple, set] = {}
    for rec in records:
        step = rec.get("step")
        if step not in _PARTICIPANT_STEPS or not rec.get("run_id"):
            continue
        seen.setdefault(_run_key(rec), set()).add(step)
    missing = 0
    for steps in seen.values():
        reached = [i for i, s in enumerate(_PARTICIPANT_STEPS) if s in steps]
        if not reached:
            continue
        for i in range(max(reached) + 1):
            if _PARTICIPANT_STEPS[i] not in steps:
                missing += 1
    return missing


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str] = None
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


def run_S10(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
    batch_workers: int = 1,
) -> StepResult:
    """S10 is global. dataset_key is ignored for aggregation but
    accepted for CLI uniformity. Emits at derivatives/spineprep/.
    """
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()

    policy_path = Path("policy/S10_qc_aggregation_and_release.yaml")
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
    # workfolder. When derivatives is a symlink, S10 owns
    # ``out_dir/release/`` instead — the upstream tree stays immutable.
    deriv_link = out_path / "derivatives"
    if deriv_link.is_symlink():
        deriv_root = out_path / "release"
    else:
        deriv_root = deriv_link / "spineprep"
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
    # cohort FC summary removed 2026-06-11 with the former S10 (ROI/connectivity, analyst-owned).

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
    participants_rows: list[dict] = []
    try:
        p_tsv = deriv_root / "participants.tsv"
        p_json = deriv_root / "participants.json"
        n_part = _build_participants_tsv(out_path, records, policy, p_tsv, p_json)
        deliverables["participants_tsv"] = str(p_tsv.relative_to(out_path))
        deliverables["participants_json"] = str(p_json.relative_to(out_path))
        # Read the rows back so the group reports can render the inclusion table
        # (avoids recomputing the include/review logic in two places).
        try:
            import pandas as _pd
            participants_rows = _pd.read_csv(p_tsv, sep="\t").to_dict("records")
        except Exception:
            participants_rows = []
    except Exception as e:
        failures.append(f"participants_tsv: {e}")

    # 11. CITATION.{md,tex,html} (NiPreps convention; was methods_manifest.*)
    citation_html = ""
    try:
        m_md = logs_root / "CITATION.md"
        m_tex = logs_root / "CITATION.tex"
        m_html = logs_root / "CITATION.html"
        _build_methods_manifest(out_path, recipe, policy, m_md, m_tex, m_html)
        deliverables["citation_md"] = str(m_md.relative_to(out_path))
        deliverables["citation_tex"] = str(m_tex.relative_to(out_path))
        deliverables["citation_html"] = str(m_html.relative_to(out_path))
        # Reuse the already-rendered HTML body for embedding in subject reports
        # (deterministic; no per-subject pandoc re-run).
        try:
            citation_html = m_html.read_text(encoding="utf-8")
        except Exception:
            citation_html = ""
    except Exception as e:
        failures.append(f"citation_md: {e}")

    # 12. Subject-level reports (reports.py — figure-first per-run cards).
    #     subject_reports keyed (dataset, subject) for the overview index.
    subject_reports: dict[tuple, Path] = {}
    for ds, sub in sorted(subjects):
        try:
            p = reports.build_subject_report(
                out_path, deriv_root, ds, sub, records, policy, recipe,
                citation_html=citation_html,
            )
            if p:
                subject_reports[(ds, sub)] = p
        except Exception as e:
            failures.append(f"subject_report {ds}/{sub}: {e}")
    n_subject_reports = len(subject_reports)
    fraction = (n_subject_reports / n_subjects) if n_subjects else 0.0

    # 12b. Group-level reports — one per dataset (Principle 10: not pooled).
    group_reports: dict[str, Path] = {}
    datasets = sorted({r.get("dataset_key") for r in records if r.get("dataset_key")})
    for ds in datasets:
        try:
            ds_subjects = {s: p for (d, s), p in subject_reports.items() if d == ds}
            gp = reports.build_group_report(
                out_path, deriv_root, ds, records, policy, recipe,
                participants_rows, ds_subjects,
            )
            if gp:
                group_reports[ds] = gp
        except Exception as e:
            failures.append(f"group_report {ds}: {e}")

    # 13. Cross-dataset overview (release_report.html)
    try:
        rr_path = deriv_root / "release_report.html"
        reports.build_overview(out_path, deriv_root, records, group_reports,
                               subject_reports, deliverables, recipe, rr_path)
        deliverables["release_report"] = str(rr_path.relative_to(out_path))
    except Exception as e:
        failures.append(f"release_report: {e}")

    # Upstream QC rollup. S10's verdict used to depend only on whether the HTML
    # rendered, so the release could -- and did -- report PASS while its own
    # inventory held 18 FAILed and 410 WARN runs out of 469. A release gate that
    # certifies formatting rather than data is not a QC gate. These counts now
    # enter the verdict and are published alongside it.
    run_status = _rollup_run_status(records)
    n_runs_total = sum(run_status.values())
    n_runs_failed = run_status.get("FAIL", 0)
    n_runs_warn = run_status.get("WARN", 0)
    n_runs_pass = run_status.get("PASS", 0)
    fail_frac = (n_runs_failed / n_runs_total) if n_runs_total else 0.0

    # missing_step_qc_count was previously the literal 0 -- published as a
    # measurement while nothing computed it, and its two policy thresholds were
    # never read. It now counts (run, step) pairs where a run that reached the
    # chain has no QC record for a participant step it should have.
    missing_qc = _count_missing_step_qc(records)
    missing_frac = (missing_qc / (n_runs_total * len(_PARTICIPANT_STEPS))
                    if n_runs_total else 0.0)

    thr = policy.get("qc_thresholds", {})
    pass_min = float(thr.get("pass_min_subject_report_fraction", 0.80))
    warn_min = float(thr.get("warn_min_subject_report_fraction", 0.50))
    pass_max_fail = float(thr.get("pass_max_run_fail_fraction", 0.05))
    warn_max_fail = float(thr.get("warn_max_run_fail_fraction", 0.20))
    pass_max_missing = float(thr.get("pass_max_missing_qc_fraction", 0.05))

    reasons: list[str] = list(failures)
    if fail_frac > warn_max_fail:
        reasons.append(f"{n_runs_failed}/{n_runs_total} runs FAILed upstream "
                       f"({fail_frac*100:.0f}% > {warn_max_fail*100:.0f}%)")
        status = "FAIL"
    elif fail_frac > pass_max_fail:
        reasons.append(f"{n_runs_failed}/{n_runs_total} runs FAILed upstream "
                       f"({fail_frac*100:.0f}% > {pass_max_fail*100:.0f}%)")
        status = "WARN"
    else:
        status = "PASS"

    if missing_frac > pass_max_missing:
        reasons.append(f"{missing_qc} missing step QC record(s) "
                       f"({missing_frac*100:.0f}% > {pass_max_missing*100:.0f}%)")
        if status == "PASS":
            status = "WARN"

    if fraction < warn_min:
        reasons.append(f"only {n_subject_reports}/{n_subjects} per-subject "
                       f"reports ({fraction*100:.0f}%)")
        status = "FAIL"
    elif fraction < pass_min or failures:
        if fraction < pass_min:
            reasons.append(f"{n_subject_reports}/{n_subjects} per-subject "
                           f"reports ({fraction*100:.0f}%)")
        if status == "PASS":
            status = "WARN"

    msg = "; ".join(reasons) if reasons else None
    failures = reasons

    metrics = {
        "n_subjects_aggregated": int(n_subjects),
        "n_runs_aggregated": int(n_runs),
        "n_datasets": len({r.get("dataset_key") for r in records}),
        "n_subject_reports": int(n_subject_reports),
        "subject_report_fraction": float(fraction),
        "missing_step_qc_count": int(missing_qc),
        # Run-level rollup: what the release actually contains.
        "n_runs_pass": int(n_runs_pass),
        "n_runs_warn": int(n_runs_warn),
        "n_runs_failed": int(n_runs_failed),
        "run_fail_fraction": float(fail_frac),
    }

    qc_dir = out_path / "logs" / "S10_qc_aggregation_and_release"
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_path = qc_dir / "qc.json"
    qc_path.write_text(json.dumps({
        "step_code": "S10_qc_aggregation_and_release",
        "status": status,
        "failure_message": msg,
        "failure_reasons": failures,
        "deliverables": deliverables,
        "metrics": metrics,
    }, indent=2, default=str))

    from spineprep.qc_dashboard import generate_dashboard_safe
    generate_dashboard_safe(out_path)

    return StepResult(status, msg, qc_path=qc_path)


def check_S10_qc_aggregation_and_release(
    dataset_key: Optional[str] = None,
    datasets_local: Optional[str] = None,
    out: Optional[str] = None,
) -> StepResult:
    if not out:
        return StepResult("FAIL", "--out is required")
    out_path = Path(out).resolve()
    qc_path = out_path / "logs" / "S10_qc_aggregation_and_release" / "qc.json"
    if not qc_path.exists():
        return StepResult("FAIL", f"QC JSON not found: {qc_path}")
    try:
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    except Exception as err:
        return StepResult("FAIL", f"Failed to read QC JSON: {err}")
    return StepResult(qc.get("status", "UNKNOWN"), qc.get("failure_message"))
