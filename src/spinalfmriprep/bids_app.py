"""Standard BIDS-App entrypoint for SpinalfMRIprep.

Conformant interface (BIDS-Apps convention, Gorgolewski 2017):

    spinalfmriprep <bids_dir> <output_dir> <analysis_level> [options]

- ``participant`` level runs the per-subject chain S1..S9 on ``bids_dir``,
  writing BIDS-Derivatives + QC into ``output_dir``.
- ``group`` level runs S10 (cross-subject QC aggregation + release reports).

This is a thin wrapper over the existing per-step CLI: every step runs into the
SAME ``output_dir`` tree, so each step finds its predecessor's outputs there (no
scope/workfolder symlink machinery needed). The dataset need not be registered
in ``policy/datasets.yaml`` — it runs ad-hoc via ``--bids-root`` (S1 tolerates a
missing policy spec; see steps/s1/validate.py).

Gates novelty claim N1 (`.claude/specs/v1-claims-ledger.md`).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional

# The per-subject chain (participant level). S10 is the group level.
PARTICIPANT_STEPS = [
    "S1_input_verify",
    "S2_anat_cordref",
    "S2B_func_denoise",
    "S3_func_init_and_crop",
    "S4_func_motion_correction",
    "S5_func_distortion_correction",
    "S6_func_to_anat_registration",
    "S7_template_normalization",
    "S8_confounds_and_physio_regressors",
    "S9_primary_functional_derivatives",
]
GROUP_STEP = "S10_qc_aggregation_and_release"


def _dataset_key_for(bids_dir: Path) -> str:
    """Stable ad-hoc dataset key derived from the bids_dir folder name."""
    name = re.sub(r"[^A-Za-z0-9]+", "_", bids_dir.name).strip("_").lower()
    return f"bidsapp_{name or 'dataset'}"


def _validate_bids_input(
    bids_dir: Path, participant_label: Optional[list[str]] = None
) -> tuple[list[str], list[str]]:
    """Fast front-door check of the BIDS input, before any heavy processing.

    Catches the malformations that otherwise surface as cryptic mid-chain
    crashes, and reports ALL of them at once with actionable messages. This is a
    lightweight structural validator (not the full BIDS validator): it verifies
    the dataset has subjects, that requested participants exist, and that each
    participant has the func + anat the cord pipeline needs and that those NIfTIs
    are readable. Returns (errors, warnings); a non-empty ``errors`` should stop
    the run (unless --skip-bids-validator).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not (bids_dir / "dataset_description.json").exists():
        warnings.append(
            "dataset_description.json not found at the dataset root "
            "(BIDS requires it; processing will still be attempted)."
        )

    all_subs = sorted(p.name for p in bids_dir.glob("sub-*") if p.is_dir())
    if not all_subs:
        errors.append(
            f"No 'sub-*' directories found under {bids_dir} — this does not look "
            "like a BIDS dataset. Check the path, or pass --skip-bids-validator."
        )
        return errors, warnings

    if participant_label:
        want = [f"sub-{lab.replace('sub-', '')}" for lab in participant_label]
        missing = [s for s in want if s not in all_subs]
        if missing:
            preview = ", ".join(all_subs[:10]) + ("…" if len(all_subs) > 10 else "")
            errors.append(
                f"Requested --participant-label not found: {', '.join(missing)}. "
                f"Available subjects: {preview}"
            )
        subs = [s for s in want if s in all_subs]
    else:
        subs = all_subs

    try:
        import nibabel as nib  # noqa
    except Exception:
        nib = None  # header check becomes a size-only check

    for sub in subs:
        sd = bids_dir / sub
        bolds = [p for p in sd.rglob("*_bold.nii*") if "/func/" in p.as_posix() + "/"]
        anats = [
            p for p in sd.rglob("*.nii*")
            if "/anat/" in p.as_posix() + "/"
            and any(t in p.name.lower() for t in ("t2w", "t1w", "t2star", "t2s"))
        ]
        if not bolds:
            errors.append(
                f"{sub}: no functional BOLD found (expected sub-*/[ses-*/]func/"
                "*_bold.nii[.gz]) — nothing to preprocess."
            )
        if not anats:
            errors.append(
                f"{sub}: no anatomical image found (expected sub-*/[ses-*/]anat/"
                "*_T2w|T1w|T2star.nii[.gz]) — S2 cord reference needs one."
            )
        for f in bolds + anats:
            try:
                empty = f.stat().st_size == 0
            except OSError:
                errors.append(f"{sub}: cannot stat {f.name}.")
                continue
            if empty:
                errors.append(f"{sub}: {f.name} is empty (0 bytes).")
            elif nib is not None:
                try:
                    nib.load(str(f)).header  # cheap: header only, no data load
                except Exception as exc:
                    errors.append(
                        f"{sub}: {f.name} is not a readable NIfTI "
                        f"({type(exc).__name__})."
                    )
        if bolds and not list(sd.rglob("*_physio.tsv*")):
            warnings.append(
                f"{sub}: no physio (*_physio.tsv.gz) — RETROICOR physiological "
                "regressors (S8) will be skipped for this subject."
            )

    warnings.extend(_acquisition_envelope_warnings(bids_dir, subs))
    return errors, warnings


