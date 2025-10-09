"""
Confounds computation rules for SpinePrep.

This module defines Snakemake rules for computing confounds:
- confounds_motion: compute FD/DVARS from motion params and BOLD
"""

from pathlib import Path as _P


rule confounds_motion:
    """
    Compute motion-based confounds (FD, DVARS) and generate QC plots.

    Inputs:
        - motion-corrected BOLD NIfTI
        - motion parameters TSV

    Outputs:
        - confounds TSV (motion params + FD + DVARS)
        - confounds JSON sidecar (schema v1)
        - motion QC PNG plot
    """
    input:
        bold="{prefix}_desc-motion_bold.nii.gz",
        motion_params="{prefix}_desc-motion_params.tsv",
    output:
        tsv="{prefix}_desc-confounds_timeseries.tsv",
        json="{prefix}_desc-confounds_timeseries.json",
        png="{prefix}_motion.png",
    log:
        "{prefix}_confounds_motion.log",
    resources:
        mem_mb=500,
    run:
        import sys
        from pathlib import Path

        # Add spineprep to path
        sys.path.insert(0, str(_P(workflow.basedir).parent))

        import nibabel as nib
        import numpy as np

        from spineprep.confounds import (
            compute_dvars,
            compute_fd_power,
            plot_motion_png,
            write_confounds_tsv_json,
        )

        # Load motion parameters from TSV
        import pandas as pd

        motion_df = pd.read_csv(input.motion_params, sep="\t")
        motion_params = motion_df[
            ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]
        ].values.astype(np.float32)

        # Compute FD
        fd = compute_fd_power(motion_params, radius_mm=50.0)

        # Load BOLD and compute DVARS
        img = nib.load(input.bold)
        data_4d = img.get_fdata().astype(np.float32)
        dvars = compute_dvars(data_4d)

        # Write outputs
        write_confounds_tsv_json(
            tsv_path=output.tsv,
            json_path=output.json,
            motion_params=motion_params,
            fd=fd,
            dvars=dvars,
        )

        plot_motion_png(
            png_path=output.png,
            motion_params=motion_params,
            fd=fd,
            dvars=dvars,
        )

        # Log summary
        with open(log[0], "w") as f:
            f.write(f"Confounds computed for {input.bold}\n")
            f.write(f"  Timepoints: {len(fd)}\n")
            f.write(f"  Mean FD: {fd.mean():.3f} mm\n")
            f.write(f"  Max FD: {fd.max():.3f} mm\n")
            f.write(f"  Mean DVARS: {dvars.mean():.3f}\n")
            f.write(f"  Max DVARS: {dvars.max():.3f}\n")
