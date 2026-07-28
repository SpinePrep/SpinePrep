#!/usr/bin/env python3
"""Resolve and download the hemodynamics reading list.

Metadata comes from Europe PMC (PMID, PMCID, DOI, journal, year). PDFs are pulled
only where the article is genuinely open access; everything else is recorded with its
identifiers so it can be requested through the library. Nothing is scraped from behind
a paywall.

Re-runnable: existing PDFs are skipped, and the manifest is rewritten each time.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PDF = HERE / "papers"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# (short name, exact-ish title to resolve). Grouped by what they contribute.
WANTED = [
    # --- spinal cord: hemodynamics, perfusion, vasculature
    ("hemmerling_2025_scvr_hemodynamics",
     "MRI mapping of hemodynamics in the human spinal cord"),
    ("duhamel_2008_cord_asl_blood_flow",
     "Spinal cord blood flow measurement by arterial spin labeling"),
    ("levy_2020_cord_ivim_7T_perfusion",
     "Intravoxel incoherent motion at 7 Tesla to quantify human spinal cord perfusion"),
    ("hemmerling_2026_spinalcompcor_denoising",
     "Data-driven denoising in spinal cord fMRI with principal component analysis"),
    ("horn_2025_7T_layer_specific_dorsalhorn",
     "Ultra-high-field fMRI reveals layer-specific responses in the human spinal cord"),
    ("hong_2008_cord_angiosome_territories",
     "Neurovascular anatomy of the spinal cord angiosome"),
    # --- brain: CVR amplitude AND lag, the method being transferred
    ("bright_murphy_2013_petco2_reliable_cvr",
     "Reliable quantification of BOLD fMRI cerebrovascular reactivity despite poor breath-hold performance"),
    ("moia_2021_multiecho_cvr_lag",
     "ICA-based denoising strategies in breath-hold induced cerebrovascular reactivity mapping with multi-echo BOLD fMRI"),
    ("moia_2020_voxelwise_lag_optimization",
     "Voxelwise optimization of hemodynamic lags to improve regional CVR estimates in breath-hold fMRI"),
    ("stickland_2021_restingstate_cvr_amplitude_lag",
     "A practical modification to a resting state fMRI protocol for improved characterization of cerebrovascular function"),
    ("vanniftrik_2016_breathhold_cvr_models",
     "Iterative analysis of cerebrovascular reactivity dynamic response by temporal decomposition"),
    # --- brain: hemodynamic lag from resting state alone, no gas challenge
    ("frederick_2012_riptide",
     "Physiological denoising of BOLD fMRI data using Regressor Interpolation at Progressive Time Delays"),
    ("erdogan_2016_blood_arrival_time",
     "Correcting for Blood Arrival Time in Global Mean Regression Enhances Functional Connectivity Analysis of Resting State fMRI-BOLD Signals"),
    ("tachibana_2022_slfo_vs_neuronal",
     "Separating neuronal activity and systemic low-frequency oscillation related BOLD responses at nodes of the default mode network"),
    ("hocke_2016_nirs_lfo_denoising",
     "Comparison of peripheral near-infrared spectroscopy low-frequency oscillations to other denoising methods in resting state functional MRI"),
    # --- HRF variability as a confound, and HRF estimation
    ("rangaprakash_2018_hrf_confounds_fc",
     "Hemodynamic response function HRF variability confounds resting-state fMRI functional connectivity"),
    ("rangaprakash_2023_hrf_confound_review",
     "The confound of hemodynamic response function variability in human resting-state functional MRI studies"),
    ("rangaprakash_2023_hrf_rat_cord_electrophysiology",
     "Comparison of hemodynamic response functions obtained from resting-state functional MRI and invasive electrophysiological recordings"),
]


def sh(cmd, timeout=90):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def resolve(title):
    q = title.replace('"', "")
    url = (f'{EPMC}?query=TITLE%3A%22{q.replace(" ", "%20")}%22'
           f"&format=json&pageSize=3&resultType=core")
    r = sh(["curl", "-s", "--max-time", "40", url])
    if not r or not r.stdout:
        return None
    try:
        res = json.loads(r.stdout).get("resultList", {}).get("result", [])
    except Exception:
        return None
    return res[0] if res else None


def try_pdf(rec, out: Path):
    """Only OA routes. Returns the URL that worked, or None."""
    pmcid = rec.get("pmcid")
    if not pmcid:
        return None
    oa = str(rec.get("isOpenAccess", "")).upper() == "Y" or \
        str(rec.get("inEPMC", "")).upper() == "Y"
    if not oa:
        return None
    for url in (f"https://europepmc.org/api/fulltextRepo?pprId={pmcid}&type=FILE&fileName=EMS.pdf",
                f"https://europepmc.org/articles/{pmcid}?pdf=render",
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"):
        r = sh(["curl", "-sL", "--max-time", "90", "-A",
                "Mozilla/5.0 (research literature collection)", "-o", str(out), url])
        if out.exists() and out.stat().st_size > 40000:
            with open(out, "rb") as fh:
                if fh.read(4) == b"%PDF":
                    return url
        if out.exists():
            out.unlink()
        time.sleep(1)
    return None


def main():
    PDF.mkdir(parents=True, exist_ok=True)
    manifest = []
    for short, title in WANTED:
        out = PDF / f"{short}.pdf"
        have = out.exists() and out.stat().st_size > 10000
        rec = resolve(title)
        entry = dict(short=short, query_title=title, pdf=have)
        if rec:
            entry.update(
                title=rec.get("title", "").rstrip("."),
                authors=rec.get("authorString", ""),
                journal=rec.get("journalTitle", ""),
                year=rec.get("pubYear", ""),
                pmid=rec.get("pmid", ""), pmcid=rec.get("pmcid", ""),
                doi=rec.get("doi", ""),
                open_access=str(rec.get("isOpenAccess", "")),
            )
            if not have:
                got = try_pdf(rec, out)
                entry["pdf"] = bool(got)
                entry["pdf_source"] = got or ""
        else:
            entry["resolve_failed"] = True
        manifest.append(entry)
        state = "PDF" if entry.get("pdf") else ("meta" if rec else "FAILED")
        print(f"  [{state:6}] {short:44} {entry.get('journal','')} {entry.get('year','')}",
              flush=True)
        time.sleep(1)
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    n_pdf = sum(1 for m in manifest if m.get("pdf"))
    print(f"\n{n_pdf}/{len(manifest)} PDFs on disk; metadata for "
          f"{sum(1 for m in manifest if not m.get('resolve_failed'))}")


if __name__ == "__main__":
    main()
