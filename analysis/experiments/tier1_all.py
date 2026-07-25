"""T1.1 task-correlated motion regression | T1.2 FD censoring | T1.3 ROI summary
measure | T1.4 conclusion robustness.  One pass, shared GLM machinery."""
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
def side_of(c):
    c=c.lower().replace('-','').replace('_','')
    return 'L' if ('left' in c or c.endswith('l')) else ('R' if ('right' in c or c.endswith('r')) else None)
CFG={'openneuro_ds004616_spinalcord_handgrasp_task':('ventral',None,'motor'),
     'openneuro_ds005884_cospine_motor':('ventral',None,'motor'),
     'openneuro_ds004926_dorsalhorn_pain':('dorsal','L','pain'),
     'openneuro_ds005883_cospine_pain':('dorsal','R','pain')}
MEAS=['mean','top10','peak','nsupra']
ARMS=['base','+motion','+motion+censor0.5','+motion+censorP90']
eff=defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # arm -> meas -> (ds,sub) -> [v]
lat=defaultdict(lambda: defaultdict(list))                        # arm -> ds -> [LI]
mtcorr=defaultdict(list)                                          # ds -> [max |r| motion vs task]
censfrac=defaultdict(list)
nrun=0
for run in driver.iter_runs(Path("/mnt/ssd1/spineprep_cohort_s2")):
    ds=run["dataset"]
    if ds not in CFG: continue
    conds=conditions_for(ds,run["run_id"])
    if not conds: continue
    parcels,_=driver.build_parcels(run)
    if "hemicord" not in parcels or "gmhorn" not in parcels: continue
    root=roots.get(ds); ev=next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")),None)
    if ev is None: continue
    rows=list(csv.DictReader(open(ev),delimiter='\t'))
    sc=Path(str(run["bold"]).replace(".nii.gz",".json")); stt=float(json.loads(sc.read_text()).get("StartTime") or 0.0) if sc.exists() else 0.0
    try: data=np.asarray(nib.load(str(run["bold"])).dataobj,dtype=np.float32)
    except Exception: continue
    if data.ndim!=4: continue
    tr=repetition_time_s(run["bold"]); nvol=data.shape[3]
    Xt,names=build_task_design(corrected_events(ds,rows,stt,run["run_id"]),nvol,tr,conds)
    if Xt.shape[1]==0: continue
    ct=Path(run["confounds"])
    if not ct.exists(): continue
    df=pd.read_csv(ct,sep='\t').iloc[:nvol]
    mot=[c for c in df.columns if c.lower().startswith(('trans_','rot_'))]
    base=[c for c in df.columns if c.lower().startswith(('cosine','retroicor'))]
    def mat(cols):
        if not cols: return np.empty((nvol,0))
        X=df[cols].to_numpy(float); X[np.isnan(X)]=0; return X[:,X.std(0)>1e-9]
    Xm, Xb = mat(mot), mat(base)
    # ---- T1.1: how task-correlated are the motion regressors? ----
    if Xm.size:
        rr=[abs(np.corrcoef(Xm[:,j],Xt[:,i])[0,1]) for j in range(Xm.shape[1]) for i in range(Xt.shape[1])]
        rr=[x for x in rr if np.isfinite(x)]
        if rr: mtcorr[ds].append(max(rr))
    fd=df['framewise_displacement'].to_numpy(float) if 'framewise_displacement' in df else np.zeros(nvol)
    fd=np.nan_to_num(fd)
    nrun+=1
    cord=parcels["cord"]["cord"]; midx=np.argwhere(cord)
    L=parcels["hemicord"].get("hemicord-L"); R=parcels["hemicord"].get("hemicord-R")
    ht,fixed,par=CFG[ds]
    Yall=data[cord].T.astype(float)
    for arm in ARMS:
        keep=np.ones(nvol,bool)
        if 'censor0.5' in arm: keep=fd<=0.5
        if 'censorP90' in arm: keep=fd<=np.percentile(fd,90)
        Xn=np.column_stack([Xb,Xm]) if ('motion' in arm and Xm.size) else Xb
        X=np.column_stack([Xt,Xn,np.ones(nvol)]) if Xn.size else np.column_stack([Xt,np.ones(nvol)])
        if 'censor' in arm: censfrac[arm].append(1-keep.mean())
        idx=np.where(keep)[0]
        if len(idx)<50: continue
        odd=idx[0::2]; even=idx[1::2]
        def fit(ix):
            if len(ix)<=X.shape[1]: return None,None
            Y=Yall[ix]-Yall[ix].mean(0,keepdims=True); Xs=X[ix]
            if np.linalg.matrix_rank(Xs)<Xs.shape[1]: return None,None
            b,*_=np.linalg.lstsq(Xs,Y,rcond=None)
            yh=Xs@b; dof=len(ix)-Xs.shape[1]
            s2=((Y-yh)**2).sum(0)/max(dof,1); XtXi=np.linalg.pinv(Xs.T@Xs)
            return b,(b[:len(names)]/np.sqrt(np.maximum(s2*np.diag(XtXi)[:len(names),None],1e-20)))
        b1,_=fit(odd); b2,_=fit(even); bf,tf=fit(idx)
        if b1 is None or b2 is None or bf is None: continue
        for ci,cn in enumerate(names):
            sd=side_of(cn) or fixed
            if sd is None: continue
            fi=(L if sd=='L' else R)[tuple(midx.T)]; fc=(R if sd=='L' else L)[tuple(midx.T)]
            if fi.sum()<10: continue
            v1,v2=b1[ci][fi],b2[ci][fi]; k=max(1,int(0.1*len(v1)))
            top=np.argsort(v1)[-k:]
            key=(ds,run['subject'])
            eff[arm]['top10'][key].append(float(v2[top].mean()))
            eff[arm]['mean'][key].append(float(v2.mean()))
            eff[arm]['peak'][key].append(float(v2[np.argmax(v1)]))
            eff[arm]['nsupra'][key].append(float((tf[ci][fi]>2).sum()))
            ni=(tf[ci][fi]>2).sum(); nc=(tf[ci][fc]>2).sum()
            if ni+nc>0: lat[arm][ds].append((ni-nc)/(ni+nc))
