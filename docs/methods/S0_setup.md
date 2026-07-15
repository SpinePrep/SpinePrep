---
search:
  boost: 2
---

# S0: Setup

S0 verifies the dataset policy and the processing environment before any data is
read. It writes a QC record and an environment fingerprint, and fails the run if a
prerequisite is missing. No imaging data is touched and no derivatives are
produced.

## What it does

S0 runs two groups of checks. The dataset policy gate validates
`policy/datasets.yaml`. The environment checks confirm that a container runtime is
available, that the required container images are present and runnable, and that
the PAM50 template data can be found. A single failed check fails the step: S0
reports either PASS or FAIL, and the failure message names the first check that
failed. There is no warning state.

## Dataset policy gate

`policy/datasets.yaml` is loaded and validated against the v1 gate, which requires
the mandatory fields, unique dataset keys, valid selection constraints, and
boolean specification flags. A schema violation fails the step and is reported
with the offending field.

## Container runtime and images

A container runtime is located by searching for `docker`, then `apptainer`. If
neither is present the runtime check fails.

Image verification is implemented for docker only. On a host whose runtime is
apptainer, the `container_images` check fails with the message "Image checks
require docker; apptainer path not implemented". Apptainer is therefore usable to
run the pipeline itself but not to satisfy S0's image verification.

Four images are checked. Each is inspected with `docker image inspect` to confirm
it is present locally and to record its repository digest, and a version command
is then executed inside it with `docker run --rm`:

`SPINEPREP_IMAGE` (environment variable, no default): verified with `spineprep --version` and `python --version`.
`vnmd/spinalcordtoolbox_7.2:20251215`: verified with `sct_version`.
`vnmd/fsl_6.0.7.18_20250928`: verified with `fslversion`.
`vnmd/ants_2.6.0_20250424`: verified with `antsRegistration --version`.

## PAM50 template

The PAM50 template directory (De Leener et al., 2018) is searched in order: the
`PAM50_PATH` environment variable, then `$SCT_DIR/data/PAM50`, then
`~/sct_7.1/data/PAM50`. The first existing path is recorded in the environment
fingerprint. If none exists the check fails and instructs the user to set
`PAM50_PATH` or install the SCT data.

## Inputs and outputs

The inputs are `policy/datasets.yaml` and the host environment. Under the project
root, S0 writes the QC record (`logs/S0_setup_qc.json`), an environment
fingerprint (`state/setup_state.yaml`) recording the runtime, image digests, and
resolved template path, and an audit trail (`logs/S0_evidence/`).

## Quality control

The QC record carries the step code, the status, the failure message, and the list
of checks, each with its name, outcome, message, and collected information such as
the runtime version or an image digest. The recorded image digests and template
path pin the environment that produced a given run, and feed the reproducibility
receipt at S10. S0 emits no reportlet, since it produces no images.

## Limitations

S0 confirms that tools are present and report a version; it does not test that
they compute correctly. Image verification requires docker, so an apptainer-only
host fails this check even when the pipeline would run. The SpinePrep image has no
default and must be named through `SPINEPREP_IMAGE`. The policy gate validates the
schema of `policy/datasets.yaml`, not whether the referenced datasets exist on
disk, which S1 checks.

## References

- De Leener, B., et al. (2018). PAM50: unbiased multimodal template of the
  brainstem and spinal cord. NeuroImage.

Running S0: see the [CLI reference](../reference/cli.md).

---
*Behaviour reflects `src/spineprep/S0_setup.py` (no `policy/S0*.yaml` by design);
verified against code 2026-07-15.*
