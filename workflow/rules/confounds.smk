"""
Confounds computation rules for SpinePrep.

This module defines Snakemake rules for computing confounds:
- confounds_motion: compute FD/DVARS from motion params and BOLD
- confounds_compcor_censor: add aCompCor, tCompCor, and censoring to confounds
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


rule confounds_compcor_censor:
    """
    Extend confounds with aCompCor, tCompCor, and censoring columns.

    Inputs:
        - motion-corrected BOLD NIfTI
        - initial confounds TSV (from confounds_motion)
        - optional tissue masks (CSF, WM, cord)

    Outputs:
        - extended confounds TSV (all motion + CompCor + censor columns)
        - updated JSON sidecar
        - CompCor spectra QC PNG
    """
    input:
        bold="{prefix}_desc-motion_bold.nii.gz",
        confounds_tsv="{prefix}_desc-confounds_timeseries.tsv",
        confounds_json="{prefix}_desc-confounds_timeseries.json",
        mask_csf=(
            "{prefix}_mask-CSF.nii.gz"
            if _P("{prefix}_mask-CSF.nii.gz").exists()
            else []
        ),
        mask_wm=(
            "{prefix}_mask-WM.nii.gz" if _P("{prefix}_mask-WM.nii.gz").exists() else []
        ),
        mask_cord=(
            "{prefix}_mask-cord.nii.gz"
            if _P("{prefix}_mask-cord.nii.gz").exists()
            else []
        ),
    output:
        tsv="{prefix}_desc-confounds_extended_timeseries.tsv",
        json="{prefix}_desc-confounds_extended_timeseries.json",
        spectra_png="{prefix}_compcor_spectra.png",
    params:
        n_acompcor=6,
        n_tcompcor=6,
        tcompcor_topk_percent=2.0,
        fd_thresh=0.5,
        dvars_thresh=1.5,
    log:
        "{prefix}_confounds_compcor_censor.log",
    resources:
        mem_mb=1000,
    run:
        import sys
        from pathlib import Path

        # Add spineprep to path
        sys.path.insert(0, str(_P(workflow.basedir).parent))

        import nibabel as nib
        import numpy as np
        import pandas as pd

        from spineprep.confounds import (
            extract_timeseries,
            fit_compcor,
            make_censor_columns,
            plot_compcor_spectra_png,
            select_tcompcor_voxels,
            write_confounds_extended_tsv_json,
        )

        # Load existing confounds TSV
        confounds_df = pd.read_csv(input.confounds_tsv, sep="\t")
        motion_params = confounds_df[
            ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]
        ].values.astype(np.float32)
        fd = confounds_df["fd"].values.astype(np.float32)
        dvars = confounds_df["dvars"].values.astype(np.float32)

        # Load BOLD
        img = nib.load(input.bold)
        data_4d = img.get_fdata().astype(np.float32)

        # aCompCor: extract from CSF/WM masks if available
        acompcor_components = None
        acompcor_variance = None
        if input.mask_csf and input.mask_wm:
            try:
                mask_csf = nib.load(input.mask_csf).get_fdata().astype(bool)
                mask_wm = nib.load(input.mask_wm).get_fdata().astype(bool)
                combined_mask = mask_csf | mask_wm

                if combined_mask.sum() > 0:
                    ts = extract_timeseries(data_4d, combined_mask)
                    acompcor_components, acompcor_variance = fit_compcor(
                        ts, n_components=params.n_acompcor
                    )
            except Exception as e:
                print(f"Warning: aCompCor extraction failed: {e}")

                # tCompCor: select high-variance voxels from cord mask
        tcompcor_components = None
        tcompcor_variance = None
        if input.mask_cord:
            try:
                mask_cord = nib.load(input.mask_cord).get_fdata().astype(bool)
                if mask_cord.sum() > 0:
                    tcompcor_mask = select_tcompcor_voxels(
                        data_4d, mask_cord, topk_percent=params.tcompcor_topk_percent
                    )
                    ts = extract_timeseries(data_4d, tcompcor_mask)
                    tcompcor_components, tcompcor_variance = fit_compcor(
                        ts, n_components=params.n_tcompcor
                    )
            except Exception as e:
                print(f"Warning: tCompCor extraction failed: {e}")

                # Censoring columns
        censor_fd, censor_dvars, censor_any = make_censor_columns(
            fd,
            dvars,
            {"fd_thresh": params.fd_thresh, "dvars_thresh": params.dvars_thresh},
        )

        # Write extended confounds
        write_confounds_extended_tsv_json(
            tsv_path=output.tsv,
            json_path=output.json,
            motion_params=motion_params,
            fd=fd,
            dvars=dvars,
            acompcor_components=acompcor_components,
            tcompcor_components=tcompcor_components,
            censor_fd=censor_fd,
            censor_dvars=censor_dvars,
            censor_any=censor_any,
        )

        # Plot CompCor spectra
        plot_compcor_spectra_png(
            png_path=output.spectra_png,
            acompcor_variance=acompcor_variance,
            tcompcor_variance=tcompcor_variance,
        )

        # Log summary
        with open(log[0], "w") as f:
            f.write(f"Extended confounds computed for {input.bold}\n")
            f.write(f"  Timepoints: {len(fd)}\n")
            if acompcor_components is not None:
                f.write(
                    f"  aCompCor: {acompcor_components.shape[1]} components, "
                    f"cumulative variance: {acompcor_variance.sum()*100:.1f}%\n"
                )
            else:
                f.write("  aCompCor: skipped (no masks)\n")
            if tcompcor_components is not None:
                f.write(
                    f"  tCompCor: {tcompcor_components.shape[1]} components, "
                    f"cumulative variance: {tcompcor_variance.sum()*100:.1f}%\n"
                )
            else:
                f.write("  tCompCor: skipped (no mask)\n")
            f.write(
                f"  Censoring: {censor_any.sum()}/{len(censor_any)} frames "
                f"(FD: {censor_fd.sum()}, DVARS: {censor_dvars.sum()})\n"
            )
