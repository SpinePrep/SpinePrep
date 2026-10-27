"""S2B_func_denoise: optional MP-PCA thermal-noise denoising of the raw BOLD series.

Disabled by default (`enabled: false` in `policy/S2B_func_denoise.yaml`); when
disabled the step passes through with no outputs and S3 reads the raw BOLD.

Input: the raw 4D BOLD of each run, located through the S1 inventory
(`work/S1_input_verify/<dataset>/bids_inventory.json`).

Output: `denoise/<run_id>/desc-denoised_bold.nii.gz` (read by S3 when present) and
`denoise/<run_id>/denoise_noise_map.nii.gz` under the output root; QC record
`logs/S2B_func_denoise/<dataset>/qc.json`.

QC picture: three PNGs under `derivatives/spineprep/<dataset>/sub-<id>/figures/`:
`desc-S2B_noise_sigma` (estimated noise map, expected flat and free of anatomy),
`desc-S2B_tsnr_before_after` (tSNR on matched slices), and
`desc-S2B_residual_structure` (temporal SD of the removed signal; visible cord or
CSF anatomy here means signal was removed).

Usage:
    spineprep run S2B_func_denoise --dataset-key <key> --out <out_dir>
The step runs inside `spineprep <bids_dir> <out_dir> participant`.
"""
from .orchestrate import run_S2B_func_denoise, check_S2B_func_denoise

__all__ = ["run_S2B_func_denoise", "check_S2B_func_denoise"]
