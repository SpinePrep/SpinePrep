"""Self-contained tutorial page for the SpinalfMRIprep QC dashboard.

Served by `dashboard_server` at GET /tutorial (and /tutorial/). Plain
HTML, no MathJax, no external CSS — same dark theme as the rest of the
chain via the constants in `reportlets_common`.

The page documents every algorithm + metric the operator encounters
when reading reportlets: DVARS, DVARS-ref, Tukey outlier rule, robust
funcref, sct_deepseg seg_sc_contrast_agnostic, brain-contamination
check, FD, cord-aware smoothing, PAM50 cord Dice, RETROICOR / PNM,
MP-PCA. One section per step (S1–S11) with concept summaries and
literature references.
"""

from __future__ import annotations

from .reportlets_common import BG, BORDER, MUTED, PANEL, TEXT


def render_tutorial_html() -> str:
    """Return the full HTML for the tutorial page."""
    # CSS uses the chain palette constants so any future palette tweak in
    # reportlets_common propagates here.
    css = f"""
        body {{ background: {BG}; color: {TEXT}; margin: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                             system-ui, sans-serif;
                font-size: 14px; line-height: 1.55; }}
        .wrap {{ max-width: 900px; margin: 0 auto;
                  padding: 28px 28px 96px 28px; }}
        h1 {{ font-size: 24px; margin: 0 0 6px 0; color: {TEXT};
               font-weight: 700; letter-spacing: 0.3px; }}
        h2 {{ font-size: 18px; margin: 32px 0 10px 0; color: {TEXT};
               border-bottom: 1px solid {BORDER}; padding-bottom: 6px; }}
        h3 {{ font-size: 15px; margin: 18px 0 6px 0; color: {TEXT};
               font-weight: 700; }}
        p, li {{ color: {TEXT}; }}
        .lead {{ color: {MUTED}; font-size: 13px; margin: 0 0 24px 0; }}
        a {{ color: #7dcfff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .topbar {{ display: flex; align-items: baseline;
                    gap: 12px; padding-bottom: 14px;
                    border-bottom: 1px solid {BORDER};
                    margin-bottom: 18px; }}
        .topbar .crumb {{ color: {MUTED}; font-size: 12px; }}
        code {{ background: {PANEL}; padding: 1px 6px; border-radius: 3px;
                 font-family: 'SF Mono', Menlo, Consolas, monospace;
                 color: {TEXT}; font-size: 12px; }}
        pre {{ background: {PANEL}; padding: 10px 12px; border-radius: 4px;
                border: 1px solid {BORDER}; overflow-x: auto;
                color: {TEXT}; font-size: 12px;
                font-family: 'SF Mono', Menlo, Consolas, monospace; }}
        .formula {{ background: {PANEL}; padding: 8px 12px;
                     border-left: 3px solid #7dcfff; border-radius: 3px;
                     font-family: 'SF Mono', Menlo, Consolas, monospace;
                     font-size: 13px; color: {TEXT}; margin: 8px 0; }}
        .ref {{ color: {MUTED}; font-size: 12px; margin-top: 6px; }}
        .ref::before {{ content: 'Ref: '; color: #7dcfff; }}
        .toc {{ background: {PANEL}; border: 1px solid {BORDER};
                 border-radius: 4px; padding: 12px 18px; margin: 8px 0 24px 0;
                 column-count: 2; column-gap: 30px; }}
        .toc a {{ display: block; padding: 2px 0; font-size: 13px; }}
        .step {{ background: {PANEL}; border: 1px solid {BORDER};
                  border-radius: 4px; padding: 14px 18px;
                  margin: 14px 0; }}
        .step h2 {{ margin-top: 0; border-bottom: 0; padding-bottom: 0; }}
        .deferred {{ color: {MUTED}; font-style: italic; }}
        .pill {{ display: inline-block; padding: 1px 7px; border-radius: 3px;
                  font-weight: 700; font-size: 11px; margin-right: 6px; }}
        .pill.standard {{ background: #14301e; color: #4ade80;
                           border: 1px solid #2a623d; }}
        .pill.novel {{ background: #3a2f00; color: #f59e0b;
                        border: 1px solid #6b4f00; }}
        .pill.deferred {{ background: {PANEL}; color: {MUTED};
                           border: 1px solid {BORDER}; }}
    """

    body_sections = [
        _section_concepts(),
        _section_S1(),
        _section_S2(),
        _section_S3(),
        _section_S4(),
        _section_S5(),
        _section_S6(),
        _section_S7(),
        _section_S8(),
        _section_S9(),
        _section_S11(),
    ]

    body = "\n".join(body_sections)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
