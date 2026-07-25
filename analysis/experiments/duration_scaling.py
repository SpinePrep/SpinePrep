import sys,csv,json; sys.path.insert(0,'/mnt/ssd1/SpinePrep')
from pathlib import Path
from collections import defaultdict
import numpy as np, yaml, statistics as st
from analysis import driver
from analysis.glm import build_task_design
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s
import nibabel as nib, pandas as pd
from scipy import stats as sps
cfg=yaml.safe_load(Path("/mnt/ssd1/SpinePrep/config/datasets_local.yaml").read_text()) or {}
raw=cfg.get("datasets",cfg)
def mkpath(v):
    p=Path(v.get("path") or v.get("bids_root")) if isinstance(v,dict) else Path(v)
    return p if p.is_absolute() else Path("/mnt/ssd1/SpinePrep")/p
roots={k:mkpath(v) for k,v in raw.items()}
def conf(tsv,n):
    if not Path(tsv).exists(): return np.empty((n,0))
    df=pd.read_csv(tsv,sep='\t').iloc[:n]; keep=[c for c in df.columns if c.lower().startswith(('trans_','rot_','cosine','retroicor'))]
    if not keep: return np.empty((n,0))
    X=df[keep].to_numpy(float); X[np.isnan(X)]=0; return X[:,X.std(0)>1e-9]
def side_of(c):
    c=c.lower().replace('-','').replace('_','')
    return 'L' if ('left' in c or c.endswith('l')) else ('R' if ('right' in c or c.endswith('r')) else None)
CFG={'openneuro_ds004926_dorsalhorn_pain':('dorsal','L','pain'),
     'openneuro_ds005883_cospine_pain':('dorsal','R','pain'),
     'openneuro_ds004616_spinalcord_handgrasp_task':('ventral',None,'motor'),
     'openneuro_ds005884_cospine_motor':('ventral',None,'motor')}
FRACS=[0.25,0.5,0.75,1.0]
acc=defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # frac -> ds -> sub -> [eff]
dur_min=defaultdict(list)
for run in driver.iter_runs(Path("/mnt/ssd1/spineprep_cohort_s2")):
    ds=run["dataset"]
    if ds not in CFG: continue
    conds=conditions_for(ds,run["run_id"])
    if not conds: continue
    parcels,_=driver.build_parcels(run)
    if "gmhorn" not in parcels: continue
    root=roots.get(ds); ev=next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")),None) if root else None
    if ev is None: continue
    rows=list(csv.DictReader(open(ev),delimiter='\t'))
    sc=Path(str(run["bold"]).replace(".nii.gz",".json")); stt=float(json.loads(sc.read_text()).get("StartTime") or 0.0) if sc.exists() else 0.0
    data=np.asarray(nib.load(str(run["bold"])).dataobj,dtype=np.float32)
    if data.ndim!=4: continue
    tr=repetition_time_s(run["bold"]); nvol=data.shape[3]
    Xt,names=build_task_design(corrected_events(ds,rows,stt,run["run_id"]),nvol,tr,conds)
    if Xt.shape[1]==0: continue
    Xn=conf(run["confounds"],nvol); X=np.column_stack([Xt,Xn,np.ones(nvol)]) if Xn.size else np.column_stack([Xt,np.ones(nvol)])
    if np.linalg.matrix_rank(X)<X.shape[1]: X=np.column_stack([Xt,np.ones(nvol)])
    cord=parcels["cord"]["cord"]; midx=np.argwhere(cord); Yall=data[cord].T.astype(float)
    ht,fixed,par=CFG[ds]
    for f in FRACS:
        nk=int(nvol*f)
        if nk<40: continue
        idx=np.arange(nk); odd=idx[0::2]; even=idx[1::2]
        def fit(ix):
            Y=Yall[ix]-Yall[ix].mean(0,keepdims=True); Xs=X[ix]
            if Xs.shape[0]<=Xs.shape[1] or np.linalg.matrix_rank(Xs)<Xs.shape[1]: return None
            b,*_=np.linalg.lstsq(Xs,Y,rcond=None); return b
        b1,b2=fit(odd),fit(even)
        if b1 is None or b2 is None: continue
        vals=[]
        for ci,cn in enumerate(names):
            s=side_of(cn) or fixed
            if s is None: continue
            m=parcels['gmhorn'].get(f'gm-{ht}-{s}')
            if m is None: continue
            fl=m[tuple(midx.T)]
            if fl.sum()<10: continue
            v1,v2=b1[ci][fl],b2[ci][fl]; k=max(1,int(0.1*len(v1)))
            vals.append(float(v2[np.argsort(v1)[-k:]].mean()))
        if vals: acc[f][ds][run["subject"]].append(float(np.mean(vals)))
        if f==1.0: dur_min[ds].append(nvol*tr/60)
short=lambda ds: ds.split('_')[1] if ds.split('_')[0]=='openneuro' else ds.split('_')[2]
print("=== SCAN-DURATION SCALING: unbiased group effect d vs fraction of run ===")
print(f"{'dataset':12} {'full_min':>8} " + " ".join(f"{int(f*100)}%".rjust(7) for f in FRACS))
for ds in CFG:
    if not any(ds in acc[f] for f in FRACS): continue
    dm=st.mean(dur_min[ds]) if dur_min[ds] else 0
    cells=[]
    for f in FRACS:
        vals=[st.mean(v) for v in acc[f].get(ds,{}).values() if v]
        if len(vals)>=5:
            d=np.mean(vals)/np.std(vals,ddof=1); cells.append(f"{d:+.2f}")
        else: cells.append("  -")
    print(f"  {short(ds):12} {dm:8.1f} " + " ".join(c.rjust(7) for c in cells))
print("\n(d rising with duration = scanning longer helps; flat = duration-saturated)")
