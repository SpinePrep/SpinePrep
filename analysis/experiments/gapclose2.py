"""Gap-closing, CORRECTED designs (the LOSO attempt failed: parcels are in each
subject's NATIVE grid, so cross-subject voxel intersection is empty).

G1 smoothing (all 4 datasets): odd/even CV -- valid, drift identical across arms.
G2 high-pass: FIXED a-priori ROI mean, NO voxel selection -> nothing for shared
   drift to inflate. This fixes the flaw that invalidated the first attempt.
G3 clean moco: S4-input (bold_coarse) vs S4-output (mocoref), IDENTICAL nuisance
   (no motion regressors in either arm) -> removes all 3 confounds of the
   retracted D1 ablation.
"""
import sys, csv, json
sys.path.insert(0, '/mnt/ssd1/SpinePrep')
from pathlib import Path
from collections import defaultdict
import numpy as np, yaml, statistics as st
from analysis import driver
from analysis.glm import build_task_design
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s
import nibabel as nib, pandas as pd
from scipy import stats as sps, ndimage

cfg = yaml.safe_load(Path("/mnt/ssd1/SpinePrep/config/datasets_local.yaml").read_text()) or {}
raw = cfg.get("datasets", cfg)

def mkpath(v):
    p = Path(v.get("path") or v.get("bids_root")) if isinstance(v, dict) else Path(v)
    return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep") / p

roots = {k: mkpath(v) for k, v in raw.items()}

def side_of(c):
    c = c.lower().replace('-', '').replace('_', '')
    if 'left' in c or c.endswith('l'):
        return 'L'
    if 'right' in c or c.endswith('r'):
        return 'R'
    return None

CFG = {'openneuro_ds004616_spinalcord_handgrasp_task': ('ventral', None),
       'openneuro_ds005884_cospine_motor': ('ventral', None),
       'openneuro_ds004926_dorsalhorn_pain': ('dorsal', 'L'),
       'openneuro_ds005883_cospine_pain': ('dorsal', 'R')}
WORK = Path("/mnt/ssd1/spineprep_cohort_s2/work/S4_func_motion_correction")
SM = [0, 2, 4, 6]
HP = ['none', 'quarter', 'half', 'all']

cv = defaultdict(lambda: defaultdict(list))
fx = defaultdict(lambda: defaultdict(list))
tsnr = defaultdict(lambda: defaultdict(list))
nrun = 0

