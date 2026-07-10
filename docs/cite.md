# Cite SpinePrep

If you use SpinePrep in your research, please cite the software and the
underlying tools it relies on. SpinePrep is an integration pipeline — most of the
scientific method it applies was developed by others, and those authors deserve
credit alongside SpinePrep itself.

## Software

Until a peer-reviewed paper is available, cite the software release:

!!! quote "BibTeX"
    ```bibtex
    @software{spineprep,
      title   = {SpinePrep: a containerised BIDS-App for reproducible
                 spinal-cord fMRI preprocessing},
      author  = {Sharifi, Kiomars},
      year    = {2026},
      version = {26.0.0},
      url     = {https://spineprep.com},
      note    = {https://github.com/SpinePrep/SpinePrep}
    }
    ```

The repository ships a [`CITATION.cff`](https://github.com/SpinePrep/SpinePrep/blob/main/CITATION.cff),
so GitHub's "Cite this repository" button will always give the current, correct
form.

## DOI

Each tagged release is archived on Zenodo and receives its own DOI. The archival
DOI will be shown here once the first release is deposited.

*DOI: pending first Zenodo deposit.*

## Tools you should also cite

SpinePrep calls the following tools. Cite the ones your run actually used — the
auto-generated methods boilerplate in each run's report lists them explicitly,
and the [`NOTICE`](https://github.com/SpinePrep/SpinePrep/blob/main/NOTICE) file
records their licenses.

| Tool | Used for | Canonical reference |
|------|----------|---------------------|
| **Spinal Cord Toolbox (SCT)** | cord segmentation, registration, PAM50 | De Leener et al., *NeuroImage* 145 (2017) 24–43 |
| **PAM50 template** | template space | De Leener et al., *NeuroImage* 165 (2018) 170–179 |
| **FSL** (topup, PNM) | distortion correction, physiological regressors | Jenkinson et al., *NeuroImage* 62 (2012) 782–790 |
| **topup** | susceptibility distortion | Andersson et al., *NeuroImage* 20 (2003) 870–888 |
| **RETROICOR / PNM** | cardiac & respiratory regressors | Brooks et al., *NeuroImage* 39 (2008) 680–692 |
| **ANTs** | image registration | Avants et al., *NeuroImage* 54 (2011) 2033–2044 |

Please also check each tool's own website for its preferred, up-to-date citation,
as these can change.

## Publications using SpinePrep

Work that uses SpinePrep will be listed here as it appears. If you publish with
it, let us know via a
[GitHub issue](https://github.com/SpinePrep/SpinePrep/issues) and we will add it.

## Acknowledgements

SpinePrep builds directly on the work of others:

- [Spinal Cord Toolbox (SCT)](https://spinalcordtoolbox.com/) — the core cord
  processing algorithms.
- [fMRIPrep](https://fmriprep.org/) — the design philosophy (BIDS-native,
  containerised, QC-first) that SpinePrep follows for the spinal cord.
- [BIDS](https://bids.neuroimaging.io/) — the data-organisation standard.
