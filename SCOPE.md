# SpinePrep Scope

## Current Scope (REG-4A + SPI-002 + SPI-003 + SPI-004)

### Included Features
- **SCT-guided Registration**: EPI to T2w and T2w to PAM50 registration
- **Spinal Cord Segmentation**: Automated cord segmentation using SCT
- **Vertebral Level Labeling**: Automatic vertebral level identification
- **Mask Generation**: Cord, WM, and CSF masks in native and PAM50 spaces
- **Pluggable Motion Engines**: SCT slice-wise, rigid3d, and hybrid motion correction
- **Grouped Motion Correction**: Concatenate→SCT→split workflow for compatible runs
- **Motion Parameter Extraction**: BIDS-compliant motion parameter files
- **Temporal Crop (TRIM)**: Automatic head/tail volume trimming with robust z-stats
- **Graceful Degradation**: Fallback behavior when SCT tools are unavailable
- **Provenance Tracking**: Complete metadata for all registration and motion steps
- **QC Integration**: Registration status, motion metrics, and trim badges in subject reports

### Out-of-Scope (Future Tickets)
- **Advanced Registration**: Multi-modal registration beyond EPI-T2w
- **Custom Templates**: Support for non-PAM50 templates
- **Manual Corrections**: Interactive registration quality control
- **Advanced Masking**: Tissue-specific segmentation beyond cord/WM/CSF
- **Registration QC**: Automated quality assessment of registration results
- **Slice Timing Correction**: Slice timing correction (SDC) - separate ticket
- **Advanced Motion Models**: Non-rigid motion correction beyond current engines
- **Advanced Temporal Cropping**: Beyond robust z-stats (e.g., ICA-based detection)
- **Batch Processing**: Optimized parallel processing for large datasets
- **Container Support**: Docker/Singularity integration for SCT tools

### Technical Limitations
- **SCT Dependency**: Requires SCT installation for full functionality
- **Template Lock-in**: Currently limited to PAM50 template
- **Single Session**: No multi-session registration support
- **Basic Masking**: Limited to standard cord/WM/CSF masks

### Future Enhancements
- **Multi-session Registration**: Cross-session alignment
- **Advanced QC**: Registration quality metrics and visualization
- **Custom Templates**: Support for study-specific templates
- **Interactive QC**: Web-based registration review interface
- **Performance Optimization**: GPU acceleration and parallel processing

## Confounds & aCompCor Scope (SPI-005C)

### Included Features
- **Framewise Displacement (FD)**: Power et al. (2012) method from motion parameters
- **DVARS**: Root mean square of BOLD signal changes between consecutive volumes
- **Frame Censoring**: Optional scrubbing based on FD/DVARS thresholds with padding and contiguity rules
- **aCompCor**: Anatomical component-based noise correction using tissue masks
- **Mask Integration**: Cord, WM, and CSF masks from SCT registration pipeline
- **Temporal Crop Integration**: Confounds computed on cropped BOLD data
- **QC Visualization**: FD/DVARS plots with censoring overlays and EV plots
- **BIDS Compliance**: Standard confounds TSV and JSON sidecar files

### aCompCor Implementation
- **Tissue Support**: Cord, white matter, and CSF masks
- **Preprocessing**: Detrending, high-pass filtering, and standardization
- **PCA Extraction**: Up to 5 components per tissue (configurable)
- **Rank Limiting**: Automatic capping at available rank
- **Empty Mask Handling**: Graceful skipping of tissues with no voxels
- **Output Format**: Canonical column order with tissue-specific PC columns

### Configuration Options
- **Mask Sources**: SCT-generated, user-provided, or disabled
- **aCompCor Settings**: Tissue selection, component counts, filtering parameters
- **Censoring Parameters**: FD/DVARS thresholds, padding, contiguity rules
- **Integration**: Temporal crop and motion correction coordination

### Out-of-Scope (Future Tickets)
- **Advanced aCompCor**: Non-linear preprocessing, ICA-based components
- **Custom Masks**: User-defined tissue regions beyond cord/WM/CSF
- **Advanced Censoring**: Machine learning-based outlier detection
- **Multi-tissue Models**: Cross-tissue component analysis
- **Real-time QC**: Live confounds monitoring during acquisition
- **Advanced Filtering**: Custom frequency domain processing
- **Component Selection**: Automated optimal component count selection

### Technical Limitations
- **Mask Dependency**: Requires SCT registration for full functionality
- **Tissue Limitation**: Limited to standard cord/WM/CSF masks
- **Linear PCA**: No non-linear component extraction
- **Single Run**: No cross-run component analysis
- **Basic Preprocessing**: Standard detrending and filtering only

### Future Enhancements
- **Advanced Preprocessing**: Non-linear detrending and filtering
- **Custom Masks**: User-defined tissue regions
- **Cross-run Analysis**: Multi-run component extraction
- **Interactive QC**: Real-time confounds visualization
- **Advanced Censoring**: ML-based outlier detection
- **Component Optimization**: Automated component count selection

## Documentation Scope (SPI-011)

### Docs as Product Invariants
The SpinePrep documentation site is treated as a first-class product with the following invariants:

- **User-Centric Design**: Documentation prioritizes user needs over technical completeness
- **Scientific Rigor**: All claims and recommendations are evidence-based and scientifically accurate
- **Accessibility**: Documentation is accessible to users with varying technical backgrounds
- **Maintainability**: Documentation is kept in sync with code changes through automated processes
- **Quality Assurance**: All documentation changes undergo the same quality gates as code changes

### Update Process
- **Automated Generation**: Reference documentation is auto-generated from schema and source code
- **CI Integration**: Documentation builds are part of the main CI pipeline
- **Version Control**: Documentation changes are tracked and reviewed like code changes
- **Quality Gates**: Linting, formatting, spell checking, and link checking are required
- **Deployment**: Documentation is automatically deployed on successful builds

### Content Standards
- **Accuracy**: All technical information must be accurate and up-to-date
- **Completeness**: Documentation covers all user-facing features and configuration options
- **Clarity**: Complex concepts are explained in clear, accessible language
- **Examples**: Practical examples are provided for all major use cases
- **Troubleshooting**: Common issues and solutions are documented