for run in driver.iter_runs(Path("/mnt/ssd1/spineprep_cohort_s2")):
    ds = run["dataset"]
    if ds not in CFG:
        continue
    conds = conditions_for(ds, run["run_id"])
    if not conds:
        continue
    parcels, _ = driver.build_parcels(run)
    if "gmhorn" not in parcels:
        continue
    root = roots.get(ds)
    ev = next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")), None) if root else None
    if ev is None:
        continue
    rows = list(csv.DictReader(open(ev), delimiter='\t'))
    scj = Path(str(run["bold"]).replace(".nii.gz", ".json"))
    stt = float(json.loads(scj.read_text()).get("StartTime") or 0.0) if scj.exists() else 0.0
    try:
        img = nib.load(str(run["bold"]))
        data = np.asarray(img.dataobj, dtype=np.float32)
    except Exception:
        continue
    if data.ndim != 4:
        continue
    zooms = img.header.get_zooms()[:3]
    tr = repetition_time_s(run["bold"])
    nvol = data.shape[3]
    Xt, names = build_task_design(corrected_events(ds, rows, stt, run["run_id"]), nvol, tr, conds)
    if Xt.shape[1] == 0:
        continue
    ct = Path(run["confounds"])
    if not ct.exists():
        continue
    df = pd.read_csv(ct, sep='\t').iloc[:nvol]

    def mat(cols):
        if not cols:
            return np.empty((nvol, 0))
        X = df[cols].to_numpy(float)
        X[np.isnan(X)] = 0
        return X[:, X.std(0) > 1e-9]

    mot = mat([c for c in df.columns if c.lower().startswith(('trans_', 'rot_'))])
    cosc = [c for c in df.columns if c.lower().startswith('cosine')]
    ret = mat([c for c in df.columns if c.lower().startswith('retroicor')])
    cord = parcels["cord"]["cord"]
    midx = np.argwhere(cord)
    nrun += 1
    ht, fixed = CFG[ds]
    key = (ds, run['subject'])
    L = parcels['gmhorn'].get(f'gm-{ht}-L')
    R = parcels['gmhorn'].get(f'gm-{ht}-R')

    def measure(d4, X, tag, mode):
        Yall = d4[cord].T.astype(float)
        if Yall.shape[0] != nvol or np.linalg.matrix_rank(X) < X.shape[1]:
            return
        b1 = b2 = b = None
        if mode == 'cv':
            odd = np.arange(0, nvol, 2); even = np.arange(1, nvol, 2)
            def f(ix):
                Y = Yall[ix] - Yall[ix].mean(0, keepdims=True)
                if np.linalg.matrix_rank(X[ix]) < X.shape[1]:
                    return None
                bb, *_ = np.linalg.lstsq(X[ix], Y, rcond=None)
                return bb
            b1, b2 = f(odd), f(even)
            if b1 is None or b2 is None:
                return
        else:
            Y = Yall - Yall.mean(0, keepdims=True)
            b, *_ = np.linalg.lstsq(X, Y, rcond=None)
        for ci, cn in enumerate(names):
            sd = side_of(cn) or fixed
            if sd is None:
                continue
            m = L if sd == 'L' else R
            if m is None:
                continue
            fi = m[tuple(midx.T)]
            if fi.sum() < 10:
                continue
            if mode == 'cv':
                v1, v2 = b1[ci][fi], b2[ci][fi]
                k = max(1, int(0.1 * len(v1)))
                cv[tag][key].append(float(v2[np.argsort(v1)[-k:]].mean()))
            else:
                fx[tag][key].append(float(b[ci][fi].mean()))

    Xfull = (np.column_stack([Xt, mot, mat(cosc), ret, np.ones(nvol)]) if ret.size
             else np.column_stack([Xt, mot, mat(cosc), np.ones(nvol)]))
    for f_ in SM:
        d4 = data if f_ == 0 else ndimage.gaussian_filter(
            data, sigma=[(f_ / 2.355) / z for z in zooms] + [0], mode='nearest')
        measure(d4, Xfull, f"sm{f_}", 'cv')
    for arm in HP:
        k = {'none': 0, 'quarter': max(1, len(cosc) // 4),
             'half': max(1, len(cosc) // 2), 'all': len(cosc)}[arm]
        Xc = mat(cosc[:k]) if k else np.empty((nvol, 0))
        X = (np.column_stack([Xt, mot, Xc, ret, np.ones(nvol)]) if ret.size
             else np.column_stack([Xt, mot, Xc, np.ones(nvol)]))
        measure(data, X, f"hp_{arm}", 'fixed')
    pre = WORK / run["run_id"] / "bold_coarse.nii.gz"
    if pre.exists():
        Xm = (np.column_stack([Xt, mat(cosc), ret, np.ones(nvol)]) if ret.size
              else np.column_stack([Xt, mat(cosc), np.ones(nvol)]))
        try:
            p4 = np.asarray(nib.load(str(pre)).dataobj, dtype=np.float32)
            if p4.ndim == 4 and p4.shape[:3] == cord.shape and p4.shape[3] >= nvol:
                for tag, dd in (("moco_off", p4[..., :nvol]), ("moco_on", data)):
                    measure(dd, Xm, tag, 'cv')
                    Y = dd[cord].T.astype(float)
                    mm, ss = Y.mean(0), Y.std(0)
                    tsnr[tag][ds].append(float(np.median(mm[ss > 0] / ss[ss > 0])))
        except Exception:
            pass

def gd(store, tag, ds):
    vals = [st.mean(v) for (d2, s), v in store[tag].items() if d2 == ds and v]
    if len(vals) < 5:
        return None, None
    t, p = sps.ttest_1samp(vals, 0)
    return np.mean(vals) / np.std(vals, ddof=1), p

short = lambda ds: ds.split('_')[1] if ds.split('_')[0] == 'openneuro' else ds.split('_')[2]
print(f"### runs: {nrun}\n")
print("=== G1  SMOOTHING, all 4 datasets (odd/even CV group d) ===")
print(f"{'dataset':11} " + " ".join(f"{f}mm".rjust(8) for f in SM))
for ds in CFG:
    cells = []
    for f_ in SM:
        d, p = gd(cv, f"sm{f_}", ds)
        cells.append(f"{d:+.2f}" if d is not None else "  -")
    print(f"  {short(ds):11} " + " ".join(c.rjust(8) for c in cells))
print("\n=== G2  HIGH-PASS, valid design (FIXED ROI, no selection) ===")
print(f"{'dataset':11} " + " ".join(a.rjust(8) for a in HP))
for ds in CFG:
    cells = []
    for a in HP:
        d, p = gd(fx, f"hp_{a}", ds)
        cells.append(f"{d:+.2f}" if d is not None else "  -")
    print(f"  {short(ds):11} " + " ".join(c.rjust(8) for c in cells))
print("\n=== G3  CLEAN MOCO ABLATION (S4 in vs out, identical nuisance) ===")
print(f"{'dataset':11} {'arm':10} {'tSNR':>7} {'group d':>8} {'p':>9}")
for ds in CFG:
    for tag in ('moco_off', 'moco_on'):
        d, p = gd(cv, tag, ds)
        if d is None:
            continue
        ts = st.median(tsnr[tag][ds]) if tsnr[tag][ds] else float('nan')
        print(f"  {short(ds):11} {tag:10} {ts:7.1f} {d:+8.2f} {p:9.5f}")
print("\nDONE_MARKER")
