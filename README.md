# SpinePrep

SpinePrep is a BIDS-first spinal cord fMRI preprocessing pipeline built around the PAM50 template, optional modules such as MP-PCA denoising and spatial smoothing, FSL FEAT-based modeling for now with a Python GLM planned, Snakemake orchestration, and profiles for both local execution and SLURM clusters.

## Quick Start

```bash
# clone and enter
git clone https://github.com/kiomarssharifi/SpinePrep && cd SpinePrep

# optional: create venv and install package (CLI will be added next step)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# coming next: spineprep validate / plan / run (CLI to be added)
```

## How to cite

See the [CITATION.cff](./CITATION.cff) file and forthcoming Zenodo record (DOI: 10.5281/zenodo.xxxxxxx) for citation details.

## License

Code is provided under the [Apache License 2.0](./LICENSE). Documentation and media assets, when added, may be released under the Creative Commons Attribution 4.0 International (CC BY 4.0) license.
