"""
SpinePrep command line interface.

Implements S0_SETUP run/check for bootstrap policy validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from importlib import metadata

from spineprep.S0_setup import check_S0_setup, run_S0_setup
from spineprep.S2_anat_cordref import StepResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spineprep", description="SpinePrep CLI")
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    subparsers = parser.add_subparsers(dest="command", required=False)

    run_parser = subparsers.add_parser("run", help="Run a pipeline step")
    _add_S0_arguments(run_parser)
    _add_S1_arguments(run_parser)

    check_parser = subparsers.add_parser("check", help="Check a pipeline step without writing outputs")
    _add_S0_arguments(check_parser)
    _add_S1_arguments(check_parser)

    return parser


def _add_S0_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "step",
        choices=["S0_SETUP", "S1_input_verify", "S2_anat_cordref"],
        help="Pipeline step code",
    )
    subparser.add_argument(
        "--project-root",
        required=False,
        type=Path,
        help="Project root containing policy/ and logs/ folders (S0 only)",
    )


def _add_S1_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--dataset-key",
        help="Dataset key from policy/datasets.yaml (S1_input_verify/S2_anat_cordref)",
    )
    subparser.add_argument(
        "--dataset-keys",
        nargs="+",
        help="Multiple dataset keys for batch processing (S2_anat_cordref only)",
    )
    subparser.add_argument(
        "--datasets-local",
        type=Path,
        help="Path to datasets_local.yaml mapping dataset keys to local BIDS roots (S1_input_verify/S2_anat_cordref)",
    )
    subparser.add_argument(
        "--bids-root",
        type=Path,
        help="Explicit BIDS root (overrides datasets-local mapping) (S1_input_verify/S2_anat_cordref)",
    )
    subparser.add_argument(
        "--out",
        type=Path,
        help="Output root for step artifacts (S1_input_verify/S2_anat_cordref)",
    )
    subparser.add_argument(
        "--reportlets-only",
        action="store_true",
        help="Regenerate only QC reportlets from existing outputs (skip processing)",
    )
    subparser.add_argument(
        "--batch-workers",
        type=int,
        default=32,
        help="Number of datasets to process in parallel (S2_anat_cordref batch only, default: 32)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        try:
            version = metadata.version("spineprep")
        except metadata.PackageNotFoundError:
            version = "unknown"
        print(version)
        return 0

    if not args.command:
        parser.error("No command provided.")
        return 2

    step: str = args.step

    if args.command == "run":
        if step == "S0_SETUP":
            if args.project_root is None:
                parser.error("--project-root is required for S0_SETUP")
                return 2
            result = run_S0_setup(args.project_root, step)
        elif step == "S1_input_verify":
            result = _run_S1(args)
        elif step == "S2_anat_cordref":
            result = _run_S2(args)
        else:
            parser.error(f"Unsupported step: {step}")
            return 2
    elif args.command == "check":
        if step == "S0_SETUP":
            if args.project_root is None:
                parser.error("--project-root is required for S0_SETUP")
                return 2
            result = check_S0_setup(args.project_root, step)
        elif step == "S1_input_verify":
            result = _check_S1(args)
        elif step == "S2_anat_cordref":
            result = _check_S2(args)
        else:
            parser.error(f"Unsupported step: {step}")
            return 2
    else:
        parser.error(f"Unknown command: {args.command}")
        return 2

    # Print a compact summary for humans.
    summary = {"status": result.status, "failure_message": result.failure_message}
    print(json.dumps(summary, indent=2))

    return 0 if result.status in {"PASS", "WARN"} else 1


def _run_S1(args):
    from spineprep.S1_input_verify import run_S1_input_verify

    return run_S1_input_verify(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        bids_root=args.bids_root,
        out=args.out,
    )


def _check_S1(args):
    from spineprep.S1_input_verify import check_S1_input_verify

    return check_S1_input_verify(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        bids_root=args.bids_root,
        out=args.out,
    )


def _run_S2(args):
    if args.reportlets_only:
        from spineprep.S2_anat_cordref import run_S2_anat_cordref_reportlets_only

        return run_S2_anat_cordref_reportlets_only(
            dataset_key=args.dataset_key,
            datasets_local=args.datasets_local,
            bids_root=args.bids_root,
            out=args.out,
        )
    elif args.dataset_keys:
        # Batch mode: process multiple datasets in parallel
        from spineprep.S2_anat_cordref import run_S2_anat_cordref_batch

        if args.out is None:
            return StepResult(status="FAIL", failure_message="--out is required for batch processing")

        results = run_S2_anat_cordref_batch(
            dataset_keys=args.dataset_keys,
            datasets_local=args.datasets_local,
            out_base=args.out,
            max_workers=args.batch_workers,
        )

        # Summarize results
        passed = sum(1 for r in results.values() if r.status == "PASS")
        failed = sum(1 for r in results.values() if r.status == "FAIL")
        total = len(results)

        # Return a combined result
        if failed == 0:
            return StepResult(
                status="PASS",
                failure_message=None,
            )
        else:
            failed_keys = [k for k, r in results.items() if r.status == "FAIL"]
            return StepResult(
                status="FAIL",
                failure_message=f"Batch processing: {failed}/{total} datasets failed. Failed: {', '.join(failed_keys[:5])}{'...' if len(failed_keys) > 5 else ''}",
            )
    else:
        # Single dataset mode
        from spineprep.S2_anat_cordref import run_S2_anat_cordref

        return run_S2_anat_cordref(
            dataset_key=args.dataset_key,
            datasets_local=args.datasets_local,
            bids_root=args.bids_root,
            out=args.out,
        )


def _check_S2(args):
    from spineprep.S2_anat_cordref import check_S2_anat_cordref

    return check_S2_anat_cordref(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        bids_root=args.bids_root,
        out=args.out,
    )


if __name__ == "__main__":
    sys.exit(main())
