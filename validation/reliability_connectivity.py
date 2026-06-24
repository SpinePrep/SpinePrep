"""Test-retest reliability of intra-cord functional connectivity.

CENTERPIECE validation (T2/R2-R3; the venue-mover). A BENCHMARK module, not a
pipeline step: it consumes the pipeline's GLM-ready derivatives and asks whether
the *scientific output* — resting-state / task functional connectivity along the
cord — is reproducible across sessions. This is the rigour a preprocessing
pipeline must show (cf. Hemmerling 2023; Dabbagh 2024).

Method (all in native func space, where the smoothed BOLD and the PAM50
spinal-level atlas already share a grid — no resampling):
1. Per run: mean BOLD time-series per vertebral level (rostro-caudal nodes).
2. Level×level Pearson connectivity matrix; Fisher-z the edges.
3. Across the two sessions of each subject: ICC(2,1) of every edge
   (Shrout & Fleiss 1979) → reliability of the connectivity fingerprint.

Usage: poetry run python validation/reliability_connectivity.py [scope ...]
"""

from __future__ import annotations

import glob
import re
import sys
from itertools import combinations
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

from reliability_tsnr import icc_2_1, _level_name  # reuse the ICC + naming

# (scope -> (repeat dimension, reliability type label, human label)). The cohort's
# repeated measures are NOT uniform — only dorsalhorn/handgrasp are true
# between-session test-retest; rest is cross-shim (auto vs manual z-shim). Each is
# labelled honestly (no run/cross-shim repeat is called "test-retest").
RELIABILITY_SCOPES = {
    "dorsalhorn": ("ses", "test-retest", "dorsalhorn pain (heat task, ses-01 vs ses-02)"),
    "handgrasp":  ("ses", "test-retest", "handgrasp motor (ses-01 vs ses-02)"),
    "rest":       ("acq", "cross-shim reproducibility",
                   "rest (auto vs manual z-shim — NOT test-retest)"),
}
# back-compat alias
TEST_RETEST_SCOPES = {k: v[2] for k, v in RELIABILITY_SCOPES.items()}


def _per_level_timeseries(bold_path: Path, atlas_path: Path) -> dict[int, np.ndarray]:
    """{level: mean time-series} from native smoothed BOLD + native level atlas
    (same grid). Levels with <3 voxels are dropped (unstable mean)."""
    bold = nib.load(str(bold_path))
    atlas = nib.load(str(atlas_path))
    if bold.shape[:3] != atlas.shape[:3]:
        return {}
    bdata = bold.get_fdata(dtype=np.float32)
    if bdata.ndim != 4:
        return {}
    labels = np.rint(atlas.get_fdata()).astype(int)
    out: dict[int, np.ndarray] = {}
    for lvl in sorted(int(v) for v in np.unique(labels) if v > 0):
        mask = labels == lvl
        if int(mask.sum()) < 3:
            continue
        ts = bdata[mask].mean(axis=0)  # (T,)
        if np.std(ts) > 0:
            out[lvl] = (ts - ts.mean()) / ts.std()
    return out


def _edges(ts_by_level: dict[int, np.ndarray], levels: list[int]) -> dict[tuple[int, int], float]:
    """Fisher-z Pearson connectivity for each level pair present in `levels`."""
    edges = {}
    for a, b in combinations(levels, 2):
        if a in ts_by_level and b in ts_by_level:
            r = float(np.corrcoef(ts_by_level[a], ts_by_level[b])[0, 1])
            r = max(min(r, 0.999999), -0.999999)
            edges[(a, b)] = float(np.arctanh(r))  # Fisher z
    return edges