<meta http-equiv="Pragma" content="no-cache" />
<meta http-equiv="Expires" content="0" />
<title>SpinalfMRIprep — Tutorial</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<div class="topbar">
<h1>SpinalfMRIprep — Tutorial</h1>
<span class="crumb"><a href="./">back to dashboard</a></span>
</div>
<p class="lead">A short reference for the algorithms and metrics the
reportlets display. One section per pipeline step. Formulas are plain
ASCII so the page is self-contained (no MathJax). Where a choice
deviates from a published convention, the deviation is documented in
<code>.claude/specs/s3-algorithm-audit.md</code> with literature
citations.</p>

<h2>Table of contents</h2>
<div class="toc">
<a href="#concepts">Core concepts</a>
<a href="#S1">S1 — input verify</a>
<a href="#S2">S2 — anat &amp; cord reference</a>
<a href="#S3">S3 — func init &amp; crop</a>
<a href="#S4">S4 — motion correction</a>
<a href="#S5">S5 — distortion correction</a>
<a href="#S6">S6 — func → anat registration</a>
<a href="#S7">S7 — template normalisation</a>
<a href="#S8">S8 — confounds &amp; physio</a>
<a href="#S9">S9 — primary functional derivatives</a>
<a href="#S11">S11 — QC aggregation &amp; release</a>
</div>

{body}

</div>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# Core concept sections — referenced from per-step sections
# ---------------------------------------------------------------------------


