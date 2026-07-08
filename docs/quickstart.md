# Run it on your data

SpinalfMRIprep is a standard **BIDS-App**: it takes a BIDS dataset and produces
GLM-ready, BIDS-Derivatives outputs plus QC reports.

```
spinalfmriprep <bids_dir> <output_dir> {participant,group} [options]
```

- **participant** — per-subject preprocessing (S1–S9), writing derivatives + QC.
- **group** — cross-subject QC aggregation + release reports (S10).

## What it's validated on (supported envelope)

SpinalfMRIprep is validated on **cervical spinal-cord EPI-BOLD at 3 T**. It will
still *run* outside that envelope, but the pipeline warns you and you should treat
results with care for: non-3 T data, non-EPI sequences, or fields of view outside
the cervical cord (thoracic/lumbar-only or whole-brain). The QC report shows the
vertebral levels actually covered.

## Build the image

SpinalfMRIprep is distributed as a **build recipe**, not a prebuilt image,
because the container installs FSL — whose binaries are licensed for
non-commercial use and are not freely redistributable. You build the image
locally (and thereby accept FSL's licence yourself):

```bash
git clone https://github.com/SpinalfMRIprep/SpinalfMRIprep.git
cd SpinalfMRIprep
docker build -f Dockerfile.spinalfmriprep \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  --build-arg GIT_DESCRIBE=$(git describe --always --tags) \
  -t spinalfmriprep:1.0.0 .
```

The `--build-arg` values stamp the pipeline version into the reproducibility
receipt. The build pulls SCT + FSL and takes tens of minutes.

## Run with Apptainer (HPC — no Docker needed)

```bash
# Convert your locally-built Docker image to a .sif:
apptainer build spinalfmriprep.sif docker-daemon://spinalfmriprep:1.0.0

apptainer run --cleanenv --writable-tmpfs --pwd /app \
  --bind /path/to/bids:/bids:ro --bind /path/to/out:/out \
  spinalfmriprep.sif /bids /out participant --participant-label 01
# then the group level:
apptainer run --cleanenv --writable-tmpfs --pwd /app \
  --bind /path/to/bids:/bids:ro --bind /path/to/out:/out \
  spinalfmriprep.sif /bids /out group
```

`--writable-tmpfs` and `--pwd /app` are required: SCT tools write temporary files
to the working directory, and the pipeline resolves its policy/config there.

## Run with Docker

```bash
docker run --rm \
  -v /path/to/bids:/bids:ro -v /path/to/out:/out \
  spinalfmriprep:1.0.0 /bids /out participant --participant-label 01
docker run --rm -v /path/to/bids:/bids:ro -v /path/to/out:/out \
  spinalfmriprep:1.0.0 /bids /out group
```

Tip: pass `--user $(id -u):$(id -g)` so outputs are owned by you, not root.

## Useful options

- `--participant-label 01 07 12` — process only these subjects (default: all).
- `--batch-workers N` — per-step parallelism across subjects/runs.
- `--smoothing-sigma-mm RL AP SI` — override the S9 cord-smoothing kernel (mm)
  without editing policy YAML (default from policy).
- `--skip-bids-validator` — bypass the built-in input checks (at your own risk).

## Resources & runtime

- **Disk:** the image is ~17 GB; budget a few GB of outputs per subject.
- **Memory:** ~8–16 GB RAM is comfortable for one subject at a time.
- **GPU (optional):** SCT's deep-learning segmentation uses the GPU when available
  (`SCT_USE_GPU=1` + a CUDA-enabled torch); CPU works but is slower.
- **Runtime:** roughly tens of minutes per functional run on CPU (motion
  correction, distortion correction, registration, smoothing).

## Read the results

```bash
# group-level overview + cross-dataset release report:
open <output_dir>/derivatives/spinalfmriprep/release_report.html
# per-subject QC reports:
open <output_dir>/derivatives/spinalfmriprep/*/sub-*/sub-*_qc_report.html
```

Each run also produces the GLM-ready `desc-preproc_bold`, a
`desc-confounds_timeseries.tsv`, PAM50-space masks + the spinal-level atlas,
per-level tSNR, and the bold↔PAM50 transforms. A machine-readable
`spinalfmriprep_run_manifest.json` records per-step pass/fail/skip counts and the
exit code, and a `reproducibility_receipt.json` records tool versions + policy
hashes + the pipeline version.

## Troubleshooting

- **"input validation FAILED"** — the front-door check found a real problem
  (no subjects, an unknown `--participant-label`, a subject missing func or anat,
  or an empty/corrupt NIfTI). Fix the listed issue, or `--skip-bids-validator` to
  bypass.
- **A subject fails a step** — it is skipped-and-reported; other subjects continue.
  Open that subject's QC report for the per-run reason (e.g. "distortion-limited,
  no fieldmap" or "high censored fraction"). The run manifest lists what was
  attrited.
- **The whole run stops** — either the step crashed, or *all* runs failed QC at
  that step (nothing left downstream). The message says which.