def _acquisition_envelope_warnings(
    bids_dir: Path, subs: list[str]
) -> list[str]:
    """Warn when the acquisition falls outside the validated envelope.

    SpinalfMRIprep is validated on cervical-cord EPI-BOLD at 3T. We warn on what
    the JSON sidecars reliably carry — field strength and (leniently) a clearly
    non-EPI sequence. Region (cervical vs thoracic/lumbar/brain) is NOT reliably
    detectable from sidecars, so it stays a documented-envelope note; the covered
    vertebral levels are surfaced by the S2/S10 QC reports instead.
    """
    import json

    warnings: list[str] = []
    seen_field: set = set()
    for sub in subs:
        sd = bids_dir / sub
        sidecars = sorted(p for p in sd.rglob("*_bold.json")
                          if "/func/" in p.as_posix() + "/")
        if not sidecars:
            continue
        try:
            meta = json.loads(sidecars[0].read_text())
        except Exception:
            continue
        fs = meta.get("MagneticFieldStrength")
        if isinstance(fs, (int, float)) and not (2.7 <= float(fs) <= 3.3):
            key = round(float(fs), 1)
            if key not in seen_field:
                seen_field.add(key)
                warnings.append(
                    f"field strength {key} T is outside the validated 3 T envelope "
                    f"(e.g. {sub}); defaults are 3 T-tuned — review results.")
        seq = str(meta.get("ScanningSequence", "")).upper()
        if seq and "EP" not in seq:
            warnings.append(
                f"{sub}: ScanningSequence '{meta.get('ScanningSequence')}' does not "
                "look like EPI; SpinalfMRIprep is validated on EPI-BOLD.")
    return warnings


def _step_run_outcome(output_dir: Path, step: str) -> Optional[tuple[int, int]]:
    """Read a step's per-run verdicts from its aggregate qc.json.

    Returns (n_survived, n_failed) where survived = PASS or WARN, or None if no
    aggregate qc.json is found (the step crashed rather than judged runs). Used for
    per-subject failure isolation: a step that ran and judged runs should not halt
    the chain just because some runs failed QC — the survivors flow downstream.
    """
    import glob
    import json

    logs = output_dir / "logs"
    candidates = [logs / f"{step}_qc.json"]
    candidates += [Path(p) for p in glob.glob(str(logs / step / "**" / "qc.json"),
                                              recursive=True)]
    for cand in candidates:
        try:
            data = json.loads(Path(cand).read_text())
        except Exception:
            continue
        runs = data.get("runs")
        if not isinstance(runs, list):
            continue
        survived = sum(1 for r in runs if r.get("status") in ("PASS", "WARN"))
        failed = sum(1 for r in runs if r.get("status") == "FAIL")
        return survived, failed
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spinalfmriprep",
        description="SpinalfMRIprep — BIDS-App for spinal-cord fMRI preprocessing.",
    )
    p.add_argument("bids_dir", type=Path,
                   help="Root of the BIDS dataset to process.")
    p.add_argument("output_dir", type=Path,
                   help="Output directory for BIDS-Derivatives + QC reports.")
    p.add_argument("analysis_level", choices=["participant", "group"],
                   help="'participant' runs S1..S9; 'group' runs S10 aggregation.")
    p.add_argument("--participant-label", "--participant_label", nargs="+",
                   default=None, dest="participant_label",
                   help="Subject label(s) to process (without 'sub-'). "
                        "Default: all subjects in bids_dir.")
    p.add_argument("--batch-workers", type=int, default=1, dest="batch_workers",
                   help="Per-step subject/run parallelism.")
    p.add_argument("--skip-bids-validator", action="store_true",
                   help="Skip the built-in input validation (subjects present, "
                        "func + anat present and readable). Bypass at your own risk.")
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    return p


