#!/usr/bin/env python3
"""One-off ETL: prepare OpenNeuro ds004926 (Leipzig dorsal-horn thermal pain)
for the v1_validation cohort under "option 1" (te40-only + physio integrated).

Why this is needed
------------------
ds004926 is a MULTI-ECHO acquisition (acq-te25..te55) but the source paper only
analyses ``acq-te40ReliabilityRun`` (160 vols/run, 40 subj x 2 days = 80 runs).
Processing all seven echoes is 4x redundant compute for no validation value, so
we restrict to te40. Its physiological recordings are real and usable (ECG +
respiratory at 1000 Hz, used for RETROICOR in the paper) but ship in a
NON-STANDARD form under ``derivatives/<sub>/<ses>/physio/``:
  - the .tsv has a HEADER row (BIDS physio is headerless), cols: ecg resp Rpeak TR stim
  - the .json declares ``SamplingFrequency`` as a string ("1000 Hz.") and a
    ``Columns`` dict in the wrong order
so SCT/our S8 parser safely rejects it (no garbage). This script transforms it
into a BIDS ``_physio.tsv.gz`` + ``.json`` our S8 RETROICOR consumes:
  cardiac <- ecg, respiratory <- resp, trigger <- TR; SamplingFrequency 1000 (num).

What it does (idempotent-ish; run once)
---------------------------------------
1. Move all non-te40 func files out of the BIDS tree to
   ``datasets/.excluded_ds004926_echoes/`` (reversible) so S1 inventories te40 only.
2. ``aws s3 sync`` the te40 physio .tsv from the dataset's derivatives/ on the
   OpenNeuro S3 mirror.
3. Transform each into ``func/<run_id>_physio.tsv.gz`` + ``.json``.

Then policy/datasets.yaml sets ds004926 ``has_physio: true``. Verified: S1 PASS,
80 te40 runs, 80 physio runs; S8 parser reads 1000 Hz with 160 trigger pulses.

To reverse the te40 restriction: move files back from .excluded_ds004926_echoes/.
"""
from __future__ import annotations
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys

DATASET = "datasets/openneuro_ds004926_dorsalhorn_pain"
HOLD = "datasets/.excluded_ds004926_echoes"
S3 = "s3://openneuro.org/ds004926/derivatives/"
KEEP = "acq-te40ReliabilityRun"


def restrict_to_te40() -> int:
    os.makedirs(HOLD, exist_ok=True)
    moved = 0
    for f in glob.glob(f"{DATASET}/**/func/*", recursive=True):
        if KEEP in os.path.basename(f):
            continue
        rel = os.path.relpath(f, DATASET)
        dst = os.path.join(HOLD, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(f, dst)
        moved += 1
    return moved


def fetch_physio(tmp="/tmp/ds004926_physio") -> str:
    os.makedirs(tmp, exist_ok=True)
    subprocess.run(["aws", "s3", "sync", "--no-sign-request", S3, tmp,
                    "--exclude", "*", "--include", f"*{KEEP}*_physio.tsv",
                    "--only-show-errors"], check=True)
    return tmp


def transform_one(src_tsv: str, out_tsv_gz: str, out_json: str) -> int:
    """source cols: ecg resp Rpeak TR stim -> keep ecg(cardiac) resp(respiratory) TR(trigger)."""
    with open(src_tsv) as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {n: header.index(n) for n in ("ecg", "resp", "TR")}
        rows = 0
        with gzip.open(out_tsv_gz, "wt") as g:
            for line in f:
                c = line.rstrip("\n").split("\t")
                g.write(f"{c[idx['ecg']]}\t{c[idx['resp']]}\t{c[idx['TR']]}\n")
                rows += 1
    json.dump({"Columns": ["cardiac", "respiratory", "trigger"],
               "SamplingFrequency": 1000, "StartTime": 0.0,
               "cardiac": {"Description": "Preprocessed ECG trace (source col 'ecg')"},
               "respiratory": {"Description": "Raw respiratory belt (source col 'resp')"},
               "trigger": {"Description": "MRI volume acquisition pulses (source col 'TR')"}},
              open(out_json, "w"), indent=2)
    return rows


def place_all(tmp: str) -> tuple[int, int]:
    ok = miss = 0
    for src in glob.glob(f"{tmp}/**/*_physio.tsv", recursive=True):
        run_id = os.path.basename(src).replace("_physio.tsv", "")
        sub = re.search(r"sub-\d+", run_id).group(0)
        ses = re.search(r"ses-\d+", run_id).group(0)
        func_dir = f"{DATASET}/{sub}/{ses}/func"
        if not os.path.exists(f"{func_dir}/{run_id}_bold.nii.gz"):
            miss += 1
            continue
        transform_one(src, f"{func_dir}/{run_id}_physio.tsv.gz",
                      f"{func_dir}/{run_id}_physio.json")
        ok += 1
    return ok, miss


def main() -> int:
    moved = restrict_to_te40()
    print(f"restrict: moved {moved} non-te40 func files to {HOLD}")
    tmp = fetch_physio()
    ok, miss = place_all(tmp)
    print(f"physio: placed {ok}, skipped {miss} (no matching te40 bold)")
    print("Remember: set has_physio: true for ds004926 in policy/datasets.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
