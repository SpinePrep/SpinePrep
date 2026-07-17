---
status: approved
extends: s6-algorithm-audit.md
---

# S6 algorithm audit v2 — citation truth, Dice circularity

Written 2026-07-16. The v1 audit found ten implementation issues (dead code,
stale docstring, threshold-vs-policy mismatch, T2star modality, reportlet
contour) and they are FIXED in the current code — verified. This pass re-checked
S6's **claims** against Kaptan's actual published code and SCT's docs, and
examined the QC metric. The registration engine is sound; the story around it is
not.

**Headline: the recipe is described as "the Kaptan 2023 Eippert-lab verbatim
chain". It is not. Kaptan's code is a different chain, with a different target.
And the QC metric is the registration's own objective.**

## What Kaptan 2023 actually does (verified from their code)

Kaptan et al. 2023's published preprocessing code
(`github.com/eippertlab/restingstate-reliability-spinalcord`,
`II_III_II_REL_Preprocessing.m` lines 549-556) registers with:

```
sct_register_multimodal -i PAM50_t2 -d func_mean -iseg PAM50_cord -dseg ...
  -param step=1,type=seg,algo=centermass:step=2,type=seg,algo=bsplinesyn,\
         metric=MeanSquares,smooth=1,slicewise=1,iter=3
  -initwarp warp_PAM502T2 -initwarpinv warp_T22PAM50
```

So Kaptan's chain is **two steps** (`centermass` → `bsplinesyn`, iter=3), and it
registers the **PAM50 template to the functional mean directly**, initialised by
the anatomy→template warp. The paper says so in prose: "The T2-weighted PAM50
template was registered to the mean of motion-corrected functional images …
(with the initial step using the inverse warping field obtained from the
registration of the T2-weighted anatomical image to the template image)."

SpinePrep's chain is `centermassrot → columnwise → bsplinesyn (iter=20)`,
registering **func → the subject's own anatomy**. It differs from Kaptan on:
- step count: 3 vs 2;
- first algorithm: `centermassrot` (with rotation) vs `centermass`;
- the inserted `columnwise` step, which Kaptan does not use;
- iterations: 20 vs 3;
- the target: func→own-anat vs template→func-direct.

"Kaptan 2023 verbatim" is false on every one of those axes.

## What SCT actually recommends (verified)

