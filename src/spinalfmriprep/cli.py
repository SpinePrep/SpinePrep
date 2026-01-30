"""
SpinalfMRIprep command line interface.

Implements S0_SETUP run/check for bootstrap policy validation.
"""

from __future__ import annotations


import argparse
import json
import sys
from pathlib import Path

from importlib import metadata

from spinalfmriprep.S0_setup import check_S0_setup, run_S0_setup
from spinalfmriprep.S2_anat_cordref import StepResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spinalfmriprep", description="SpinalfMRIprep CLI")
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
        choices=["S0_SETUP", "S1_input_verify", "S2_anat_cordref", "S3_func_init_and_crop"],
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
        "--scope",
        help="Process datasets by scope: 'reg'/'regression' (5 subsets, 5 subjects), "
             "'full'/'v1_validation' (5 datasets, 146 subjects), or comma-separated keys. "
             "See SPEC/HEADER.md for definitions.",
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
            version = metadata.version("spinalfmriprep")
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
        elif step == "S3_func_init_and_crop":
            result = _run_S3(args)
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
        elif step == "S3_func_init_and_crop":
            result = _check_S3(args)
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
    # Resolve dataset keys from --scope if provided
    dataset_keys = args.dataset_keys or []
    if args.scope:
        resolved_keys = _resolve_scope_to_dataset_keys(args.scope)
        if not resolved_keys:
            return StepResult(
                status="FAIL",
                failure_message=f"No datasets found for scope: {args.scope}",
            )
        dataset_keys = resolved_keys
    
    if dataset_keys:
        # Batch mode: process multiple datasets
        from spinalfmriprep.S1_input_verify import run_S1_input_verify_batch

        if args.out is None:
            return StepResult(status="FAIL", failure_message="--out is required for batch processing")

        results = run_S1_input_verify_batch(
            dataset_keys=dataset_keys,
            datasets_local=args.datasets_local,
            out_base=args.out,
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
        from spinalfmriprep.S1_input_verify import run_S1_input_verify

        return run_S1_input_verify(
            dataset_key=args.dataset_key,
            datasets_local=args.datasets_local,
            bids_root=args.bids_root,
            out=args.out,
        )


def _check_S1(args):
    from spinalfmriprep.S1_input_verify import check_S1_input_verify

    return check_S1_input_verify(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        bids_root=args.bids_root,
        out=args.out,
    )


def _run_S2(args):
    # Resolve dataset keys from --scope if provided
    dataset_keys = args.dataset_keys or []
    if args.scope:
        resolved_keys = _resolve_scope_to_dataset_keys(args.scope)
        if not resolved_keys:
            return StepResult(
                status="FAIL",
                failure_message=f"No datasets found for scope: {args.scope}",
            )
        dataset_keys = resolved_keys
    
    # Handle --reportlets-only mode
    if args.reportlets_only:
        if args.out is None:
            return StepResult(status="FAIL", failure_message="--out is required for --reportlets-only")
        
        if dataset_keys:
            # Batch mode reportlets-only: regenerate for multiple datasets
            from spinalfmriprep.S2_anat_cordref import run_S2_anat_cordref_reportlets_only_batch
            
            results = run_S2_anat_cordref_reportlets_only_batch(
                dataset_keys=dataset_keys,
                out_base=args.out,
            )
            
            # Summarize results
            passed = sum(1 for r in results.values() if r.status == "PASS")
            failed = sum(1 for r in results.values() if r.status == "FAIL")
            total = len(results)
            
            if failed == 0:
                return StepResult(status="PASS", failure_message=None)
            else:
                failed_keys = [k for k, r in results.items() if r.status == "FAIL"]
                return StepResult(
                    status="FAIL",
                    failure_message=f"Reportlets-only batch: {failed}/{total} datasets failed. Failed: {', '.join(failed_keys[:5])}",
                )
        else:
            # Single dataset reportlets-only
            from spinalfmriprep.S2_anat_cordref import run_S2_anat_cordref_reportlets_only

            return run_S2_anat_cordref_reportlets_only(
                dataset_key=args.dataset_key,
                datasets_local=args.datasets_local,
                bids_root=args.bids_root,
                out=args.out,
            )
    
    if dataset_keys:
        # Batch mode: process multiple datasets
        from spinalfmriprep.S2_anat_cordref import run_S2_anat_cordref_batch

        if args.out is None:
            return StepResult(status="FAIL", failure_message="--out is required for batch processing")

        # Chain model: detect S1 done path based on scope
        s1_base = None
        if args.scope:
            scope_aliases = {"full": "v1_validation", "reg": "regression"}
            resolved_scope = scope_aliases.get(args.scope, args.scope)
            # Map scope to chain name
            chain_name = {"regression": "reg", "v1_validation": "full"}.get(resolved_scope, args.scope)
            s1_done_path = Path("work") / "done" / chain_name / "S1"
            if s1_done_path.exists() or s1_done_path.is_symlink():
                s1_base = s1_done_path.resolve()

        results = run_S2_anat_cordref_batch(
            dataset_keys=dataset_keys,
            datasets_local=args.datasets_local,
            out_base=args.out,
            max_workers=args.batch_workers,
            s1_base=s1_base,
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
        from spinalfmriprep.S2_anat_cordref import run_S2_anat_cordref

        return run_S2_anat_cordref(
            dataset_key=args.dataset_key,
            datasets_local=args.datasets_local,
            bids_root=args.bids_root,
            out=args.out,
        )


def _resolve_scope_to_dataset_keys(scope: str) -> list[str]:
    """
    Resolve a scope value to a list of dataset keys.
    
    Scope can be:
    - 'regression' or 'reg': all datasets with intended_use containing 'regression'
    - 'full' or 'v1_validation': all datasets with intended_use containing 'v1_validation'
    - Comma-separated list of dataset keys
    
    See private/SPEC/HEADER.md § Development Scopes for canonical definitions:
    - smoke: 1 subject (handled by smoke scripts, not this function)
    - reg: 5 subjects (1 per dataset, regression subsets)
    - full: 146 subjects (all subjects in v1_validation datasets)
    """
    from spinalfmriprep.policy.datasets import load_dataset_policy
    
    # Scope aliases
    scope_aliases = {
        "full": "v1_validation",
        "reg": "regression",
    }
    resolved_scope = scope_aliases.get(scope, scope)
    
    # Check if scope is a known intended_use value
    known_scopes = {"regression", "v1_validation", "extended", "private", "requested"}
    
    if resolved_scope in known_scopes:
        # Load policy and filter by intended_use
        policy_path = Path("policy") / "datasets.yaml"
        if not policy_path.exists():
            return []
        
        policy = load_dataset_policy(policy_path)
        return [
            entry.key
            for entry in policy.datasets
            if resolved_scope in entry.intended_use
        ]
    else:
        # Treat as comma-separated list of dataset keys
        return [k.strip() for k in scope.split(",") if k.strip()]


def _check_S2(args):
    from spinalfmriprep.S2_anat_cordref import check_S2_anat_cordref

    return check_S2_anat_cordref(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        bids_root=args.bids_root,
        out=args.out,
    )


def _run_S3(args):
    from spinalfmriprep.S3_func_init_and_crop import run_S3_func_init_and_crop

    return run_S3_func_init_and_crop(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        out=args.out,
        batch_workers=args.batch_workers,
    )


def _check_S3(args):
    from spinalfmriprep.S3_func_init_and_crop import check_S3_func_init_and_crop

    return check_S3_func_init_and_crop(
        dataset_key=args.dataset_key,
        datasets_local=args.datasets_local,
        out=args.out,
    )


if __name__ == "__main__":
    sys.exit(main())
