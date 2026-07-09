# Requirements & setup

This page lists what you need before running SpinePrep. For the step-by-step
walkthrough, see the [Quickstart](quickstart.md); for a fuller tour, see
[Install & use](tutorial.md).

## What SpinePrep needs

The full pipeline calls several neuroimaging tools — the **Spinal Cord Toolbox
(SCT)**, **FSL**, and **ANTs**. The supported way to get all of them in one place
is the container.

=== "Container (recommended)"

    You need **Docker** or, on HPC, **Apptainer / Singularity**. The container
    image bundles SCT, FSL, ANTs, PAM50 and SpinePrep itself, so nothing else has
    to be installed on the host.

    - [Docker Engine](https://docs.docker.com/get-docker/), or
    - [Apptainer](https://apptainer.org/docs/user/main/quick_start.html)

    SpinePrep ships as a **build recipe** (`Dockerfile.spineprep`), not a prebuilt
    image — see the [Quickstart](quickstart.md) for the build command and why.

=== "Local (advanced)"

    If you would rather not use a container, you need on your `PATH`:

    - **SCT** (Spinal Cord Toolbox)
    - **FSL** (for `topup` and PNM)
    - **ANTs**
    - **Python 3.10–3.12**

    Then install the Python orchestration layer:

    ```bash
    pip install spineprep
    # or, from a clone:
    git clone https://github.com/SpinePrep/SpinePrep.git
    cd SpinePrep && pip install .
    ```

    The Python package alone does not include SCT/FSL/ANTs; installing those is
    your responsibility in this mode.

## Hardware

- SpinePrep runs on a normal workstation; no GPU is required.
- A GPU can speed up SCT's deep-learning segmentation (S2) substantially, but the
  pipeline runs correctly on CPU.
- Disk: allow room for BIDS-Derivatives outputs and the QC reports alongside your
  input data.

## Your data

SpinePrep expects a **[BIDS](https://bids.neuroimaging.io/)** dataset. At minimum
it needs the functional runs; it also uses an anatomical image for the cord
reference, and will make use of fieldmaps and physiological recordings if they
are present. S1 (Input Verify) checks the layout and reports what it found before
any processing runs.

## Next

- [Quickstart](quickstart.md) — build the image and run it on your data.
- [Methods overview](methods/overview.md) — what each step does.
- [CLI reference](reference/cli.md) — every command-line option.
