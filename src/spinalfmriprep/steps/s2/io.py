"""I/O utilities: StepResult, JSON/JSONL, paths, file copy, subprocess execution."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2
from typing import Optional

import nibabel as nib


@dataclass
class StepResult:
    status: str
    failure_message: Optional[str]
    runs_path: Optional[Path] = None
    qc_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run_command(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.CalledProcessError as err:
        output = "\n".join(part for part in [err.stdout, err.stderr] if part)
        return False, output.strip()
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    return True, output.strip()


def _is_command_not_found(message: str) -> bool:
    return "Command not found" in message or "not found" in message.lower()


def _get_sct_version() -> Optional[str]:
    ok, output = _run_command(["sct_version"])
    if not ok:
        return None
    return output.strip() or None


# ---------------------------------------------------------------------------
# JSONL / JSON persistence
# ---------------------------------------------------------------------------

def _write_runs_jsonl(path: Path, runs: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for run in runs:
            f.write(json.dumps(run, default=str))
            f.write("\n")


def _read_runs_jsonl(path: Path) -> list[dict]:
    runs = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            runs.append(json.loads(line))
    return runs


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _append_metrics(path: Path, dataset_key: Optional[str], runs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for run in runs:
            record = _metrics_record(dataset_key, run)
            if record is None:
                continue
            f.write(json.dumps(record))
            f.write("\n")


def _metrics_record(dataset_key: Optional[str], run: dict) -> Optional[dict]:
    metrics = run.get("metrics") or {}
    labels_info = run.get("labels") or {}
    label_metrics = labels_info.get("metrics") or {}
    if not metrics:
        return None
    return {
        "step": "S2_anat_cordref",
        "dataset_key": dataset_key,
        "subject": run.get("subject"),
        "session": run.get("session"),
        "status": run.get("status"),
        "cordref_modality": run.get("cordref_modality"),
        "cord_length_mm": metrics.get("cord_length_mm"),
        "cord_volume_mm3": metrics.get("cord_volume_mm3"),
        "csa_mean_mm2": metrics.get("csa_mean_mm2"),
        "csa_min_mm2": metrics.get("csa_min_mm2"),
        "csa_max_mm2": metrics.get("csa_max_mm2"),
        "label_count": label_metrics.get("label_count"),
        "disc_label_count": label_metrics.get("disc_label_count"),
        "rootlets_status": (run.get("rootlets") or {}).get("status"),
        "registration_selected": (run.get("registration") or {}).get("selected"),
    }


# ---------------------------------------------------------------------------
# File copy helpers
# ---------------------------------------------------------------------------

def _copy_nifti(source: Path, dest: Path) -> None:
    img = nib.load(source)
    nib.save(img, dest)


def _copy_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, dest)


# ---------------------------------------------------------------------------
# Failure record helper
# ---------------------------------------------------------------------------

def _fail_run(subject: str, session: Optional[str], run_id: str, message: str) -> dict:
    return {
        "subject": subject,
        "session": session,
        "status": "FAIL",
        "failure_message": message,
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Command-line formatting
# ---------------------------------------------------------------------------

def _format_command_line(
    dataset_key: Optional[str],
    datasets_local: Optional[Path],
    bids_root: Optional[Path],
    out: Optional[Path],
) -> str:
    parts = ["poetry", "run", "spinalfmriprep", "run", "S2_anat_cordref"]
    if dataset_key:
        parts.extend(["--dataset-key", str(dataset_key)])
    if datasets_local:
        parts.extend(["--datasets-local", str(datasets_local)])
    if bids_root:
        parts.extend(["--bids-root", str(bids_root)])
    if out:
        parts.extend(["--out", str(out)])
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Path formatting helpers
# ---------------------------------------------------------------------------

def _derivatives_anat_dir(out_root: Path, subject: str, session: Optional[str], dataset_key: Optional[str] = None) -> Path:
    """
    Return the derivatives anat directory path.

    If dataset_key is provided, includes it in the path for multi-dataset workflows:
    out_root/derivatives/spinalfmriprep/{dataset_key}/sub-XX/[ses-XX/]anat

    If dataset_key is None, uses the traditional path:
    out_root/derivatives/spinalfmriprep/sub-XX/[ses-XX/]anat
    """
    if dataset_key:
        base = out_root / "derivatives" / "spinalfmriprep" / dataset_key / f"sub-{subject}"
    else:
        base = out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}"

    if session:
        return base / f"ses-{session}" / "anat"
    return base / "anat"


def _format_derivative_name(subject: str, session: Optional[str], desc: str, suffix: str) -> str:
    if session:
        return f"sub-{subject}_ses-{session}_{desc}_{suffix}.nii.gz"
    return f"sub-{subject}_{desc}_{suffix}.nii.gz"


def _format_run_id(subject: str, session: Optional[str]) -> str:
    if session:
        return f"sub-{subject}_ses-{session}"
    return f"sub-{subject}_ses-none"


def _relpath(path: Optional[Path], out_root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.relative_to(out_root))
    except ValueError:
        return str(path)


def _derivatives_figures_dir(out_root: Path, subject: Optional[str], session: Optional[str], dataset_key: Optional[str] = None) -> Path:
    """
    Return the derivatives figures directory path.

    If dataset_key is provided, includes it in the path for multi-dataset workflows:
    out_root/derivatives/spinalfmriprep/{dataset_key}/sub-XX/[ses-XX/]figures

    If dataset_key is None, uses the traditional path:
    out_root/derivatives/spinalfmriprep/sub-XX/[ses-XX/]figures
    """
    if dataset_key:
        if session:
            return out_root / "derivatives" / "spinalfmriprep" / dataset_key / f"sub-{subject}" / f"ses-{session}" / "figures"
        return out_root / "derivatives" / "spinalfmriprep" / dataset_key / f"sub-{subject}" / "figures"
    else:
        if session:
            return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "figures"
        return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "figures"


def _format_reportlet_name(
    subject: Optional[str],
    session: Optional[str],
    desc: str,
    ext: str = "png",
) -> str:
    if session:
        return f"sub-{subject}_ses-{session}_desc-{desc}.{ext}"
    return f"sub-{subject}_desc-{desc}.{ext}"


def _abs_path(out_root: Path, rel: Optional[str]) -> Optional[Path]:
    if rel is None:
        return None
    path = Path(rel)
    if path.is_absolute():
        return path
    return out_root / rel


def _derivatives_xfm_dir(out_root: Path, subject: str, session: Optional[str]) -> Path:
    if session:
        return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / f"ses-{session}" / "xfm"
    return out_root / "derivatives" / "spinalfmriprep" / f"sub-{subject}" / "xfm"


def _format_xfm_name(subject: str, session: Optional[str], suffix: str) -> str:
    if session:
        return f"sub-{subject}_ses-{session}_{suffix}.nii.gz"
    return f"sub-{subject}_{suffix}.nii.gz"
