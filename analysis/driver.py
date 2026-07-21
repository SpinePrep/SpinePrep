#!/usr/bin/env python3
"""Walk the cohort, extract parcels, emit the long-format endpoint table.

ANALYSIS module -- not part of the preprocessing toolbox.

Scope
-----
This driver computes the QUALITY and RELIABILITY families, which are derived
from the preprocessed BOLD alone. The EFFECT family needs first-level betas and
so is deferred until the GLM has run; ``endpoints.applicable_metrics`` already
declares that dependency, and the effect hook is left explicit below rather
than half-implemented.

Design rules
------------
* A tier whose input is missing is RECORDED as skipped, never silently dropped.
  A tier that quietly vanishes from a results table looks identical to a tier
  that was computed and found empty, and only one of those is a finding.
* Every parcel emits ``n_voxels`` alongside its statistics, because a value
  from an 8-voxel dorsal horn and one from a 462-voxel cord are not comparable
  and the table must carry the means to tell them apart.
* Runs are processed one at a time and never all held in memory; the cohort is
  ~100 GB of 4D data.

Cord mask: PAM50 throughout, and why it differs from S9
-------------------------------------------------------
Every tier here is built from the PAM50 atlas warped into native space, INCLUDING
the whole-cord tier. S9's own ``tsnr_post_median`` instead uses the EPI-derived
cord segmentation (``sct_deepseg sc_epi`` on the post-S5 mean BOLD), so the two
numbers are not identical: measured across 8 runs the median difference is
about 1 tSNR unit, reaching 2.2 on one subject.

That is not an error in either. They answer different questions -- the EPI
segmentation asks where the cord is in THIS subject's data, the warped template
asks where the template says it is after registration -- and the gap between
them tracks registration quality, which is why it is systematic within a subject
rather than random.

PAM50 is used here because the sub-cord tiers (spinal level, hemicord, grey
matter horns) exist only in template space. Mixing sources would make the cord
tier stop being the union of its own sub-parcels, and a hierarchy whose levels
do not nest is not a hierarchy. Every row therefore carries ``mask_source`` so
this choice is visible in the table rather than buried here, and any comparison
against an S9 value must account for it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

from analysis import endpoints as EP
from analysis.endpoints import parcel_name, record
from analysis import estimators as ES
from analysis.glm_spec import RESTING, SPEC, is_excluded, repetition_time_s

# PAM50 atlas indices for the grey-matter parcels, from info_label.txt.
# Verified against the warped atlas: 30/31 ventral, 32/33 intermediate,
# 34/35 dorsal, left/right respectively.
GM_PARCELS = {
    "ventral": (30, 31),
    "intermediate": (32, 33),
    "dorsal": (34, 35),
}

# Repeat structure, measured on the cohort. Drives which metrics are attempted.
REPEAT_AXIS = {
    "openneuro_ds004926_dorsalhorn_pain": "session",
    "openneuro_ds004616_spinalcord_handgrasp_task": "run",
    # ds004386's two runs are auto vs manual z-shim (Kaptan 2022, HBM
    # 10.1002/hbm.26018), NOT repeat measurements. Treating them as a
    # reliability axis would compute a spurious cross-run ICC that actually
    # measures a shim contrast. Split-half within each run is the honest axis;
    # the auto-vs-manual comparison is a separate, deliberate analysis.
    "openneuro_ds004386_spinalcord_rest_testretest": "split",
    "internal_balgrist_cospigvs_11": "run",
    "internal_balgrist_motor_11": "run",
    "internal_balgrist_painmotor_21": "run",
    "openneuro_ds005884_cospine_motor": "split",
    "openneuro_ds005883_cospine_pain": "split",
    "openneuro_ds005075_brain_spine_rest": "split",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def iter_runs(out_dir: Path) -> Iterator[dict]:
    """Yield one record per run that reached S9, with its file paths resolved."""
    logs = Path(out_dir) / "logs" / "S9_primary_functional_derivatives"
    deriv = Path(out_dir) / "derivatives"
    for qc in sorted(logs.glob("*/qc.json")):
        dataset = qc.parent.name
        try:
            data = json.loads(qc.read_text())
        except Exception:
            continue
        for run in data.get("runs", []):
            rid = run.get("run_id")
            if not rid or is_excluded(dataset, rid):
                continue
            bold = next(iter(deriv.rglob(f"{rid}_desc-preproc_bold.nii.gz")), None)
            if bold is None:
                continue
            func = bold.parent
            yield {
                "dataset": dataset,
                "subject": run.get("subject"),
                "session": run.get("session"),
                "run_id": rid,
                "bold": bold,
                "func_dir": func,
                "cord": func / f"{rid}_desc-PAM50cord_mask.nii.gz",
                "spinallevels": func / f"{rid}_desc-PAM50spinallevels.nii.gz",
                "vertlevels": func / f"{rid}_desc-PAM50vertlevels.nii.gz",
                "atlas": func / f"{rid}_desc-PAM50atlas_probseg.nii.gz",
                "confounds": func / f"{rid}_desc-confounds_timeseries.tsv",
                "status": run.get("status"),
                "metrics": run.get("metrics") or {},
            }


# ---------------------------------------------------------------------------
# Parcel construction
# ---------------------------------------------------------------------------


def _load(p: Path) -> Optional[np.ndarray]:
    import nibabel as nib
    if not Path(p).exists():
        return None
    try:
        return np.asarray(nib.load(str(p)).dataobj)
    except Exception:
        return None


def hemicord_masks(cord: np.ndarray, axcodes: tuple) -> Optional[dict]:
    """Split the cord into left and right about its own per-slice centroid.

    Uses the cord's centroid rather than the image midline: the cord is rarely
    centred in the field of view, and an image-midline split would assign whole
    slices to one side on an off-centre acquisition.

    The L-R axis is taken from the affine, not assumed. Every file in this
    cohort is LAS, but hardcoding that would break silently on the first
    dataset that is not -- the same class of bug as the FD orientation issue
    fixed in the pipeline this week.
    """
    lr = next((i for i, c in enumerate(axcodes) if c in ("L", "R")), None)
    if lr is None:
        return None
    left_is_positive = axcodes[lr] == "L"
    out_l = np.zeros_like(cord, dtype=bool)
    out_r = np.zeros_like(cord, dtype=bool)
    idx = np.indices(cord.shape)[lr]
    # per axial slice, split about that slice's own cord centroid
    z_axis = next((i for i, c in enumerate(axcodes) if c in ("S", "I")), 2)
    for z in range(cord.shape[z_axis]):
        sl = [slice(None)] * 3
        sl[z_axis] = z
        sl = tuple(sl)
        m = cord[sl] > 0.5
        if not m.any():
            continue
        centre = idx[sl][m].mean()
        pos = idx[sl] > centre
        (out_l if left_is_positive else out_r)[sl] = m & pos
        (out_r if left_is_positive else out_l)[sl] = m & ~pos
    return {"L": out_l, "R": out_r}


def build_parcels(run: dict) -> tuple[dict, list[str]]:
    """Return ``({tier: {parcel: bool mask}}, [skipped tier reasons])``."""
    import nibabel as nib
    parcels: dict[str, dict[str, np.ndarray]] = {}
    skipped: list[str] = []

    cord = _load(run["cord"])
    if cord is None:
        return {}, ["cord: mask missing -- no tier can be built"]
    cordm = cord > 0.5
    if not cordm.any():
        return {}, ["cord: mask empty"]
    parcels["cord"] = {"cord": cordm}

    try:
        ax = nib.orientations.aff2axcodes(nib.load(str(run["bold"])).affine)
    except Exception:
        ax = ("L", "A", "S")

    hemi = hemicord_masks(cordm, ax)
    if hemi:
        parcels["hemicord"] = {parcel_name("hemicord", None, s): m
                               for s, m in hemi.items() if m.any()}
    else:
        skipped.append("hemicord: no L-R axis in the affine")

    for tier, key in (("spinallevel", "spinallevels"), ("vertlevel", "vertlevels")):
        lab = _load(run[key])
        if lab is None:
            skipped.append(f"{tier}: {Path(run[key]).name} not emitted by S7")
            continue
        d = {}
        for v in sorted(set(np.unique(lab.astype(int))) - {0}):
            m = (lab.astype(int) == v) & cordm
            if m.sum() > 0:
                d[parcel_name(tier, int(v))] = m
        if d:
            parcels[tier] = d

    atlas = _load(run["atlas"])
    if atlas is None:
        skipped.append("gmhorn: PAM50atlas_probseg not emitted by S7")
    elif atlas.ndim != 4:
        skipped.append(f"gmhorn: atlas is {atlas.ndim}D, expected 4D")
    else:
        meta_p = Path(str(run["atlas"]).replace(".nii.gz", ".json"))
        idx_map = {}
        if meta_p.exists():
            try:
                for lab in json.loads(meta_p.read_text()).get("Labels", []):
                    idx_map[int(lab["atlas_id"])] = int(lab["index"])
            except Exception:
                pass
        d = {}
        for sub, (l_id, r_id) in GM_PARCELS.items():
            for side, aid in (("L", l_id), ("R", r_id)):
                j = idx_map.get(aid, aid)
                if j >= atlas.shape[3]:
                    continue
                m = (atlas[..., j] > 0.5) & cordm
                if m.sum() > 0:
                    d[parcel_name("gmhorn", sub, side)] = m
        if d:
            parcels["gmhorn"] = d
        else:
            skipped.append("gmhorn: no parcel exceeded the 0.5 threshold")
    return parcels, skipped


# ---------------------------------------------------------------------------
# Per-run endpoints
# ---------------------------------------------------------------------------


def run_endpoints(run: dict, rows: list[dict]) -> list[dict]:
    """Compute the quality + reliability families for one run."""
    import nibabel as nib

    ds, sub, ses, rid = run["dataset"], run["subject"], run["session"], run["run_id"]
    # mask_source travels with every row: the cord tier here is NOT the same
    # mask S9 used, and a reader comparing the two must be able to see that.
    common = dict(dataset=ds, subject=sub, session=ses, run_id=rid,
                  mask_source="PAM50_warped")

    parcels, skipped = build_parcels(run)
    for reason in skipped:
        rows.append({**common, "tier": reason.split(":")[0], "parcel": None,
                     "metric": None, "value": None, "n": None,
                     "family": "skipped", "units": "", "skip_reason": reason})
    if not parcels:
        return rows

    img = nib.load(str(run["bold"]))
    data = np.asarray(img.dataobj, dtype=np.float32)
    if data.ndim != 4:
        return rows
    n_vol = data.shape[3]
    record(rows, **common, tier="cord", parcel="cord",
           metric="n_volumes", value=int(n_vol), n=int(n_vol))

    # motion summaries come from the run record, not recomputed
    fd = run["metrics"].get("mean_fd_mm") or run["metrics"].get("fd_mean_mm")
    if isinstance(fd, (int, float)):
        record(rows, **common, tier="cord", parcel="cord",
               metric="fd_mean_mm", value=float(fd), n=int(n_vol))

    for tier, pmap in parcels.items():
        for pname, mask in pmap.items():
            nvox = int(mask.sum())
            record(rows, **common, tier=tier, parcel=pname,
                   metric="n_voxels", value=nvox, n=nvox)
            ts = data[mask]                       # (voxels, time)
            if ts.size == 0:
                continue
            v = ES.tsnr(ts)
            if v is not None:
                med, iqr = ES.median_iqr(v)
                if med is not None:
                    record(rows, **common, tier=tier, parcel=pname,
                           metric="tsnr_median", value=med, n=nvox)
                    record(rows, **common, tier=tier, parcel=pname,
                           metric="tsnr_iqr", value=iqr, n=nvox)
            # split-half on the parcel-mean timeseries: available on every
            # dataset because it needs one run, which is why Q2-A made it the
            # reliability backbone.
            mean_ts = np.nanmean(ts, axis=0)
            r = ES.split_half(mean_ts, "oddeven")
            if r is not None:
                record(rows, **common, tier=tier, parcel=pname,
                       metric="splithalf_r", value=r, n=int(n_vol))
                sb = ES.spearman_brown(r)
                if sb is not None:
                    record(rows, **common, tier=tier, parcel=pname,
                           metric="splithalf_r_sb", value=sb, n=int(n_vol))
    return rows


# ---------------------------------------------------------------------------
# Group-level endpoints (need several runs)
# ---------------------------------------------------------------------------


def group_endpoints(rows: list[dict]) -> list[dict]:
    """ICC and between-subject variance, from the per-run rows already emitted.

    Only attempted where the dataset's repeat structure supports it -- ICC
    needs session-level repeats, which in this cohort is ds004926 alone.
    """
    import collections
    out: list[dict] = []
    by = collections.defaultdict(dict)
    for r in rows:
        if r.get("metric") != "tsnr_median" or r.get("value") is None:
            continue
        key = (r["dataset"], r["tier"], r["parcel"])
        by[key].setdefault(r["subject"], []).append((r.get("session"), r["value"]))

    for (ds, tier, parcel), subs in sorted(by.items()):
        axis = REPEAT_AXIS.get(ds)
        if axis not in ("run", "session"):
            continue
        mat, kept = [], 0
        for sub, vals in sorted(subs.items()):
            if axis == "session":
                per = {}
                for sess, v in vals:
                    per.setdefault(sess, []).append(v)
                if len(per) < 2:
                    continue
                row = [float(np.mean(per[s])) for s in sorted(per)][:2]
            else:
                if len(vals) < 2:
                    continue
                row = [v for _, v in vals][:2]
            if len(row) == 2:
                mat.append(row); kept += 1
        if kept < 3:
            continue
        m = np.asarray(mat, float)
        common = dict(dataset=ds, subject=None, session=None, run_id=None)
        bsf = ES.between_subject_variance_fraction(m)
        if bsf is not None:
            record(out, **common, tier=tier, parcel=parcel,
                   metric="betweensubj_var_frac", value=bsf, n=kept,
                   repeat_axis=axis)
        if axis == "session":
            res = ES.icc(m, form="2,1")
            if res["icc"] is not None:
                record(out, **common, tier=tier, parcel=parcel,
                       metric="icc_2_1", value=res["icc"], n=res["n"],
                       repeat_axis=axis)
                for b, k in (("ci_lo", "icc_2_1_ci_lo"), ("ci_hi", "icc_2_1_ci_hi")):
                    if res[b] is not None:
                        record(out, **common, tier=tier, parcel=parcel,
                               metric=k, value=res[b], n=res["n"],
                               repeat_axis=axis)
    return out


def run_cohort(out_dir: Path, limit: Optional[int] = None) -> list[dict]:
    rows: list[dict] = []
    for i, run in enumerate(iter_runs(Path(out_dir))):
        if limit is not None and i >= limit:
            break
        try:
            run_endpoints(run, rows)
        except Exception as err:                 # one bad run must not stop the sweep
            rows.append({"dataset": run["dataset"], "subject": run["subject"],
                         "session": run["session"], "run_id": run["run_id"],
                         "tier": None, "parcel": None, "metric": None,
                         "value": None, "n": None, "family": "error",
                         "units": "", "skip_reason": f"{type(err).__name__}: {err}"})
    rows.extend(group_endpoints(rows))
    return rows


def main() -> int:
    import argparse
    import pandas as pd
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out_dir")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--tsv", default="analysis/results/endpoints.tsv")
    a = ap.parse_args()
    rows = run_cohort(Path(a.out_dir), a.limit)
    df = pd.DataFrame(rows)
    cols = EP.CANONICAL_COLUMNS + [c for c in df.columns
                                   if c not in EP.CANONICAL_COLUMNS]
    df = df.reindex(columns=cols)
    Path(a.tsv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.tsv, sep="\t", index=False)
    n_skip = int((df["family"] == "skipped").sum())
    n_err = int((df["family"] == "error").sum())
    print(f"rows {len(df)}  runs {df['run_id'].nunique()}  "
          f"skipped-tier notes {n_skip}  errors {n_err}")
    print(f"wrote {a.tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
