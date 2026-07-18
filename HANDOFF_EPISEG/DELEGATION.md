# Delegation → p2-spineprep: reliable cord discovery on EPI (use EPISeg / `sc_epi`)

**From:** p1-cospi-gvs session (data dir `/mnt/hdd2/P1_CoSpiGVS`, read-only consumer of SpinePrep output)
**To:** p2-spineprep session (pipeline repo `/mnt/ssd1/SpinePrep`)
**Date:** 2026-07-13
**Owner after handoff:** p2-spineprep (you). Continue the toolbox work here.

---

## 1. The ask, in one line

Make the **S3 cord discovery/crop** use the EPI-specific segmentation model
(**EPISeg = `sct_deepseg sc_epi`**, already installed in SCT 7.1) instead of the
contrast-agnostic `sct_deepseg spinalcord`, so the **whole cord** — not just the
upper half — is found on the functional (BOLD EPI) reference. Then reprocess and
verify.

## 2. What's wrong (symptom → root cause, both verified)

- **Symptom:** on the GVS dataset, the S3.1 "discovery cord" mask covers only the
  **upper ~half** of the imaged cervical cord. Worst case sub-AS002 run-01: mask =
  17 axial slices (~75 mm), stops at the mid-cervical curve. The crop follows the
  mask, so downstream derivatives lose the lower cord.
- **Verified it is NOT** a display bug, a cache issue, or an acquisition limit. I
  pulled every axial slice below the mask: a clear, compact spinal canal/cord
  continues ~12 slices (~50 mm) further, curving anteriorly, completely unmasked.
  See `proof_AS002_run01_axials_below_mask.png`.
- **Root cause:** `sct_deepseg spinalcord` (contrast-agnostic model) is trained
  mostly on high-res anatomical scans. On BOLD EPI (low res, distortion, dropout,
  ghosting) it locks onto the cord where it is brightest (upper cervical, big CSF
  pool) and gives up where contrast flattens and the cord curves forward. This is
  a documented limitation of the general models on EPI.
- The earlier mitigation in this repo — `_caudal_union` (propseg) + `_caudal_trace`
  (intensity trace) in `steps/s3/localize.py` — extrapolates the centreline
  **straight down**, so it also walks off the forward-curving cord and stops at
  roughly the same place. It is a patch on the wrong model.

## 3. The fix (already partly in this repo)

Use **EPISeg**, a model trained specifically on gradient-echo BOLD EPI (406
subjects, 15 sites, nnU-Net 3D). Best-in-class on EPI: Dice **0.87** vs 0.83
(contrast-agnostic), 0.77 (deepseg), 0.56 (propseg). Shipped in SCT ≥7.0 as
`sct_deepseg sc_epi`. **It is already installed here (SCT 7.1) and this repo
already calls it at S5–S9** (see `steps/s5..s9/orchestrate.py` →
`bold_after_cord_seg.nii.gz — sct_deepseg sc_epi`).

**The inconsistency to fix:** only **S3 discovery/crop** still uses the weak
`spinalcord` model — so S3 crops the cord short *before* the good `sc_epi` model
ever runs downstream. Align S3 with the rest of the pipeline.

### Proof on the exact failing image
`sct_deepseg sc_epi` on AS002 run-01 func ref: **17 slices → 56 slices**, follows
the cord through the anterior curve to the bottom of the FOV. Side-by-side:
`proof_AS002_run01_current_vs_epiSeg.png`. Seg output: `AS002_run01_sc_epi_seg.nii.gz`.
~40 s on CPU per run.

## 4. Exact code to change (`/mnt/ssd1/SpinePrep`)

All in `src/spineprep/steps/s3/`:

1. **`localize.py:742`** — the discovery-seg subprocess is hard-coded:
   ```python
   "sct_deepseg", "spinalcord",
   ```
   Change the task to `sc_epi` (and update the output-path handling / expected
   filename if the CLI writes `*_bold_seg.nii.gz`). Confirm the `-o` / output
   parsing still resolves `func_ref_fast_seg.nii.gz`.

2. **`session.py:339`** — the config that names the task:
   ```python
   "func_localization": {"enabled": True, "method": "deepseg", "task": "spinalcord"},
   ```
   Change `"task": "spinalcord"` → `"task": "sc_epi"`. Prefer driving the CLI from
   this config rather than the hard-coded string in `localize.py`, so there is one
   source of truth.