def run_bids_app(
    bids_dir: Path,
    output_dir: Path,
    analysis_level: str,
    participant_label: Optional[list[str]] = None,
    batch_workers: int = 1,
    skip_bids_validator: bool = False,
) -> int:
    """Drive the chain in-process via the per-step CLI. Returns an exit code."""
    from spinalfmriprep import cli  # in-process: no PATH/poetry dependency

    bids_dir = Path(bids_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if not bids_dir.is_dir():
        print(f"ERROR: bids_dir does not exist: {bids_dir}")
        return 2

    # Front-door input validation (participant level only; group aggregates
    # existing outputs, not the raw BIDS inputs). Fails fast with actionable
    # messages instead of a cryptic mid-chain crash.
    if analysis_level == "participant":
        if skip_bids_validator:
            print("[bids-app] --skip-bids-validator: skipping input checks.")
        else:
            errors, warnings = _validate_bids_input(bids_dir, participant_label)
            for w in warnings:
                print(f"[bids-app] WARNING: {w}")
            if errors:
                print("[bids-app] input validation FAILED:")
                for e in errors:
                    print(f"  ERROR: {e}")
                print("[bids-app] Fix the above, or pass --skip-bids-validator "
                      "to bypass these checks.")
                return 2
            print("[bids-app] input validation passed.")

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_key = _dataset_key_for(bids_dir)

    if participant_label and analysis_level == "participant":
        # Honor --participant-label without touching the steps: build a filtered
        # BIDS view (symlink dataset_description.json + only the requested
        # sub-XX dirs) and run the chain against that. group level ignores it
        # (it aggregates whatever is already in output_dir).
        import os as _os
        import shutil
        view = output_dir / ".bids_view"
        if view.exists():
            shutil.rmtree(view)
        view.mkdir(parents=True)
        # top-level metadata files
        for f in list(bids_dir.glob("*.json")) + list(bids_dir.glob("*.tsv")):
            (view / f.name).symlink_to(f.resolve())

        def _mirror(src: Path, dst: Path) -> None:
            # Mirror the directory tree with FILE-level symlinks so S1's rglob
            # (which does not descend symlinked dirs) discovers every file.
            dst.mkdir(parents=True, exist_ok=True)
            for entry in src.iterdir():
                if entry.is_dir():
                    _mirror(entry, dst / entry.name)
                else:
                    (dst / entry.name).symlink_to(entry.resolve())

        n = 0
        for lab in participant_label:
            sub = f"sub-{lab.replace('sub-', '')}"
            src = bids_dir / sub
            if src.is_dir():
                _mirror(src, view / sub)
                n += 1
        if n == 0:
            print(f"[bids-app] ERROR: none of --participant-label {participant_label} "
                  f"found under {bids_dir}")
            return 2
        print(f"[bids-app] filtered to {n} participant(s): {participant_label}")
        bids_dir = view

    # Machine-readable run manifest (written at every exit) for pipeline integration.
    manifest: dict = {"analysis_level": analysis_level, "dataset_key": dataset_key,
                      "steps": [], "status": "running", "exit_code": None}

    def _finish(status: str, code: int) -> int:
        manifest["status"] = status
        manifest["exit_code"] = code
        try:
            (output_dir / "spinalfmriprep_run_manifest.json").write_text(
                __import__("json").dumps(manifest, indent=2))
        except Exception:
            pass
        return code

    steps = PARTICIPANT_STEPS if analysis_level == "participant" else [GROUP_STEP]
    for step in steps:
        argv = ["run", step, "--out", str(output_dir),
                "--batch-workers", str(batch_workers)]
        if step != GROUP_STEP:
            # group level aggregates whatever is already in output_dir; the
            # per-subject steps need the input dataset.
            argv += ["--bids-root", str(bids_dir), "--dataset-key", dataset_key]
        print(f"[bids-app] {analysis_level}: {step}", flush=True)
        rc = cli.main(argv)

        # Group level: a non-zero rc is fatal (nothing to isolate).
        if step == GROUP_STEP:
            manifest["steps"].append({"step": step, "rc": rc})
            if rc not in (0, None):
                print(f"[bids-app] {step} failed (rc={rc}); stopping.")
                return _finish("group_failed", int(rc))
            continue

        # Participant level: per-subject failure isolation. A step reports FAIL
        # (rc=1) whenever ANY run fails QC; that must NOT halt the other subjects.
        # Continue as long as the step judged at least one surviving run; stop only
        # on a true crash (no qc.json) or zero survivors (nothing left downstream).
        outcome = _step_run_outcome(output_dir, step)
        if outcome is None:
            manifest["steps"].append({"step": step, "rc": rc, "crashed": True})
            print(f"[bids-app] step {step} crashed (rc={rc}; no per-run QC written); "
                  f"stopping.")
            return _finish("crashed", int(rc) if rc not in (0, None) else 1)
        survived, failed = outcome
        manifest["steps"].append({"step": step, "rc": rc,
                                  "survived": survived, "failed": failed})
        if failed:
            print(f"[bids-app] {step}: {survived} run(s) ok, {failed} failed QC "
                  f"(attrited; survivors continue).")
        if survived == 0:
            print(f"[bids-app] step {step}: all runs failed QC — nothing to continue; "
                  f"stopping. See the QC reports for per-run reasons.")
            return _finish("all_runs_failed", 1)
    print(f"[bids-app] {analysis_level} level complete -> {output_dir}")
    return _finish("complete", 0)


def main_bids_app(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "version", False):
        from spinalfmriprep import __version__ as v  # noqa
        print(v)
        return 0
    return run_bids_app(
        bids_dir=args.bids_dir,
        output_dir=args.output_dir,
        analysis_level=args.analysis_level,
        participant_label=args.participant_label,
        batch_workers=args.batch_workers,
        skip_bids_validator=args.skip_bids_validator,
    )