short=lambda ds: ds.split('_')[1] if ds.split('_')[0]=='openneuro' else ds.split('_')[2]
print(f"### runs analysed: {nrun}\n")
print("=== T1.1  motion regressors vs task design: max |r| ===")
for ds in CFG:
    if mtcorr[ds]: print(f"  {short(ds):11} {CFG[ds][2]:6} median max|r| = {st.median(mtcorr[ds]):.3f}  (n={len(mtcorr[ds])})")
print("\n=== T1.3  does the ROI SUMMARY MEASURE decide the answer? (arm=+motion) ===")
print(f"{'dataset':11} " + " ".join(m.rjust(9) for m in MEAS) + "   <- group d")
for ds in CFG:
    cells=[]
    for m in MEAS:
        vals=[st.mean(v) for (d2,s),v in eff['+motion'][m].items() if d2==ds and v]
        if len(vals)>=5:
            d=np.mean(vals)/np.std(vals,ddof=1); cells.append(f"{d:+.2f}")
        else: cells.append("  -")
    print(f"  {short(ds):11} " + " ".join(c.rjust(9) for c in cells))
print("\n=== T1.1/T1.2  nuisance arm effect on group d (top10) + laterality ===")
print(f"{'dataset':11} {'arm':20} {'group_d':>8} {'p':>9} {'LI':>7} {'%censored':>10}")
for ds in CFG:
    for arm in ARMS:
        vals=[st.mean(v) for (d2,s),v in eff[arm]['top10'].items() if d2==ds and v]
        if len(vals)<5: continue
        t,p=sps.ttest_1samp(vals,0); d=np.mean(vals)/np.std(vals,ddof=1)
        li=st.median(lat[arm][ds]) if lat[arm][ds] else float('nan')
        cf=st.mean(censfrac[arm])*100 if censfrac[arm] else 0
        print(f"  {short(ds):11} {arm:20} {d:+8.2f} {p:9.5f} {li:+7.2f} {cf:9.0f}%")
print("\n=== T1.4  conclusion robustness: does laterality SIGN ever flip across arms? ===")
for ds in CFG:
    sg=[np.sign(st.median(lat[a][ds])) for a in ARMS if lat[a][ds]]
    if sg: print(f"  {short(ds):11} laterality signs across arms: {sg}  -> {'STABLE' if len(set(sg))==1 else 'FLIPS'}")
