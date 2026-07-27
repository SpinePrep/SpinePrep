import numpy as np, statistics as st
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.linewidth':0.8,
 'axes.spines.top':False,'axes.spines.right':False,'axes.titlesize':10,
 'axes.titleweight':'bold','savefig.dpi':200})
# group detectability d (top-10%, unbiased CV) per dataset per arm  [T1.2 output]
D={'ds004616':{'base':1.12,'motion':0.90,'cens0.5':0.59,'censP90':1.30},
   'ds005884':{'base':0.56,'motion':0.41,'cens0.5':0.29,'censP90':0.73},
   'ds004926':{'base':0.23,'motion':0.11,'cens0.5':0.32,'censP90':0.24},
   'ds005883':{'base':0.41,'motion':0.44,'cens0.5':0.50,'censP90':0.33}}
MEAN={'ds004616':-0.35,'ds005884':0.10,'ds004926':0.11,'ds005883':-0.17}   # T1.3 parcel-mean
TOP ={'ds004616':0.90,'ds005884':0.41,'ds004926':0.11,'ds005883':0.44}
def pct(new,old): return (new-old)/abs(old)*100 if abs(old)>1e-9 else np.nan
CH=[]
CH.append(("ROI summary: parcel-MEAN\ninstead of top-10%", [pct(MEAN[k],TOP[k]) for k in D], 'measure'))
CH.append(("FD censoring @0.5 mm\n(brain-derived, 24% of frames)", [pct(D[k]['cens0.5'],D[k]['motion']) for k in D], 'imported'))
CH.append(("motion regressors added", [pct(D[k]['motion'],D[k]['base']) for k in D], 'choice'))
CH.append(("smoothing 4 mm FWHM", [30.0], 'choice'))
CH.append(("FD censoring @worst-10%\n(cord-derived)", [pct(D[k]['censP90'],D[k]['motion']) for k in D], 'cord-fix'))
med=lambda v:[x for x in v if np.isfinite(x)]
CH.sort(key=lambda c: st.median(med(c[1])))
COL={'measure':'#6a3d9a','imported':'#b2182b','choice':'#2166ac','cord-fix':'#1b7837'}
fig,(a1,a2)=plt.subplots(1,2,figsize=(11,4.4),gridspec_kw={'wspace':0.55,'width_ratios':[1.5,1]})
ys=range(len(CH))
for y,(lab,vals,kind) in zip(ys,CH):
    v=med(vals); m=st.median(v)
    a1.barh(y,m,color=COL[kind],alpha=0.85,height=0.6,zorder=2)
    if len(v)>1: a1.scatter(v,[y]*len(v),color='0.25',s=16,zorder=4,alpha=0.85)
    a1.text(m+(6 if m>=0 else -6),y,f"{m:+.0f}%",va='center',ha='left' if m>=0 else 'right',
            fontsize=9,fontweight='bold',color=COL[kind])
a1.axvline(0,color='0.3',lw=1)
a1.set_yticks(list(ys)); a1.set_yticklabels([c[0] for c in CH],fontsize=8)
a1.set_xlabel('change in group detectability (%)',fontsize=9)
a1.set_title('a   What each processing choice costs or buys',loc='left',fontsize=9.6)
a1.set_xlim(-115,115)
from matplotlib.patches import Patch
a1.legend(handles=[Patch(color=COL['imported'],label='imported from brain — harmful'),
                   Patch(color=COL['cord-fix'],label='cord-derived alternative — helps'),
                   Patch(color=COL['choice'],label='processing choice'),
                   Patch(color=COL['measure'],label='measurement choice')],
          fontsize=7,frameon=False,loc='lower right')
# Panel B: distortion, the arm with a MEASURED ground truth
arms=['no correction','image-based SyN\n(fallback)','measured field\n(TopUp)']
disp=[3.339,2.215,0.608]; cols=['0.55','#b2182b','#1b7837']
a2.bar(range(3),disp,color=cols,alpha=0.9,width=0.62)
for i,(d,c) in enumerate(zip(disp,cols)):
    a2.text(i,d+0.09,f"{d:.2f}",ha='center',fontsize=9,fontweight='bold',color=c)
a2.set_xticks(range(3)); a2.set_xticklabels(arms,fontsize=7.6)
a2.set_ylabel('cord displacement from anatomy (mm)',fontsize=9)
a2.set_title('b   Distortion: the arm with physical ground truth',loc='left',fontsize=9.6)
a2.set_ylim(0,3.9)
a2.text(1,2.55,'harms 28%\nof runs',ha='center',fontsize=7.2,color='#b2182b',style='italic')
a2.text(2,0.95,'−82%',ha='center',fontsize=8,color='#1b7837',fontweight='bold')
fig.text(0.5,1.015,'The cord is not a small brain: preprocessing conventions imported from brain fMRI misfire here',
         ha='center',fontsize=11,fontweight='bold')
fig.text(0.5,-0.05,'dots = individual datasets (n=4); bars = median. Detectability = unbiased cross-validated group effect size at the a-priori focal horn.',
         ha='center',fontsize=6.8,color='0.45')
out='/tmp/claude-1000/-mnt-ssd1-SpinePrep/f4e0bb8b-cddd-41fb-aa92-db62665bad69/scratchpad/clean/F_integrative.png'
fig.savefig(out,bbox_inches='tight'); print("wrote",out)
for lab,vals,kind in CH: print(f"  {lab.replace(chr(10),' '):48} median {st.median(med(vals)):+7.1f}%  (n={len(med(vals))})")
