"""T2.1 physio benefit by cord location | T2.2 high-pass cutoff | T2.3 normalization-error consequence"""
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
def side_of(c):
    c=c.lower().replace('-','').replace('_','')
    return 'L' if ('left' in c or c.endswith('l')) else ('R' if ('right' in c or c.endswith('r')) else None)
CFG={'openneuro_ds004616_spinalcord_handgrasp_task':('ventral',None,'motor'),
     'openneuro_ds005884_cospine_motor':('ventral',None,'motor'),
     'openneuro_ds004926_dorsalhorn_pain':('dorsal','L','pain'),
     'openneuro_ds005883_cospine_pain':('dorsal','R','pain')}
physio=defaultdict(lambda: defaultdict(list))     # ds -> zone -> [R2 gain from retroicor]
hp=defaultdict(lambda: defaultdict(list))         # hp arm -> (ds,sub) -> [eff]
peaks=defaultdict(lambda: defaultdict(list))      # ds -> sub -> [(x,y,z) mm of peak]
HP=['none','quarter','half','all']
nrun=0
for run in driver.iter_runs(Path("/mnt/ssd1/spineprep_cohort_s2")):
    ds=run["dataset"]
    if ds not in CFG: continue
    conds=conditions_for(ds,run["run_id"])
    if not conds: continue
    parcels,_=driver.build_parcels(run)
    if "gmhorn" not in parcels: continue
    root=roots.get(ds); ev=next(iter(Path(root).rglob(f"{run['run_id']}_events.tsv")),None)
    if ev is None: continue
    rows=list(csv.DictReader(open(ev),delimiter='\t'))
    sc=Path(str(run["bold"]).replace(".nii.gz",".json")); stt=float(json.loads(sc.read_text()).get("StartTime") or 0.0) if sc.exists() else 0.0
    try:
        img=nib.load(str(run["bold"])); data=np.asarray(img.dataobj,dtype=np.float32)
    except Exception: continue
    if data.ndim!=4: continue
    zooms=img.header.get_zooms()[:3]
    tr=repetition_time_s(run["bold"]); nvol=data.shape[3]
    Xt,names=build_task_design(corrected_events(ds,rows,stt,run["run_id"]),nvol,tr,conds)
    if Xt.shape[1]==0: continue
    ct=Path(run["confounds"])
    if not ct.exists(): continue
    df=pd.read_csv(ct,sep='\t').iloc[:nvol]
    def mat(cols):
        if not cols: return np.empty((nvol,0))
        X=df[cols].to_numpy(float); X[np.isnan(X)]=0; return X[:,X.std(0)>1e-9]
    mot=mat([c for c in df.columns if c.lower().startswith(('trans_','rot_'))])
    cos=[c for c in df.columns if c.lower().startswith('cosine')]
    ret=mat([c for c in df.columns if c.lower().startswith('retroicor')])
    cord=parcels["cord"]["cord"]; midx=np.argwhere(cord); nrun+=1
    ht,fixed,par=CFG[ds]
    # ---------- T2.1 physio benefit: cord CORE vs RIM (rim = adjacent to CSF) ----------
    core=ndimage.binary_erosion(cord,iterations=1)
    rim=cord & ~core
    if ret.size and core.sum()>20 and rim.sum()>20:
        Xbase=np.column_stack([Xt,mot,mat(cos),np.ones(nvol)])
        Xful=np.column_stack([Xbase,ret])
        for zone,m in (('core',core),('rim',rim)):
            Y=data[m].T.astype(float); Y=Y-Y.mean(0,keepdims=True)
            if Y.shape[0]!=nvol: continue
            def r2(X):
                b,*_=np.linalg.lstsq(X,Y,rcond=None); res=Y-X@b
                return 1-(res**2).sum()/max((Y**2).sum(),1e-9)
            try: physio[ds][zone].append(r2(Xful)-r2(Xbase))
            except Exception: pass
    # ---------- T2.2 high-pass cutoff (subset the cosine basis) ----------
    L=parcels['gmhorn'].get(f'gm-{ht}-L'); R=parcels['gmhorn'].get(f'gm-{ht}-R')
    for arm in HP:
        k={'none':0,'quarter':max(1,len(cos)//4),'half':max(1,len(cos)//2),'all':len(cos)}[arm]
        Xc=mat(cos[:k]) if k else np.empty((nvol,0))
        X=np.column_stack([Xt,mot,Xc,ret,np.ones(nvol)]) if ret.size else np.column_stack([Xt,mot,Xc,np.ones(nvol)])
        if np.linalg.matrix_rank(X)<X.shape[1]: continue
        Yall=data[cord].T.astype(float)
        odd=np.arange(0,nvol,2); even=np.arange(1,nvol,2)
        def fit(ix):
            Y=Yall[ix]-Yall[ix].mean(0,keepdims=True); Xs=X[ix]
            if np.linalg.matrix_rank(Xs)<Xs.shape[1]: return None
            b,*_=np.linalg.lstsq(Xs,Y,rcond=None); return b
        b1,b2=fit(odd),fit(even)
        if b1 is None or b2 is None: continue
        for ci,cn in enumerate(names):
            sd=side_of(cn) or fixed
            if sd is None: continue
            m=(L if sd=='L' else R)
            if m is None: continue
            fi=m[tuple(midx.T)]
            if fi.sum()<10: continue
            v1,v2=b1[ci][fi],b2[ci][fi]; kk=max(1,int(0.1*len(v1)))
            hp[arm][(ds,run['subject'])].append(float(v2[np.argsort(v1)[-kk:]].mean()))
    # ---------- T2.3 where is each subject's peak? (scatter = normalization+anatomy variability) ----------
    Xf=np.column_stack([Xt,mot,mat(cos),ret,np.ones(nvol)]) if ret.size else np.column_stack([Xt,mot,mat(cos),np.ones(nvol)])
    if np.linalg.matrix_rank(Xf)>=Xf.shape[1]:
        Y=data[cord].T.astype(float); Y=Y-Y.mean(0,keepdims=True)
        if Y.shape[0]==nvol:
            b,*_=np.linalg.lstsq(Xf,Y,rcond=None)
            for ci,cn in enumerate(names):
                sd=side_of(cn) or fixed
                if sd is None: continue
                m=(L if sd=='L' else R)
                if m is None: continue
                fi=m[tuple(midx.T)]
                if fi.sum()<10: continue
                pk=midx[fi][np.argmax(b[ci][fi])]
                peaks[ds][run['subject']].append(tuple(float(pk[i]*zooms[i]) for i in range(3)))
short=lambda ds: ds.split('_')[1] if ds.split('_')[0]=='openneuro' else ds.split('_')[2]
print(f"### runs analysed: {nrun}\n")
print("=== T2.1  does RETROICOR help more at the cord RIM (next to CSF) than the CORE? ===")
print(f"{'dataset':11} {'core R2 gain':>13} {'rim R2 gain':>12} {'rim/core':>9}")
for ds in CFG:
    c,r=physio[ds]['core'],physio[ds]['rim']
    if len(c)>=5 and len(r)>=5:
        mc,mr=st.median(c),st.median(r)
        print(f"  {short(ds):11} {mc:13.4f} {mr:12.4f} {(mr/mc if mc>0 else float('nan')):9.2f}")
print("\n=== T2.2  high-pass filtering: group detectability (unbiased CV, top10) ===")
print(f"{'dataset':11} " + " ".join(a.rjust(9) for a in HP) + "   <- group d")
for ds in CFG:
    cells=[]
    for a in HP:
        vals=[st.mean(v) for (d2,s),v in hp[a].items() if d2==ds and v]
        if len(vals)>=5:
            d=np.mean(vals)/np.std(vals,ddof=1); cells.append(f"{d:+.2f}")
        else: cells.append("  -")
    print(f"  {short(ds):11} " + " ".join(c.rjust(9) for c in cells))
print("\n=== T2.3  across-subject scatter of the peak-activation location (mm) ===")
print(f"{'dataset':11} {'N':>3} {'SD x':>6} {'SD y':>6} {'SD z':>7}   vs horn size (~2-3mm across)")
for ds in CFG:
    pts=[np.mean(np.array(v),axis=0) for v in peaks[ds].values() if v]
    if len(pts)<5: continue
    A=np.array(pts); sd=A.std(0,ddof=1)
    print(f"  {short(ds):11} {len(pts):3} {sd[0]:6.2f} {sd[1]:6.2f} {sd[2]:7.2f}")
print("\n(if SD >> horn width, between-subject localisation variability caps horn-scale group inference)")