def _section_concepts() -> str:
    return """
<h2 id="concepts">Core concepts</h2>
<div class="step">
<h3>DVARS</h3>
<p>Root-mean-square of the temporal derivative of the BOLD signal,
restricted to the cord mask. Flags frame-to-frame intensity shifts
caused by motion, physiology, or transient artifacts.</p>
<div class="formula">
DVARS(t) = sqrt( mean_voxels-in-cord( (Y(v, t) - Y(v, t-1))^2 ) )
</div>
<p>For a brain-fMRI analog with the same restriction-to-mask logic,
see Power 2014. In SpinalfMRIprep we restrict the mean to the cord
voxels (Smyser 2019 / Kaptan 2023 cord adaptation), otherwise the
metric is dominated by background noise / shim drift outside the
cord.</p>
<p class="ref">Power JD et al., NeuroImage 2014. Smyser CD et al.,
NeuroImage 2019. Kaptan M et al., NeuroImage 2023.</p>
</div>

<div class="step">
<h3>DVARS-ref (a.k.a. refRMS)</h3>
<p>Root-mean-square of <code>(frame − reference)</code> within the
cord mask. Where DVARS measures frame-to-previous-frame change,
DVARS-ref measures frame-to-baseline divergence — a complementary
view that catches slow drift away from the run's reference even when
each frame-to-frame step is small.</p>
<div class="formula">
DVARS-ref(t) = sqrt( mean_voxels-in-cord( (Y(v, t) - Y_ref(v))^2 ) )
</div>
<p>Kaptan 2023 / Dabbagh 2024 introduce this metric for cord-fMRI
under the name <code>refRMS</code>; we use the literature-aligned
<code>DVARS-ref</code> in dashboard text. The on-disk TSV column is
<code>ref_rms</code> for backwards compatibility with the S8 confound
contract.</p>
<p class="ref">Kaptan M et al., NeuroImage 2023. Dabbagh A et al.,
NeuroImage 2024.</p>
</div>

<div class="step">
<h3>Tukey 1.5·IQR boxplot outlier rule</h3>
<p>A parameter-free outlier definition: a frame is an outlier when
its DVARS (or DVARS-ref) exceeds <code>Q3 + 1.5·IQR</code>, where Q3
is the 75th percentile and IQR is the inter-quartile range of the
per-run time series. Chosen over the more common 3σ rule because:</p>
<ul>
<li>It is parameter-free — no calibration against a group mean is
needed.</li>
<li>It is robust to non-Gaussian heavy-tailed cord DVARS at low TR.</li>
<li>It adapts to per-run scanner / sequence variability without a
group-mean calibration.</li>
</ul>
<p>The deviation from Kaptan 2023's 3σ rule is documented in
<code>.claude/specs/s3-algorithm-audit.md</code>.</p>
<p class="ref">Tukey JW, <i>Exploratory Data Analysis</i>, 1977.</p>
</div>

<div class="step">
<h3>Robust functional reference (funcref)</h3>
<p>The voxel-wise median of the non-outlier frames in a run (the
outlier mask comes from the Tukey rule above). Median over mean
because:</p>
<ul>
<li>One large-motion frame skews the mean toward the wrong voxel
intensity; the median is unaffected.</li>
<li>Cord EPI has heavy-tailed intensity distributions per voxel
across time, so the median is closer to the typical voxel intensity
than the mean.</li>
</ul>
<p>S3 emits this as <code>func_ref.nii.gz</code> (a.k.a. "funcref" /
"functional reference"). It is the registration target for S6 and
the per-run baseline for downstream tSNR maps.</p>
<p class="ref">Mohammed J et al., Magn Reson Med 2020 (cord moco).
SCT batch_processing.sh.</p>
</div>

<div class="step">
<h3>sct_deepseg seg_sc_contrast_agnostic</h3>
<p>The SCT 7.0+ default cord-segmentation tool. Replaces the older
contrast-specific <code>sct_deepseg_sc -c t2</code> / <code>-c
t2s</code>. Contrast-agnostic models work directly on EPI volumes
without a per-sequence calibration step, which makes them suitable
for the functional-reference cord localization in S3.1.</p>
<p>Open question for future versions: EPISeg (Valošek 2025) is a
new model tuned to EPI specifically. It is not yet packaged in SCT
batch_processing; we will switch when it ships.</p>
<p class="ref">De Leener B et al., NeuroImage 2017 (SCT).
Valošek J et al., 2025 (EPISeg).</p>
</div>

<div class="step">
<h3>Brain contamination check (internal: drift gate)</h3>
<p>A SpinalfMRIprep-specific QC guard. <code>sct_deepseg</code> can
drift into the brain stem on acquisitions where the top of the
imaging FOV clips through the brain. The "cord" segmentation then
bleeds upward and the downstream pipeline computes cord-fMRI
metrics on brain tissue.</p>
<p>Two checks on the most-superior 5 cord-bearing slices flag this:</p>
<ul>
<li><b>Absolute cap</b> — any slice with cord cross-sectional area
&gt; 200 mm² is rejected. Cervical cord CSA never exceeds ~80 mm²;
200 mm² leaves margin for swelling / pathology while catching brain
stem (CSA 500+ mm²).</li>
<li><b>Spike ratio</b> — the topmost cord slice's area divided by
the slice immediately inferior to it must be ≤ 4×. Brain stem is
6–10× larger than the cord, so 4× is sensitivity-favoring (catches
early drift).</li>
</ul>
<p>This is documented as a pipeline-specific innovation in
<code>.claude/specs/s3-algorithm-audit.md</code>; no published
cord-fMRI pipeline codifies an equivalent guard, but the failure
mode is acknowledged by SCT issue threads and CoSpine 2025's
per-acquisition QC caveat.</p>
</div>

<div class="step">
<h3>Frame-wise displacement (FD)</h3>
<p>Power 2014's volume-level motion summary: sum of absolute
frame-to-frame translations + rotations (rotations converted to
mm by multiplying by a 50 mm head-radius constant; for cord we
follow brain convention).</p>
<div class="formula">
FD(t) = |Δtx| + |Δty| + |Δtz| + 50·(|Δrx| + |Δry| + |Δrz|)
</div>
<p>Computed in S4 from the rigid-body parameters MCFLIRT estimates
per frame. The cord-fMRI FD threshold convention is Kaptan 2023:
runs with mean FD &gt; 0.5 mm are flagged.</p>
<p class="ref">Power JD et al., NeuroImage 2014. Kaptan M et al.,
NeuroImage 2023.</p>
</div>

<div class="step">
<h3>Cord-aware smoothing</h3>
<p>Spatial smoothing applied <i>along</i> the straightened cord
centerline rather than as an isotropic 3D Gaussian. Implemented by
SCT's <code>sct_smooth_spinalcord</code>: the cord is first
straightened (warped onto a vertical centerline), then smoothed in
PAM50 space, then warped back. This avoids the "smooth across the
cord boundary into CSF" problem that an isotropic Gaussian would
cause.</p>
<p>Applied in S9. We use this in preference to the X+Y in-plane
Gaussian that CoSpine applies during S3-stage smoothing because the
straightened-cord approach handles cervical cord curvature
correctly.</p>
<p class="ref">De Leener B et al., NeuroImage 2017 (SCT).
Eippert F et al., NeuroImage 2017 (cord-fMRI defaults).</p>
</div>

<div class="step">
<h3>PAM50 cord Dice</h3>
<p>The Sørensen–Dice coefficient between the subject's cord
segmentation and the PAM50 template cord, after registration. Used
as the step-local truth metric for S2 (anat→PAM50) and S7
(template normalisation).</p>
<div class="formula">
Dice(A, B) = 2 · |A ∩ B| / (|A| + |B|)
</div>
<p>Per-slice Dice (computed slice-by-slice along the cord and
plotted in a bar chart) is the diagnostic reportlet: a single
collapsed-into-zero slice points to exactly which Z had a
registration failure.</p>
<p class="ref">De Leener B et al., NeuroImage 2018 (PAM50).
Wei H et al., 2025 (CoSpine effectiveness reportlets).</p>
</div>

<div class="step">
<h3>RETROICOR / PNM physiological noise modelling</h3>
<p>Physiological noise (cardiac pulsation, respiration) is the
dominant nuisance in cord BOLD — much more so than in brain, because
the cord sits next to large arteries and the dura pulses with each
heartbeat. <b>RETROICOR</b> (Glover 2000) models the contribution as
a Fourier expansion of the cardiac and respiratory phase per slice.
<b>PNM</b> (FSL's PhysioNoiseModelling) is the implementation; it
emits per-slice regressors that S8 packs into the design matrix
alongside motion + DVARS-derived outliers.</p>
<p>Cord-specific extensions: additional CSF nuisance (which moves
with the respiratory cycle in the cord), per-slice timing offset
(slice-acquisition order matters for the phase calculation).</p>
<p class="ref">Glover GH et al., Magn Reson Med 2000 (RETROICOR).
Eippert F et al., NeuroImage 2017 (cord-fMRI defaults).
Kong Y et al., NeuroImage 2014.</p>
</div>

<div class="step">
<h3>MP-PCA thermal-noise reduction</h3>
<p><span class="pill deferred">deferred</span> Marchenko-Pastur PCA
(Veraart 2016) denoising — fits a random-matrix-theory model to the
noise eigenvalues of the local 4D patch and removes the
noise-only components. Kaptan 2023 applies it to raw EPI before any
other preprocessing for cord; fMRIPrep brain skips it.</p>
<p>We currently skip too. Adding it is a v2 candidate (pre-S3.1
hook). The expected gain is a 1.3–1.6× tSNR increase on cord EPI
without changing the BOLD signal of interest.</p>
<p class="ref">Veraart J et al., NeuroImage 2016. Kaptan M et al.,
NeuroImage 2023.</p>
</div>
"""