def _runs(scope: str, repeat_key: str = "ses"):
    """Yield (subject, repeat_label, bold_path, atlas_path). The repeat label is
    drawn from the BIDS entity that indexes the repeated measure for this scope
    (``ses``/``acq``/``run``)."""
    s9 = Path(f"work/done/{scope}/S9/derivatives/spinalfmriprep")
    s7 = Path(f"work/done/{scope}/S7/derivatives/spinalfmriprep")
    pat = {"ses": r"_ses-([A-Za-z0-9]+)", "acq": r"_acq-([A-Za-z0-9]+)",
           "run": r"_run-([A-Za-z0-9]+)"}[repeat_key]
    for bold in glob.glob(str(s9 / "**" / "*_desc-preproc_bold.nii.gz"), recursive=True):
        if "PAM50" in Path(bold).name:
            continue
        run_id = Path(bold).name.replace("_desc-preproc_bold.nii.gz", "")
        ms = re.search(r"(sub-[A-Za-z0-9]+)", run_id)
        mr = re.search(pat, run_id)
        if not ms or not mr:
            continue
        sub, rep = ms.group(1), mr.group(1)
        atlas = glob.glob(str(s7 / "**" / f"{run_id}_desc-PAM50spinallevels.nii.gz"),
                          recursive=True)
        if atlas:
            yield sub, rep, Path(bold), Path(atlas[0])


def run(scopes: list[str], out_tsv: Path | None = None) -> pd.DataFrame:
    results = []
    for scope in scopes:
        repeat_key, rtype, label = RELIABILITY_SCOPES.get(
            scope, ("ses", "test-retest", scope))
        # collect edges per (subject, repeat); average any runs within a repeat
        per_ss: dict[tuple[str, str], list[dict]] = {}
        all_levels: set[int] = set()
        for sub, ses, bold, atlas in _runs(scope, repeat_key):
            ts = _per_level_timeseries(bold, atlas)
            if len(ts) < 2:
                continue
            lv = sorted(ts)
            all_levels.update(lv)
            per_ss.setdefault((sub, ses), []).append(_edges(ts, lv))
        if not per_ss:
            print(f"  {label}: no usable runs")
            continue
        # average edges within (sub,ses)
        ss_edges = {}
        for key, lst in per_ss.items():
            agg: dict[tuple[int, int], list[float]] = {}
            for e in lst:
                for k, v in e.items():
                    agg.setdefault(k, []).append(v)
            ss_edges[key] = {k: float(np.mean(v)) for k, v in agg.items()}
        subjects = sorted({s for s, _ in ss_edges})
        sessions = sorted({se for _, se in ss_edges})[:2]
        # ICC per edge across the two sessions
        edge_iccs = []
        for a, b in combinations(sorted(all_levels), 2):
            rows = []
            for sub in subjects:
                v = [ss_edges.get((sub, se), {}).get((a, b)) for se in sessions]
                if all(x is not None for x in v):
                    rows.append(v)
            if len(rows) >= 3:
                icc, n = icc_2_1(np.array(rows, dtype=float))
                if not np.isnan(icc):
                    edge_iccs.append(icc)
                    results.append({"scope": scope, "type": rtype,
                                    "edge": f"{_level_name(a)}-{_level_name(b)}",
                                    "icc_2_1": round(icc, 3), "n": n})
        if edge_iccs:
            print(f"\n{label}: connectivity {rtype} — {len(edge_iccs)} edges, "
                  f"repeats {sessions}")
            print(f"   mean edge ICC(2,1) = {np.mean(edge_iccs):.2f} "
                  f"(median {np.median(edge_iccs):.2f}, "
                  f"max {np.max(edge_iccs):.2f})")
    df = pd.DataFrame(results)
    if out_tsv is not None and not df.empty:
        out_tsv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_tsv, sep="\t", index=False)
        print(f"\nwrote {out_tsv}")
    return df


if __name__ == "__main__":
    scopes = sys.argv[1:] or list(RELIABILITY_SCOPES)
    print("Test-retest reliability of intra-cord connectivity — ICC(2,1) per edge")
    run(scopes, out_tsv=Path("validation/results/reliability_connectivity.tsv"))
