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
                   help="Accepted for BIDS-App convention (no external validator is run).")
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    return p


def run_bids_app(
    bids_dir: Path,
    output_dir: Path,
    analysis_level: str,
    participant_label: Optional[list[str]] = None,
    batch_workers: int = 1,
) -> int:
    """Drive the chain in-process via the per-step CLI. Returns an exit code."""
    from spinalfmriprep import cli  # in-process: no PATH/poetry dependency

    bids_dir = Path(bids_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if not bids_dir.is_dir():
        print(f"ERROR: bids_dir does not exist: {bids_dir}")
        return 2
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
        if rc not in (0, None):
            print(f"[bids-app] step {step} failed (rc={rc}); stopping.")
            return int(rc)
    print(f"[bids-app] {analysis_level} level complete -> {output_dir}")
    return 0


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
    )
