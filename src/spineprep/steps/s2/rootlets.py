"""S2.3: rootlets detection."""
from __future__ import annotations

from pathlib import Path

from .io import _run_command


def _run_rootlets_segmentation(
    cordref_path: Path,
    work_dir: Path,
    enabled: bool,
    eligible: bool,
) -> dict:
    if not enabled:
        return {"status": "SKIP", "eligible": eligible, "enabled": False}
    if not eligible:
        return {"status": "SKIP", "eligible": False, "enabled": True}

    rootlets_dir = work_dir / "rootlets"
    rootlets_dir.mkdir(parents=True, exist_ok=True)
    output_base = rootlets_dir / "rootlets.nii.gz"
    ok, message = _run_command(
        [
            "sct_deepseg",
            "rootlets",
            "-i",
            str(cordref_path),
            "-o",
            str(output_base),
        ]
    )
    if not ok:
        return {"status": "FAIL", "eligible": True, "enabled": True, "failure_message": message}

    rootlets_path = _find_rootlets_output(rootlets_dir, output_base)
    if rootlets_path is None:
        return {
            "status": "FAIL",
            "eligible": True,
            "enabled": True,
            "failure_message": "Rootlets output not found.",
        }
    return {
        "status": "PASS",
        "eligible": True,
        "enabled": True,
        "rootlets_path": str(rootlets_path),
    }


def _find_rootlets_output(folder: Path, base: Path) -> Path | None:
    candidates = sorted(folder.glob("*.nii.gz"))
    for candidate in candidates:
        if "rootlets" in candidate.name:
            return candidate
    expected = Path(str(base) + ".nii.gz")
    if expected.exists():
        return expected
    return candidates[0] if candidates else None
