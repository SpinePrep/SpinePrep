import sys,csv,json; sys.path.insert(0,'/mnt/ssd1/SpinePrep')
from pathlib import Path
from collections import defaultdict
import numpy as np, yaml, statistics as st
from analysis import driver
from analysis.glm import build_task_design
from analysis.glm_spec import conditions_for, corrected_events, repetition_time_s
import nibabel as nib, pandas as pd
from scipy import stats as sps, ndimage
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
DS="openneuro_ds004616_spinalcord_handgrasp_task"   # strongest laterality dataset
SMOOTH_MM=[0,2,4,6]        # in-plane FWHM (mm); cord is ~5-7mm wide
res=defaultdict(lambda: {'det':[], 'lat':[], 'nact':[]})
nrun=0
for run in driver.iter_runs(Path("/mnt/ssd1/spineprep_cohort_s2")):
    if run["dataset"]!=DS: continue
    conds=conditions_for(DS,run["run_id"])
    if not conds: continue
    parcels,_=driver.build_parcels(run)
    if "hemicord" not in parcels: continue
    root=roots.get(DS); ev=next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")),None)
    if ev is None: continue
    rows=list(csv.DictReader(open(ev),delimiter='\t'))
    sc=Path(str(run["bold"]).replace(".nii.gz",".json")); stt=float(json.loads(sc.read_text()).get("StartTime") or 0.0) if sc.exists() else 0.0
    img=nib.load(str(run["bold"])); data=np.asarray(img.dataobj,dtype=np.float32)
    if data.ndim!=4: continue
    zooms=img.header.get_zooms()[:3]
    tr=repetition_time_s(run["bold"]); nvol=data.shape[3]
    Xt,names=build_task_design(corrected_events(DS,rows,stt,run["run_id"]),nvol,tr,conds)
    if Xt.shape[1]==0: continue
    Xn=conf(run["confounds"],nvol); X=np.column_stack([Xt,Xn,np.ones(nvol)]) if Xn.size else np.column_stack([Xt,np.ones(nvol)])
    if np.linalg.matrix_rank(X)<X.shape[1]: X=np.column_stack([Xt,np.ones(nvol)])
    cord=parcels["cord"]["cord"]; midx=np.argwhere(cord)
    L=parcels["hemicord"].get("hemicord-L"); R=parcels["hemicord"].get("hemicord-R")
    if L is None or R is None: continue
    nrun+=1
    for fwhm in SMOOTH_MM:
        if fwhm==0: d4=data
        else:
            sig=[(fwhm/2.355)/z for z in zooms]   # in-plane + through-plane in voxels
            d4=ndimage.gaussian_filter(data,sigma=(sig[0],sig[1],sig[2],0),mode='nearest')
        Y=d4[cord].T.astype(float); Y=Y-Y.mean(0,keepdims=True)
        if Y.shape[0]!=nvol: continue
        beta,*_=np.linalg.lstsq(X,Y,rcond=None); dof=nvol-X.shape[1]
        yhat=X@beta; sig2=((Y-yhat)**2).sum(0)/dof; XtXi=np.linalg.pinv(X.T@X)
        for ci,cn in enumerate(names):
            s=side_of(cn)
            if s is None: continue
            t=beta[ci]/np.sqrt(np.maximum(sig2*XtXi[ci,ci],1e-20))
            fi=(L if s=='L' else R)[tuple(midx.T)]; fc=(R if s=='L' else L)[tuple(midx.T)]
            ni=(t[fi]>2).sum(); nc=(t[fc]>2).sum()
            k=max(1,int(0.1*fi.sum()))
            res[fwhm]['det'].append(float(np.sort(beta[ci][fi])[-k:].mean()))
            res[fwhm]['nact'].append(int(ni+nc))
            if ni+nc>0: res[fwhm]['lat'].append((ni-nc)/(ni+nc))
print(f"=== SMOOTHING TRADEOFF, ds004616 handgrasp ({nrun} runs) ===")
print(f"{'FWHM':>6} {'active vox':>11} {'detect (top10%)':>16} {'laterality LI':>14} {'%ipsi-dominant':>15}")
for f in SMOOTH_MM:
    r=res[f]
    if not r['det']: continue
    li=r['lat']; pos=np.mean([x>0 for x in li]) if li else float('nan')
    print(f"  {f:>4}mm {st.mean(r['nact']):11.0f} {st.mean(r['det']):16.4f} {st.median(li):+14.2f} {pos*100:14.0f}%")
print("\n(if active-vox rises but LI/%ipsi falls -> smoothing buys detectability by destroying specificity)")