# ---------------------------------------------------------------------------
# Per-step sections
# ---------------------------------------------------------------------------


def _section_S1() -> str:
    return """
<h2 id="S1">S1 — Input verify</h2>
<div class="step">
<p>BIDS inventory + integrity checks before any algorithm runs.
For each functional run we verify: required anat references (T2
+ optional T2*), BOLD geometry (TR, TE, slice timing, voxel size),
sidecar JSON completeness, and that the dataset key matches the
policy YAML inventory. Failures here block the run from entering
S2+ — the runs in S1 FAIL are typically missing-anat or
malformed-BIDS cohorts that need upstream cleanup.</p>
<p>Reportlet: <code>dataset_summary</code> — per-dataset inventory
with PASS/WARN/FAIL counts and a check-by-check table.</p>
</div>
"""


def _section_S2() -> str:
    return """
<h2 id="S2">S2 — Anatomical &amp; cord reference</h2>
<div class="step">
<p>Builds the per-subject anatomical reference and cord
segmentation that downstream steps register against. Sub-steps:</p>
<ul>
<li><b>S2.1</b> — anat preprocessing (N4 bias, denoise) + cord
crop bbox.</li>
<li><b>S2.2</b> — cord segmentation via
<code>sct_deepseg spinalcord</code>; TotalSpineSeg for vertebrae,
discs, canal anatomy.</li>
<li><b>S2.3</b> — nerve rootlets segmentation (cord-specific
anatomical landmark for slice-to-vertebra correspondence).</li>
<li><b>S2.4</b> — PAM50 template registration (rigid →
affine → SyN).</li>
</ul>
<p><b>Step-local truth metric</b> (CLAUDE.md dev principle §3):
PAM50 cord Dice between the subject cord and the registered
PAM50 cord template — see <a href="#concepts">core concepts</a>.</p>
<p>Reportlets: <code>cordmask_montage</code> (cord seg overlay),
<code>totalspineseg_montage</code> (vertebrae + discs + canal
overlay), <code>rootlets_montage</code>, <code>pam50_reg_overlay</code>
(template alignment).</p>
<p class="ref">De Leener B et al., NeuroImage 2018 (PAM50).
Valošek J et al., 2023 (TotalSpineSeg). Cohen-Adad J et al., SCT 7.</p>
</div>
"""


