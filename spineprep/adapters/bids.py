from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

_RUN_RE = re.compile(r".*?_run-(\d+)_bold\.nii\.gz$")
_TASK_RE = re.compile(r".*?_task-([a-zA-Z0-9]+)_")
_SES_RE = re.compile(r"^ses-[a-zA-Z0-9]+$")


def _iter_dirs(p: Path, prefix: str) -> List[Path]:
    if not p.exists():
        return []
    return sorted([d for d in p.iterdir() if d.is_dir() and d.name.startswith(prefix)])


def list_subjects(
    bids_root: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[str]:
    root = Path(bids_root)
    subs = [d.name for d in _iter_dirs(root, "sub-")]
    if include:
        subs = [s for s in subs if s in include]
    if exclude:
        subs = [s for s in subs if s not in exclude]
    return sorted(subs)


def list_sessions(bids_root: str, sub: str) -> List[str]:
    sdir = Path(bids_root) / sub
    if not sdir.exists():
        return []
    ses = [d.name for d in _iter_dirs(sdir, "ses-")]
    return sorted(ses)


def _runs_in_func(func_dir: Path, task: Optional[str]) -> List[str]:
    if not func_dir.exists():
        return []
    runs = set()
    for f in func_dir.iterdir():
        if not f.is_file():
            continue
        name = f.name
        if not name.endswith("_bold.nii.gz"):
            continue
        if task:
            mtask = _TASK_RE.search(name)
            if not mtask or mtask.group(1) != task:
                continue
        m = _RUN_RE.match(name)
        if m:
            runs.add(m.group(1).zfill(2))
    return sorted(runs, key=lambda x: (len(x), x))


def list_runs(
    bids_root: str, sub: str, ses: Optional[str], task: Optional[str] = None
) -> List[str]:
    base = Path(bids_root) / sub
    func_dir = base / ses / "func" if ses else base / "func"
    return _runs_in_func(func_dir, task)


def bold_nii(
    bids_root: str, sub: str, ses: Optional[str], run: str, task: Optional[str] = None
) -> str:
    base = Path(bids_root) / sub
    func_dir = base / ses / "func" if ses else base / "func"
    candidates = []
    for f in func_dir.iterdir():
        if not f.is_file() or not f.name.endswith("_bold.nii.gz"):
            continue
        if f"_run-{int(run):02d}_" not in f.name:
            continue
        if task:
            mtask = _TASK_RE.search(f.name)
            if not mtask or mtask.group(1) != task:
                continue
        candidates.append(f)
    if not candidates:
        raise FileNotFoundError(
            f"No BOLD found for {sub} {ses or ''} run-{run} (task={task}) in {func_dir}"
        )
    # deterministic: pick shortest name (fewest entities)
    candidates.sort(key=lambda p: (len(p.name), p.name))
    return str(candidates[0])


def discover(bids_root: str, task: Optional[str] = None) -> Dict:
    root = Path(bids_root).absolute()
    out = {
        "bids_root": str(root),
        "subjects": [],
        "counts": {"subjects": 0, "sessions": 0, "runs": 0},
    }
    subs = list_subjects(str(root))
    n_ses_total = 0
    n_runs_total = 0
    for sub in subs:
        ses = list_sessions(str(root), sub)
        if ses:
            ses_list = []
            for s in ses:
                runs = list_runs(str(root), sub, s, task=task)
                if runs:
                    ses_list.append({"id": s, "runs": runs})
                    n_runs_total += len(runs)
                    n_ses_total += 1
            if ses_list:
                out["subjects"].append({"id": sub, "sessions": ses_list})
        else:
            runs = list_runs(str(root), sub, None, task=task)
            if runs:
                out["subjects"].append(
                    {"id": sub, "sessions": [{"id": None, "runs": runs}]}
                )
                n_ses_total += 1
                n_runs_total += len(runs)
    out["counts"] = {
        "subjects": len(out["subjects"]),
        "sessions": n_ses_total,
        "runs": n_runs_total,
    }
    return out


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--task", default=None)
    args = ap.parse_args()
    print(json.dumps(discover(args.root, task=args.task), indent=2))
