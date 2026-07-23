"""Build the preprocessing lock manifest.

Captures the exact state being frozen: code SHA, per-step policy hashes, tool
versions, per-step QC tallies, the attrition waterfall, and reportlet counts.
Anything that drifts later is detectable by re-running this and diffing.
"""
import json, glob, os, hashlib, subprocess, collections

REPO = "/mnt/ssd1/SpinePrep"
COH = "/mnt/ssd1/spineprep_cohort_s2"

def sh(*a):
    return subprocess.run(a, cwd=REPO, capture_output=True, text=True).stdout.strip()

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

STEPS = ["S1_input_verify", "S2_anat_cordref", "S3_func_init_and_crop",
         "S4_func_motion_correction", "S5_func_distortion_correction",
         "S6_func_to_anat_registration", "S7_template_normalization",
         "S8_confounds_and_physio_regressors", "S9_primary_functional_derivatives",
         "S10_qc_aggregation_and_release"]

lock = {
    "locked_utc": None,          # stamped by caller
    "git": {
        "sha": sh("git", "rev-parse", "HEAD"),
        "describe": sh("git", "describe", "--always", "--dirty"),
        "clean": sh("git", "status", "--porcelain") == "",
    },
    "cohort_root": COH,
    "policy_sha256": {},
    "steps": {},
    "reportlets": {},
}

for p in sorted(glob.glob(f"{REPO}/policy/*.yaml")):
    lock["policy_sha256"][os.path.basename(p)] = sha256(p)

for s in STEPS:
    files = glob.glob(f"{COH}/logs/{s}/*/qc.json") or glob.glob(f"{COH}/logs/{s}/qc.json")
    c = collections.Counter(); n = 0; ds = 0
    for f in files:
        ds += 1
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for r in d.get("runs", []):
            c[r.get("status")] += 1; n += 1
    lock["steps"][s] = {"datasets": ds, "runs": n,
                        "PASS": c["PASS"], "WARN": c["WARN"], "FAIL": c["FAIL"]}

# reportlet PNG counts per step prefix, as shipped
for s in STEPS:
    tag = s.split("_")[0]
    lock["reportlets"][tag] = len(glob.glob(f"{COH}/derivatives/**/*desc-{tag}_*.png", recursive=True))

# tool versions from the receipt (authoritative, emitted by S10)
rec = json.load(open(f"{COH}/derivatives/spineprep/reproducibility_receipt.json"))
lock["tools"] = {k: rec.get(k) for k in
                 ("sct_version", "fsl_version", "ants_version", "mrtrix_version",
                  "python_version", "os")}
lock["tools"]["packages"] = rec.get("package_versions")
lock["receipt_git_sha"] = rec.get("pipeline_git_sha")

print(json.dumps(lock, indent=2))
