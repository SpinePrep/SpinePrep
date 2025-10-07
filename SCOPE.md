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
