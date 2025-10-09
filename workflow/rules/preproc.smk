# Preprocessing rules for SpinePrep

import csv
from pathlib import Path


# Read manifest to get functional series
def get_func_series():
    """Get list of functional series from manifest."""
    manifest_csv = config.get("manifest_csv", f"{config['out_dir']}/manifest.csv")
    manifest_path = Path(manifest_csv)

    if not manifest_path.exists():
        return []

    func_series = []
    with open(manifest_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["modality"] == "func":
                func_series.append(row)

    return func_series


FUNC_SERIES = get_func_series()
OUT_DIR = config.get("out_dir", "./out")


# Build mapping of output names to input paths
DENOISE_PAIRS = []
for series in FUNC_SERIES:
    in_path = series["filepath"]
    filepath = Path(in_path)
    # Remove .nii.gz extension
    stem = filepath.name.replace(".nii.gz", "").replace(".nii", "")
    out_path = f"{OUT_DIR}/denoised/{stem}_desc-mppca_bold.nii.gz"
    DENOISE_PAIRS.append((in_path, out_path))


rule denoise_bold:
    """Apply MP-PCA denoising to BOLD series."""
    input:
        bold=lambda wildcards: [
            pair[0]
            for pair in DENOISE_PAIRS
            if pair[1].endswith(f"{wildcards.stem}_desc-mppca_bold.nii.gz")
        ][0],
    output:
        denoised="{outdir}/denoised/{stem}_desc-mppca_bold.nii.gz",
    params:
        patch=5,
        stride=3,
    shell:
        """
        python -m spineprep.preproc.denoise_cli \
            --in {input.bold} \
            --out {output.denoised} \
            --patch {params.patch} \
            --stride {params.stride}
        """


def get_denoise_outputs():
    """Get list of expected denoised outputs."""
    return [pair[1] for pair in DENOISE_PAIRS]