- SCT's **default** `sct_register_to_template` chain is `centermassrot →
  bsplinesyn` — also two steps. `columnwise` and `iter=20` are **not** SCT
  defaults; both are SpinePrep tuning.
- SCT's **fMRI tutorial** registers template→func with a single **intensity**
  step (`type=im,algo=syn,metric=CC,iter=5`), reusing the anat↔template warp —
  not a seg chain at all, because thick-slice axial fMRI lacks the vertebral
  labels `sct_register_to_template` needs.
- Algorithm definitions (SCT docs, verified): `centermassrot` = "slicewise
  center of mass and rotation alignment"; `columnwise` = "R-L scaling followed by
  A-P columnwise alignment (seg only)"; `bsplinesyn` = "syn regularized with
  b-splines".

So the recipe is a legitimate SCT seg-driven chain built from real SCT
primitives, but it is SpinePrep's own composition — not verbatim from Kaptan and
not SCT's default.

## Findings

### F1 — "Kaptan 2023 verbatim" / "field-standard" is a mis-claim — FIX
The attribution appears in four places: `policy/S6_...yaml:3` ("the Kaptan 2023
Eippert-lab verbatim chain"), `process.py` module docstring ("Kaptan 2023"),
`.claude/specs/s6-func-to-anat-registration.md` ("also adopted by Kaptan 2023"),
and `docs/methods/S6_registration.md:35` ("the cord-fMRI field-standard recipe …
also used under Kaptan 2023 SCT conventions"). None survives contact with
Kaptan's code. Honest description: **SpinePrep's own seg-driven chain, built from
SCT's standard registration primitives (the centermassrot/columnwise/bsplinesyn
family; cf. SCT's default centermassrot→bsplinesyn), in the template-to-native
spirit of Kaptan et al. 2023 but not identical to it.** The `spi06_1fov_reg.sh`
CoSpi origin is the operator's, so "field-standard" is also wrong — the same
over-claim corrected for S5's "field-standard ladder".

### F2 — the Dice threshold citations are unverified, and one is the wrong metric — FIX
`policy/S6_...yaml:46-52` justifies `pass_dice_min: 0.85` with "Cohen-Adad 2014,
De Leener 2017, Gros 2019 … report cord-seg/registration Dice in the ~0.85-0.95
band". Checked:
- **Gros 2019 reports SEGMENTATION Dice** (auto vs manual mask, ~0.9), **not
  registration Dice** — a different quantity, and the paper gives no circularity
  caveat.
- **De Leener 2017 and Cohen-Adad 2014**: no cord-*registration* Dice 0.85-0.95
  band was found in either. UNVERIFIED.
So the 0.85 bar is not grounded in the cited papers. It is a reasonable
engineering choice on cord-cropped EPI, but it must be stated as SpinePrep's
operating point, not as a literature-reported band. (Segmentation-Dice papers may
be cited for what a *good cord mask overlap* looks like, but not for a
registration threshold.)

### F3 — cord Dice is the registration's own objective (circular) — DISCLOSE
S6's registration cost is `type=seg` MeanSquares on the EPI and anat cord masks —
the optimiser explicitly maximises cord-mask overlap (`process.py:142` `-iseg`,
`:144` `-dseg`). The QC then measures Dice between those same two masks
(`process.py:477`). A high Dice therefore mostly confirms the optimiser converged
on its own objective, not that the registration is anatomically correct. Two
failure modes it structurally cannot catch:
- **axial mis-registration**: Dice on a smooth near-cylindrical cord is nearly
  invariant to shifts along the cord axis, so a run mis-levelled in Z can still
  score high Dice;
- **intensity/anatomy mismatch inside the cord**, which a mask-overlap metric
  never sees.
An INDEPENDENT check would be vertebral-level / disc-label agreement along Z
(orthogonal to mask overlap — the strongest option, since Dice is blind to axial
error), or intensity agreement (EPI vs anat cross-correlation, which the
registration did not optimise). HD95/ASD help with boundary outliers but are
computed on the same masks, so they are only partly independent. Recommendation:
keep Dice as a convergence check, add a level/landmark or intensity metric as the
independent validator, and disclose the circularity in the doc.

### F4 — the design is a variant, not the dominant pattern — DOCUMENT
S6 does an independent func→own-anat registration. Kaptan and SCT's fMRI tutorial
instead register template↔func **directly**, initialised by the anat↔template
warp, and never do a fresh func→own-anat step. CoSpine and Eippert 2017 do use a
func→structural→template two-hop, so the two-hop design is defensible and has
precedent — but it should be presented as a deliberate choice, not as the field
default. (No change to the algorithm; a framing fix in the doc.)

### F5 — the FASB nonlinear-warp objection partly applies — DOCUMENT
FASB argued against nonlinear warping of cord EPI ("non-optimal twisted warping
fields"), but their mechanism is intensity-driven: distortion and susceptibility
signal loss corrupt the EPI voxel intensities an image-based warp chases. S6's
`bsplinesyn` is **seg-driven** — it never sees those intensities, only the cord
outline — so it is partly insulated from FASB's specific failure mode. It is not
fully safe: `slicewise=1 bsplinesyn` optimises each 2D slice independently, so it
can still produce per-slice discontinuous along-Z deformation, and a near-circular
cord mask under-constrains rotation. Lower risk than intensity-driven SyN, not
zero. Worth one honest sentence in the doc's limitations. (The seg-vs-intensity
distinction is our reasoning; FASB itself does not draw it.)

### F6 — S6 has never run on the 466-run cohort — OPEN
Every S6 number (Dice 0.89-0.97, 11/11 PASS, wf_reg_066) is the retired 11-run
reg cohort. S6 depends on S5, whose held-out validation is running now. Until S6
runs on the 466, its numbers are not the paper's.

## Fixed in v1 (verified still fixed)
Dead helpers deleted; module docstring rewritten to the 3-stage recipe; T2star/
PD/T1map modality detection added; `_classify` defaults aligned to policy YAML;
reportlet contour switched from intensity-percentile to the cord segmentation.

## Open items, by priority
1. **F1** — correct the "Kaptan verbatim / field-standard" attribution in policy,
   module docstring, spec, and the public doc.
2. **F3** — disclose Dice circularity; add an independent level/intensity metric.
3. **F2** — reword the Dice-threshold justification; drop the registration-Dice
   band attribution (Gros is segmentation Dice).
4. **F6** — run S6 on the 466-run cohort after S5 settles; re-derive numbers.
5. **F4/F5** — framing sentences in the public doc.
