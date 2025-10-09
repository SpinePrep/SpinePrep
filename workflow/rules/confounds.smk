# Confounds computation rules

import csv
from pathlib import Path


# Read manifest to get functional series
def get_func_series_for_confounds():
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


FUNC_SERIES_CONFOUNDS = get_func_series_for_confounds()
OUT_DIR_CONFOUNDS = config.get("out_dir", "./out")


# Build confounds output pairs
CONFOUNDS_PAIRS = []
for series in FUNC_SERIES_CONFOUNDS:
    in_path = series["filepath"]
    filepath = Path(in_path)
    stem = filepath.name.replace(".nii.gz", "").replace(".nii", "")

    tsv_path = f"{OUT_DIR_CONFOUNDS}/confounds/{stem}_desc-basic_confounds.tsv"
    json_path = f"{OUT_DIR_CONFOUNDS}/confounds/{stem}_desc-basic_confounds.json"

    CONFOUNDS_PAIRS.append((in_path, tsv_path, json_path))


rule confounds_basic:
    """Compute basic confounds (motion, FD, DVARS, spikes) for BOLD."""
    input:
        bold=lambda wildcards: [
            pair[0]
            for pair in CONFOUNDS_PAIRS
            if pair[1].endswith(f"{wildcards.stem}_desc-basic_confounds.tsv")
        ][0],
    output:
        tsv="{outdir}/confounds/{stem}_desc-basic_confounds.tsv",
        json_sidecar="{outdir}/confounds/{stem}_desc-basic_confounds.json",
    params:
        fd_thr=0.5,
        dvars_z=2.5,
        radius=50.0,
    shell:
        """
        python -m spineprep.confounds.cli_basic \
            --in {input.bold} \
            --out {output.tsv} \
            --sidecar {output.json_sidecar} \
            --fd-thr {params.fd_thr} \
            --dvars-z {params.dvars_z} \
            --radius {params.radius}
        """


def get_confounds_outputs():
    """Get list of expected confounds TSV and JSON outputs."""
    outputs = []
    for pair in CONFOUNDS_PAIRS:
        outputs.append(pair[1])  # TSV
        outputs.append(pair[2])  # JSON
    return outputs