def _section_S3() -> str:
    return """
<h2 id="S3">S3 — Functional initialisation &amp; crop</h2>
<div class="step">
<p>Prepares each BOLD run for downstream motion correction. Three
sub-steps:</p>
<ul>
<li><b>S3.1</b> — drop dummy frames (4 frames at TR ≈ 2 s; Eippert
2017 / Kaptan 2023 default), compute the <b>coarse functional
reference</b> (median over all dummy-dropped frames), segment the
cord on the coarse reference via <code>sct_deepseg
seg_sc_contrast_agnostic</code>, and apply the <b>brain-contamination
check</b> — see <a href="#concepts">core concepts</a>.</li>
<li><b>S3.2</b> — compute per-frame DVARS + DVARS-ref within the
cord mask, flag outliers via the Tukey 1.5·IQR rule, then build
the <b>robust functional reference</b> as the voxel-wise median
over non-outlier frames.</li>
<li><b>S3.3</b> — crop the 4D BOLD to a 60 mm cylinder around the
cord (CoSpine 2025 uses 35 mm; we are wider for more anatomical
context in S6 registration). The crop bbox is shown on the
sagittal reportlet with axial montage tiles centered on the cord.</li>
</ul>
<p><b>Step-local truth metric</b>: outlier fraction. Kaptan 2023
reports a typical 2% for healthy cord rest (range 0.6–5.6%); we
PASS at ≤20%, WARN at 20–40%, FAIL above. Conservative upper
end of "still usable".</p>
<p>Reportlets:</p>
<ul>
<li><code>func_localization</code> — cord segmentation on the
coarse functional reference (renamed from
<code>func_localization_crop</code> since S3.1 doesn't actually
crop; the crop happens in S3.3).</li>
<li><code>frame_metrics</code> — DVARS + DVARS-ref time series
with outlier markers and thresholds.</li>
<li><code>crop_box_sagittal</code> — the S3.3 crop bbox on the
sagittal reference + per-Z axial tiles.</li>
<li><code>funcref_montage</code> — robust funcref axial montage
for visual cord-signal sanity.</li>
</ul>
<p class="ref">Eippert F et al., NeuroImage 2017. Mohammed J et al.,
Magn Reson Med 2020. Kaptan M et al., NeuroImage 2023.
Audit: <code>.claude/specs/s3-algorithm-audit.md</code>.</p>
</div>
"""


