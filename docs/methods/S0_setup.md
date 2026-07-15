---
search:
  boost: 1
---

# S0: Developer environment check

S0 is a maintainer utility, not a pipeline step. It does not run when SpinePrep is
invoked as a BIDS-App: the participant level runs S1 to S9 and the group level
runs S10. Users preprocessing their own dataset never invoke S0, and this page is
here for contributors working from a repository checkout.

S0 confirms that a development machine can build and run the containers the
project ships, and that the dataset registry used for the maintainers' validation
cohort is well formed. It reads no imaging data and writes no derivatives.

## What it checks

S0 runs a policy gate and a set of environment checks, and reports PASS or FAIL.
Any failed check fails the step, and the message names the first failure. There is
no warning state.

The policy gate validates the maintainers' dataset registry against its v1 schema,
requiring the mandatory fields, unique dataset keys, valid selection constraints,
and boolean specification flags. This registry exists only to drive the internal
validation cohort; it is not required to process a dataset.

The environment checks locate a container runtime by searching for `docker`, then
`apptainer`, and verify the container images and the PAM50 template data.

## Container images

Image verification is implemented for docker only. On a host whose runtime is
apptainer the image check fails with "Image checks require docker; apptainer path
not implemented". Apptainer can still run the pipeline; it just cannot satisfy
this check.

Each image is inspected with `docker image inspect` to confirm it is present
locally and to record its repository digest, then a version command is executed
inside it with `docker run --rm`:

`SPINEPREP_IMAGE` (environment variable, no default): `spineprep --version` and `python --version`.
`vnmd/spinalcordtoolbox_7.2:20251215`: `sct_version`.
`vnmd/fsl_6.0.7.18_20250928`: `fslversion`.
`vnmd/ants_2.6.0_20250424`: `antsRegistration --version`.

## PAM50 template

The PAM50 template directory (De Leener et al., 2018) is searched in order: the
`PAM50_PATH` environment variable, then `$SCT_DIR/data/PAM50`, then
`~/sct_7.1/data/PAM50`. The first existing path is recorded. If none exists the
check fails and instructs the user to set `PAM50_PATH` or install the SCT data.

## Outputs

S0 writes a QC record listing every check with its outcome and collected
information such as the runtime version or an image digest, an environment
fingerprint recording the runtime, image digests, and resolved template path, and
an audit trail. The recorded digests and template path pin the environment that
produced a given run.

## Limitations

S0 confirms that tools are present and report a version; it does not test that
they compute correctly. Image verification requires docker, so an apptainer-only
host fails that check even when the pipeline would run. The SpinePrep image has no
default and must be named through `SPINEPREP_IMAGE`.

## References

- De Leener, B., et al. (2018). PAM50: unbiased multimodal template of the
  brainstem and spinal cord. NeuroImage.

---
*Behaviour reflects `src/spineprep/S0_setup.py`; verified against the
implementation on 2026-07-15.*
