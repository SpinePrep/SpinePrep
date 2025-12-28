#!/usr/bin/env python3
"""
Generate black-background QC HTML for available step outputs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


REPORTLET_LABELS = {
    "centerline_montage": "centerline",
    "cordmask_montage": "cordmask",
    "vertebral_labels_montage": "vertebral labels",
    "rootlets_montage": "rootlets",
    "pam50_reg_overlay": "pam50 reg overlay",
}

def cache_busted_url(rel: str, path: Path) -> str:
    """Append a cache-busting query based on file mtime so browsers reload updated reportlets."""
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return rel
    return f"{rel}?v={mtime_ns}"


def main() -> int:
    work_root = Path("work")
    out_root = work_root / "qc_standalone"
    out_root.mkdir(parents=True, exist_ok=True)

    # Look for datasets in both *_acceptance/* and s2_regression/* patterns
    dataset_dirs = sorted(
        list(work_root.glob("*_acceptance/*")) + list(work_root.glob("s2_regression/*"))
    )
    dataset_dirs = [p for p in dataset_dirs if p.is_dir()]
    datasets = []
    for dataset_dir in dataset_dirs:
        logs_dir = dataset_dir / "logs"
        if not logs_dir.exists():
            continue
        qc_files = sorted(logs_dir.glob("*_qc.json"))
        if not qc_files:
            continue
        dataset = collect_dataset(dataset_dir, qc_files)
        ensure_parent_link(dataset_dir, out_root)
        if dataset["steps"]:
            build_step_pages(dataset, out_root)
        datasets.append(dataset)

    build_reportlet_pages(datasets, out_root)
    build_index(datasets, out_root)
    return 0


def collect_dataset(dataset_dir: Path, qc_files: list[Path]) -> dict:
    dataset_key = dataset_dir.name
    steps = []
    subjects = set()
    for qc_path in qc_files:
        step_code = qc_path.name.replace("_qc.json", "")
        data = json.loads(qc_path.read_text(encoding="utf-8"))
        runs = data.get("runs")
        step = {
            "step": step_code,
            "qc_path": qc_path,
            "status": data.get("status"),
            "failure_message": data.get("failure_message"),
            "runs": [],
            "dataset_qc": data,
        }
        if isinstance(runs, list):
            for run in runs:
                subject = run.get("subject") or "unknown"
                session = run.get("session") or "none"
                subjects.add((subject, session))
                step["runs"].append(run)
        steps.append(step)
    return {
        "dataset_key": dataset_key,
        "dataset_dir": dataset_dir,
        "steps": steps,
        "subjects": sorted(subjects),
    }


def build_index(datasets: list[dict], out_root: Path) -> None:
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\" />",
        "<title>SpinePrep QC</title>",
        "<style>",
        "body { background: #000; color: #e6e6e6; font-family: Arial, sans-serif; }",
        "a { color: #7dcfff; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        ".card { border: 1px solid #333; padding: 12px; margin: 12px 0; }",
        ".muted { color: #999; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>SpinePrep QC</h1>",
        "<p class=\"muted\">Generated from work/*_acceptance and work/s2_regression outputs.</p>",
    ]
    if not datasets:
        lines.append("<p>No QC data found.</p>")
    reportlet_index = collect_reportlet_index(datasets)
    for step_code in sorted(reportlet_index.keys()):
        lines.append(f"<div class=\"card\"><h2>{step_code}</h2>")
        any_links = False
        reportlets = reportlet_index.get(step_code, {})
        if reportlets:
            lines.append("<ul>")
            for key in ordered_reportlet_keys(step_code, reportlets.keys()):
                link = reportlet_page_name(step_code, key)
                label = display_reportlet_key(key)
                lines.append(f"<li><a href=\"{link}\">{label}</a></li>")
                any_links = True
            lines.append("</ul>")
        if not any_links:
            lines.append("<p class=\"muted\">No reportlets found for this step.</p>")
        lines.append("</div>")
    lines.extend(["</body>", "</html>"])
    (out_root / "index.html").write_text("\n".join(lines), encoding="utf-8")


def build_step_pages(dataset: dict, out_root: Path) -> None:
    dataset_key = dataset["dataset_key"]
    dataset_dir = dataset["dataset_dir"]
    for step in dataset["steps"]:
        step_code = step["step"]
        lines = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "<meta charset=\"utf-8\" />",
            f"<title>QC {dataset_key} {step_code}</title>",
            "<style>",
            "body { background: #000; color: #e6e6e6; font-family: Arial, sans-serif; }",
            "a { color: #7dcfff; text-decoration: none; }",
            "a:hover { text-decoration: underline; }",
            ".group { border: 1px solid #333; padding: 12px; margin: 16px 0; }",
            ".reportlet { margin: 10px 0; }",
            ".reportlet img { width: 100%; max-width: 1200px; border: 1px solid #222; }",
            ".subject { margin: 8px 0 20px 0; }",
            ".badge { padding: 2px 6px; border-radius: 4px; background: #333; }",
            ".fail { background: #7f1d1d; }",
            ".pass { background: #14532d; }",
            ".warn { background: #78350f; }",
            ".muted { color: #999; }",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>{dataset_key} — {step_code}</h1>",
            "<p><a href=\"index.html\">Back to index</a></p>",
        ]
        reportlet_groups = group_reportlets(step["runs"])
        if not reportlet_groups:
            lines.append("<p class=\"muted\">No reportlets found for this step.</p>")
        for key in ordered_reportlet_keys(step_code, reportlet_groups.keys()):
            items = reportlet_groups.get(key, [])
            anchor = anchor_id(key)
            lines.append(f"<div class=\"group\"><h2 id=\"{anchor}\">{key}</h2>")
            for item in items:
                subject = item["subject"]
                session = item["session"]
                status = item.get("status", "UNKNOWN")
                badge_class = "pass" if status == "PASS" else "fail" if status == "FAIL" else "warn"
                label = f"{subject} / {session}" if session != "none" else subject
                lines.append(f"<div class=\"subject\"><div>{label} <span class=\"badge {badge_class}\">{status}</span></div>")
                path = resolve_path(dataset_dir, item["rel"])
                if not path.exists():
                    lines.append("<div class=\"muted\">Missing reportlet file.</div></div>")
                    continue
                rel = rel_to_parent_root(path, dataset_dir, out_root)
                bust = cache_busted_url(rel, path)
                lines.append(f"<a href=\"{bust}\"><img src=\"{bust}\" alt=\"{key}\" /></a></div>")
            lines.append("</div>")
        lines.extend(["</body>", "</html>"])
        (out_root / step_page_name(dataset_key, step_code)).write_text(
            "\n".join(lines), encoding="utf-8"
        )


def step_page_name(dataset_key: str, step_code: str) -> str:
    return f"{dataset_key}__step-{step_code}.html"


def reportlet_page_name(step_code: str, reportlet_key: str) -> str:
    return f"step-{step_code}__reportlet-{anchor_id(reportlet_key)}.html"


def display_reportlet_key(reportlet_key: str) -> str:
    return REPORTLET_LABELS.get(reportlet_key, reportlet_key)


def build_reportlet_pages(datasets: list[dict], out_root: Path) -> None:
    reportlet_index = collect_reportlet_index(datasets)
    for step_code, reportlets in reportlet_index.items():
        for reportlet_key, items in reportlets.items():
            label = display_reportlet_key(reportlet_key)
            lines = [
                "<!DOCTYPE html>",
                "<html>",
                "<head>",
                "<meta charset=\"utf-8\" />",
                f"<title>QC {step_code} — {label}</title>",
                "<style>",
                "body { background: #000; color: #e6e6e6; font-family: Arial, sans-serif; }",
                "a { color: #7dcfff; text-decoration: none; }",
                "a:hover { text-decoration: underline; }",
                ".group { border: 1px solid #333; padding: 12px; margin: 16px 0; }",
                ".reportlet img { width: 100%; max-width: 1200px; border: 1px solid #222; }",
                ".reportlet.half { text-align: center; }",
                ".reportlet.half img { width: 50%; max-width: 1200px; border: 1px solid #222; }",
                ".row { display: flex; gap: 12px; }",
                ".row .reportlet { flex: 1; }",
                ".badge { padding: 2px 6px; border-radius: 4px; background: #333; }",
                ".fail { background: #7f1d1d; }",
                ".pass { background: #14532d; }",
                ".warn { background: #78350f; }",
                ".muted { color: #999; }",
                "</style>",
                "</head>",
                "<body>",
                f"<h1>{step_code} — {label}</h1>",
                "<p><a href=\"index.html\">Back to index</a></p>",
            ]
            for item in items:
                dataset_key = item["dataset_key"]
                subject = item["subject"]
                session = item["session"]
                status = item.get("status", "UNKNOWN")
                badge_class = "pass" if status == "PASS" else "fail" if status == "FAIL" else "warn"
                label = f"{subject} / {session}" if session != "none" else subject
                lines.append(f"<div class=\"group\"><div><strong>{dataset_key}</strong></div>")
                lines.append(f"<div>{label} <span class=\"badge {badge_class}\">{status}</span></div>")
                path = resolve_path(item["dataset_dir"], item["rel"])
                if not path.exists():
                    lines.append("<div class=\"muted\">Missing reportlet file.</div></div>")
                    continue
                rel = rel_to_parent_root(path, item["dataset_dir"], out_root)
                bust = cache_busted_url(rel, path)
                lines.append(
                    f"<div class=\"reportlet\"><a href=\"{bust}\"><img src=\"{bust}\" alt=\"{reportlet_key}\" /></a></div></div>"
                )
            lines.extend(["</body>", "</html>"])
            (out_root / reportlet_page_name(step_code, reportlet_key)).write_text(
                "\n".join(lines), encoding="utf-8"
            )


def group_reportlets(runs: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        reportlets = run.get("reportlets") or {}
        subject = run.get("subject") or "unknown"
        session = run.get("session") or "none"
        for key, rel in reportlets.items():
            if not rel:
                continue
            grouped.setdefault(key, []).append(
                {
                    "subject": subject,
                    "session": session,
                    "status": run.get("status", "UNKNOWN"),
                    "rel": rel,
                }
            )
    return grouped


def collect_steps(datasets: list[dict]) -> list[str]:
    steps = set()
    for dataset in datasets:
        for step in dataset["steps"]:
            steps.add(step["step"])
    return sorted(steps)


def collect_reportlet_index(datasets: list[dict]) -> dict[str, dict[str, list[dict]]]:
    index: dict[str, dict[str, list[dict]]] = {}
    for dataset in datasets:
        dataset_key = dataset["dataset_key"]
        dataset_dir = dataset["dataset_dir"]
        for step in dataset["steps"]:
            step_code = step["step"]
            for run in step["runs"]:
                reportlets = run.get("reportlets") or {}
                subject = run.get("subject") or "unknown"
                session = run.get("session") or "none"
                for key, rel in reportlets.items():
                    if not rel:
                        continue
                    index.setdefault(step_code, {}).setdefault(key, []).append(
                        {
                            "dataset_key": dataset_key,
                            "dataset_dir": dataset_dir,
                            "subject": subject,
                            "session": session,
                            "status": run.get("status", "UNKNOWN"),
                            "rel": rel,
                        }
                    )
    return index


def ordered_reportlet_keys(step_code: str, keys) -> list[str]:
    keys = list(keys)
    if step_code == "S2_anat_cordref":
        preferred = [
            "centerline_montage",
            "cordmask_montage",
            "vertebral_labels_montage",
            "rootlets_montage",
            "pam50_reg_overlay",
        ]
        ordered = [k for k in preferred if k in keys]
        ordered.extend([k for k in sorted(keys) if k not in ordered])
        return ordered
    return sorted(keys)


def anchor_id(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")


def resolve_path(dataset_dir: Path, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        return path
    return dataset_dir / rel


def ensure_parent_link(dataset_dir: Path, out_root: Path) -> None:
    parent = dataset_dir.parent
    link = out_root / parent.name
    if link.exists() or link.is_symlink():
        try:
            if link.resolve() == parent.resolve():
                return
        except OSError:
            pass
        try:
            link.unlink()
        except OSError:
            return
    try:
        link.symlink_to(parent.resolve())
    except OSError:
        pass


def rel_to_parent_root(path: Path, dataset_dir: Path, out_root: Path) -> str:
    parent = dataset_dir.parent
    try:
        rel = path.resolve().relative_to(parent.resolve())
        return f"{parent.name}/{rel.as_posix()}"
    except ValueError:
        return os.path.relpath(path.resolve(), out_root)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


if __name__ == "__main__":
    raise SystemExit(main())