def _section_S4() -> str:
    return """
<h2 id="S4">S4 — Functional motion correction</h2>
<div class="step">
<p>Per-frame rigid-body motion correction with MCFLIRT (FSL).
Registration target: the robust functional reference from S3.2.
Cord-fMRI works at lower TR than brain — typical TR 1.5–2.5 s —
so per-frame motion can be sizeable from cardiac pulsation alone.</p>
<p>S4 emits the moco BOLD plus six motion parameters per frame
(three translations + three rotations) which S8 packs into the
confound design matrix.</p>
<p><b>Step-local truth metric</b>: tSNR before/after — a working
moco improves tSNR (especially per-slice in the cord). A failed
moco can lower it (over-fitting / wrong reference).</p>
<p>Reportlets:</p>
<ul>
<li><code>S4_motion_traces</code> — 6-parameter rigid-body time
series with FD overlay.</li>
<li><code>S4_dvars_plot</code> — DVARS time series after moco.</li>
<li><code>S4_tsnr_comparison</code> — before/after tSNR montage,
the headline moco-quality reportlet.</li>
</ul>
<p class="ref">Jenkinson M et al., NeuroImage 2002 (MCFLIRT).
Kaptan M et al., NeuroImage 2023 (cord FD threshold).</p>
</div>
"""


def _section_S5() -> str:
    return """
<h2 id="S5">S5 — Functional distortion correction</h2>
<div class="step">
<p>EPI suffers susceptibility-induced distortions in the
phase-encode direction. In cord this manifests as A–P (anterior-
posterior) compression / expansion of the cord cross-section at
vertebral-disc and lung-tissue interfaces. We follow the fMRIPrep
hierarchy: <b>topup</b> &gt; <b>fugue</b> &gt; <b>SyN fallback</b>
depending on which fieldmap data is available.</p>
<p><b>Step-local truth metric</b> (Wei 2025 / CoSpine v2): per-slice
A–P cord-centerline displacement between EPI and anat, and
per-slice 2D cord Dice between EPI cord seg and anat cord seg
resampled into EPI space.</p>
<p>Reportlets:</p>
<ul>
<li><code>slice_displacement</code> — A–P displacement bars per
slice (CoSpine convention).</li>
<li><code>cord_dice_per_slice</code> — 2D cord Dice per slice
(EPI ∩ anat).</li>
</ul>
<p class="ref">Andersson JLR et al., NeuroImage 2003 (topup).
Jenkinson M et al., 2001 (FUGUE). Wei H et al., 2025 (CoSpine v2).</p>
</div>
"""


def _section_S6() -> str:
    return """
<h2 id="S6">S6 — Functional → anatomical registration</h2>
<div class="step">
<p>Rigid + small non-linear registration of the EPI funcref to the
subject's T2 anat space. Uses <code>sct_register_multimodal</code>
with cord-seg-driven cost so the registration is driven by the
cord intensity rather than the noisy background. The recipe is the
S6 spec's recommended cord-fMRI default.</p>
<p><b>Step-local truth metric</b>: per-slice cord Dice in anat
space after the BOLD is warped over. A working registration gives
&gt; 0.7 Dice across the cord-bearing slices; a slice that
collapses to near-zero is exactly where the registration broke.</p>
<p>Reportlets:</p>
<ul>
<li><code>bold_on_anat_axial</code> — axial overlay of BOLD on
anat with cord seg contour.</li>
<li><code>bold_on_anat_sagittal</code> — mid-sagittal overlay.</li>
<li><code>cord_dice_per_slice</code> — per-slice Dice bar chart.</li>
</ul>
<p class="ref">De Leener B et al., NeuroImage 2017 (SCT).</p>
</div>
"""


