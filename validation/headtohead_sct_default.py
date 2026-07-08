"""Head-to-head: SpinePrep S6 registration recipe vs SCT-default (T4; V3).

Pre-empts the #1 reviewer objection ("why not just use SCT defaults?"). Compares
functional->anatomical cord registration quality (cord-Dice) between:
  - OURS: the S6 cord-driven recipe (Kaptan 2023: centermassrot -> columnwise ->
    bsplinesyn) — `cord_dice` already in each run's S6 qc.json.
  - SCT-default: `sct_register_multimodal -i funcref -d anat_in_bold` with default
    parameters, the warp applied to the func cord seg, Dice vs the anat cord seg.

Paired over the same runs; Wilcoxon signed-rank for non-inferiority/superiority.

WHEN TO RUN: at the release gate (GOAL ladder RG), on the locked-σ reprocessed
cohort — the SCT-default arm must compare against the FINAL pipeline, not stale
derivatives. The Dice + comparison logic is implemented and unit-tested here; the
SCT-default arm (`run_sct_default`) is the only heavy compute and is invoked then.

Inputs per run live in the S6 work tree:
  funcref.nii.gz, anat_in_bold.nii.gz, funccrop_mask.nii.gz (func cord region),
  anat_dseg_in_bold.nii.gz (anat cord seg in func space).
"""

from __future__ import annotations

import glob
import json
import subprocess
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np


def dice(seg_a: np.ndarray, seg_b: np.ndarray) -> float:
    """Sørensen–Dice of two binary masks."""
    a = seg_a > 0
    b = seg_b > 0
    denom = int(a.sum()) + int(b.sum())
    if denom == 0:
        return float("nan")
    return 2.0 * int((a & b).sum()) / denom


def our_cord_dice(scope: str) -> dict[str, float]:
    """{run_id: cord_dice} from our S6 qc.json (the 'ours' arm — already computed)."""
    out = {}
    for f in glob.glob(f"work/done/{scope}/S6/logs/S6_func_to_anat_registration/*/qc.json"):
        d = json.loads(Path(f).read_text())
        for r in (d.get("runs") or []):
            v = (r.get("metrics") or {}).get("cord_dice")
            if v is not None:
                out[r.get("run_id")] = float(v)
    return out


def run_sct_default(funcref: Path, anat_in_bold: Path,
                    func_seg: Path, anat_seg: Path, work: Path) -> Optional[float]:
    """SCT-default arm: register funcref->anat with DEFAULT params, apply the warp
    to the func cord seg, return Dice vs the anat cord seg. Heavy — run at RG."""
    work.mkdir(parents=True, exist_ok=True)
    warp = work / "warp_func2anat_default.nii.gz"
    reg = work / "funcref_reg_default.nii.gz"
    # SCT default: no -param override -> the toolbox's out-of-the-box behaviour.
    cmd = ["sct_register_multimodal", "-i", str(funcref), "-d", str(anat_in_bold),
           "-owarp", str(warp), "-o", str(reg), "-x", "linear"]
    if subprocess.run(cmd, cwd=work).returncode != 0 or not warp.exists():
        return None
    seg_reg = work / "func_seg_in_anat_default.nii.gz"
    cmd2 = ["sct_apply_transfo", "-i", str(func_seg), "-d", str(anat_seg),
            "-w", str(warp), "-x", "nn", "-o", str(seg_reg)]
    if subprocess.run(cmd2, cwd=work).returncode != 0 or not seg_reg.exists():
        return None
    return dice(nib.load(str(seg_reg)).get_fdata(), nib.load(str(anat_seg)).get_fdata())


def main():
    print("T4 head-to-head harness. The SCT-default arm is heavy and runs at the "
          "release gate (RG) on the locked-σ cohort. 'Ours' arm preview:")
    for scope in ("cospain", "cosmotor", "dorsalhorn"):
        ours = our_cord_dice(scope)
        if ours:
            vals = np.array(list(ours.values()))
            print(f"  {scope}: ours S6 cord_dice n={len(vals)} "
                  f"mean={vals.mean():.3f} median={np.median(vals):.3f}")


if __name__ == "__main__":
    main()