3. **Input to the model — use a higher-SNR reference.** EPISeg expects a
   motion-corrected **temporal mean**, not a single coarse frame. S3 currently
   segments `init/func_ref_fast.nii.gz` (coarse fast ref). Check whether a
   mean-of-MOCO functional is available at S3 time; if so, feed that to `sc_epi`.
   If only the fast ref exists, `sc_epi` still works far better than `spinalcord`
   (proven above), but the mean is the recommended input.

4. **Add largest-connected-component cleanup** after `sc_epi`. When the FOV
   includes brain (e.g. AS002), EPISeg emits a few stray specks up in the brain.
   The cord is one long connected object — keep the largest 3D component (or the
   component overlapping the image-centre column) and drop the rest.

5. **Remove / disable the straight-line caudal patches** once `sc_epi` is in:
   `_caudal_union` (localize.py:155, called ~544) and `_caudal_trace`
   (localize.py:298, called ~475). They were compensating for the weak model and
   now do nothing useful (EPISeg already follows the curve); leaving them risks
   re-introducing off-axis leakage. Delete or gate behind a flag.

## 5. Reliable recipe (the general method, any EPI image)

1. Motion-correct the 4D run; take the **temporal mean** (SNR ↑).
2. `sct_deepseg sc_epi -i mean.nii.gz -o cord.nii.gz`.
3. **Keep the largest connected component** (removes brain/vessel specks).
4. QC: check the centreline is continuous top-to-bottom; morphological-close
   1–2 slice gaps. Fallback centreline detector for pathological images:
   `sct_get_centerline -method optic`.

## 6. Validation (definition of done)

- Re-run S3 (localization + crop) for **all 43 GVS runs**
  (`/mnt/hdd2/P1_CoSpiGVS` BIDS; 11 subjects, MC001 has 3 runs).
- Re-render the S3 `func_localization` reportlets and confirm the discovery cord
  spans the full imaged cord on the sagittal for every run — spot-check the known
  bad ones: **AS002 (all), CO001 (all), LK001 (all), MC001 (all)**.
- Confirm the crop box now contains the full cord (no caudal truncation).
- Re-run downstream (S4→S9) so derivatives inherit the fuller cord; watch WY001
  run-03, which previously attrited on downstream QC after a fuller crop.
- Regenerate the QC dashboard (`qc_dashboard.py`) and confirm figures update
  (image `?v=` is keyed to figure mtime).

## 7. Constraints (must respect — repo is mid-release-migration)

- **Do NOT** touch, stage, revert, or commit release-prep files: NOTICE, README,
  RELEASE, docs, pyproject, .github, CHANGELOG. Stage only your own changed code
  files **by explicit path**. **Never `git add -A`.**
- This `HANDOFF_EPISEG/` folder is a working note — **do not commit it**.
- Plain language in all reportlet text / logs / commit messages; no emojis.
- The GVS data is restricted human clinical data — keep it on-machine.
- Commit trailer must credit Claude + Happy (see repo CLAUDE.md).

## 8. Open decisions for you (p2)

- Config-drive the task (recommended) vs. hard-code — pick one and make it single-source.
- Where to compute the mean-MOCO input at S3, or accept the fast ref.
- Whether to keep `_caudal_*` as a disabled fallback or delete outright.
- Whether to bump the S3 reportlet to crop the sagittal to the cord extent (a
  separate presentation nicety I flagged; optional, not required for this fix).

## 9. Artifacts in this folder

- `proof_AS002_run01_current_vs_epiSeg.png` — current 17-slice mask vs `sc_epi` full cord.
- `proof_AS002_run01_axials_below_mask.png` — axial slices below the mask showing unmasked cord.
- `AS002_run01_sc_epi_seg.nii.gz` — the `sc_epi` segmentation (in `func_ref_fast` geometry).

## 10. References

- EPISeg — Imaging Neuroscience (MIT Press): https://direct.mit.edu/imag/article/doi/10.1162/IMAG.a.98/131869
- EPISeg — PMC full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12421696/
- SCT `sct_deepseg` docs: https://spinalcordtoolbox.com/stable/user_section/command-line/sct_deepseg.html
- Contrast-agnostic seg (Bédard et al.): https://www.sciencedirect.com/science/article/pii/S1361841525000210