def _section_S7() -> str:
    return """
<h2 id="S7">S7 — Template normalisation</h2>
<div class="step">
<p>Warp the per-subject anat (with the registered BOLD chain
piggy-backing along) into PAM50 template space. The warp is
already computed in S2.4; S7 applies it to the BOLD-space
artefacts and verifies the result.</p>
<p><b>Step-local truth metric</b>: PAM50 vertebral-level alignment
— the subject's vertebrae centroids vs the template vertebrae
centroids per level (C2 through T1).</p>
<p>Reportlets:</p>
<ul>
<li><code>pam50_overlay_sagittal</code> — funcref + PAM50 cord
contour, mid-sagittal.</li>
<li><code>pam50_overlay_axial</code> — funcref + PAM50 cord
contour, axial montage.</li>
<li><code>vertebral_alignment</code> — per-level alignment
chart.</li>
</ul>
<p class="ref">De Leener B et al., NeuroImage 2018 (PAM50).</p>
</div>
"""


def _section_S8() -> str:
    return """
<h2 id="S8">S8 — Confounds &amp; physio regressors</h2>
<div class="step">
<p>Pack the design matrix for downstream GLMs. Columns:</p>
<ul>
<li><b>Motion</b> — six rigid params + their first derivatives
(Friston 24) from S4.</li>
<li><b>Outliers</b> — one-hot columns for frames flagged by DVARS
or DVARS-ref above their thresholds in S3.2 (also re-thresholded
here with the policy's <code>refrms_outlier_n_sd</code>).</li>
<li><b>FD</b> — frame-wise displacement from S4 motion params.</li>
<li><b>CSF</b> — CSF voxel signal averaged per slice (cord-
specific aCompCor-like regressor; uses the CSF mask carved out
of the S2 cord crop).</li>
<li><b>RETROICOR / PNM</b> — Fourier expansion of cardiac +
respiratory phase per slice — see
<a href="#concepts">core concepts</a>.</li>
</ul>
<p>Reportlets:</p>
<ul>
<li><code>confound_columns</code> — column counts per family.</li>
<li><code>fd_dvars_outliers</code> — FD / DVARS / DVARS-ref with
outlier highlights.</li>
<li><code>carpet_plot</code> — cord BOLD carpet with FD / DVARS rails.</li>
<li><code>pnm_peaks</code> — FSL PNM cardiac / respiratory peak
detection.</li>
<li><code>correlation_heatmap</code> — confound correlation
matrix.</li>
</ul>
<p class="ref">Friston KJ et al., Magn Reson Med 1996 (24-param).
Glover GH et al., Magn Reson Med 2000 (RETROICOR).
Behzadi Y et al., NeuroImage 2007 (CompCor).</p>
</div>
"""


def _section_S9() -> str:
    return """
<h2 id="S9">S9 — Primary functional derivatives</h2>
<div class="step">
<p>The output products downstream analyses depend on: tSNR maps
per voxel, cord-aware smoothed BOLD, requested-vs-measured FWHM
diagnostics. Smoothing uses <code>sct_smooth_spinalcord</code> —
see <a href="#concepts">core concepts</a>.</p>
<p><b>Step-local truth metric</b>: tSNR per vertebral level. A
working chain produces tSNR &gt; 15–20 per voxel in cervical cord
(Kaptan 2023 typical); per-level breakdown surfaces if a single
slice has a coil dropout.</p>
<p>Reportlets:</p>
<ul>
<li><code>tsnr_map_axial</code> — native tSNR map montage.</li>
<li><code>tsnr_per_level</code> — per-vertebral-level tSNR
bars.</li>
<li><code>smoothness_summary</code> — requested vs measured
FWHM.</li>
</ul>
<p class="ref">Kaptan M et al., NeuroImage 2023.
Eippert F et al., NeuroImage 2017.</p>
</div>
"""


def _section_S11() -> str:
    return """
<h2 id="S11">S11 — QC aggregation &amp; release</h2>
<div class="step">
<p>The cohort-level release report. Aggregates per-step QC across
all subjects + sessions, emits the methods-paper-ready summary
(coverage matrix, per-step pass fractions, runtime estimates),
and ships the reproducibility receipt (policy SHA + git SHA +
tool versions).</p>
<p>S11 is a release deliverable, not an engineering tool
(CLAUDE.md dev principle §8): we run it twice in the project life
— mid-pipeline sanity check and final methods table. Never to
decide between algorithms.</p>
</div>
"""
