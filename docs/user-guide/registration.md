# Registration

SpinePrep uses spinal cord-specific registration methods to align data to standard space. This guide explains the registration pipeline, methods, and quality assessment.

## Registration Pipeline

SpinePrep follows a multi-step registration process:

1. **Spinal cord segmentation**: Identify spinal cord boundaries
2. **Vertebral level detection**: Identify vertebral levels
3. **Template registration**: Align to standard space (PAM50)
4. **Quality assessment**: Evaluate registration quality

## Registration Methods

### SCT-Guided Registration

SpinePrep primarily uses the Spinal Cord Toolbox (SCT) for registration:

```bash
# Spinal cord segmentation
sct_deepseg_sc -i T2w.nii.gz -c t2

# Vertebral level detection
sct_label_vertebrae -i T2w.nii.gz -s cord_seg.nii.gz

# Template registration
sct_register_to_template -i T2w.nii.gz -s cord_seg.nii.gz -l labels.nii.gz
```

### Registration Steps

1. **Preprocessing**:
   - Bias field correction
   - Intensity normalization
   - Cropping to spinal cord region

2. **Segmentation**:
   - Spinal cord segmentation using deep learning
   - Vertebral level labeling
   - Quality control of segmentation

3. **Registration**:
   - Affine registration to template
   - Non-linear registration (if specified)
   - Quality assessment

## Template Spaces

### PAM50 Template

The PAM50 template is the standard space for spinal cord imaging:

- **Resolution**: 0.5 × 0.5 × 0.5 mm
- **Coverage**: C1-C7 vertebral levels
- **Orientation**: RPI (Right-Posterior-Inferior)

### Template Files

```
templates/
├── PAM50/
│   ├── PAM50_t2.nii.gz          # T2-weighted template
│   ├── PAM50_cord.nii.gz         # Spinal cord mask
│   ├── PAM50_levels.nii.gz       # Vertebral level labels
│   └── PAM50_cord_labeled.nii.gz # Labeled spinal cord
```

## Registration Quality

### Quality Metrics

SpinePrep assesses registration quality using:

- **Dice coefficient**: Overlap between registered and template masks
- **Hausdorff distance**: Maximum distance between boundaries
- **Jacobian determinant**: Local volume changes
- **Visual inspection**: Overlay of registered and template images

### Quality Thresholds

```yaml
registration:
  quality:
    dice_threshold: 0.8
    hausdorff_threshold: 2.0
    jacobian_threshold: 0.5
```

### Quality Assessment

```python
# Calculate Dice coefficient
dice = dice_coefficient(registered_mask, template_mask)

# Calculate Hausdorff distance
hausdorff = hausdorff_distance(registered_boundary, template_boundary)

# Check Jacobian determinant
jacobian = calculate_jacobian(transform)
jacobian_valid = (jacobian > 0.5).all()
```

## Registration Workflow

### Step 1: Spinal Cord Segmentation

```bash
# Deep learning segmentation
sct_deepseg_sc -i T2w.nii.gz -c t2 -o cord_seg.nii.gz

# Quality control
sct_qc -i T2w.nii.gz -s cord_seg.nii.gz -p sct_deepseg_sc
```

### Step 2: Vertebral Level Detection

```bash
# Label vertebrae
sct_label_vertebrae -i T2w.nii.gz -s cord_seg.nii.gz -o labels.nii.gz

# Quality control
sct_qc -i T2w.nii.gz -s labels.nii.gz -p sct_label_vertebrae
```

### Step 3: Template Registration

```bash
# Register to template
sct_register_to_template -i T2w.nii.gz -s cord_seg.nii.gz -l labels.nii.gz -o T2w_reg.nii.gz

# Quality control
sct_qc -i T2w_reg.nii.gz -s cord_seg_reg.nii.gz -p sct_register_to_template
```

## Registration Parameters

### Affine Registration

```yaml
registration:
  affine:
    method: "flirt"  # or "ants"
    cost_function: "mutualinfo"
    dof: 12
    search_angles: [45, 45, 45]
    search_translations: [10, 10, 10]
```

### Non-linear Registration

```yaml
registration:
  nonlinear:
    method: "ants"
    transformation: "SyN"
    metric: "CC"
    iterations: [100, 50, 25]
    shrink_factors: [2, 1, 1]
    smoothing_sigmas: [1, 0.5, 0]
```

## Registration Outputs

### Registered Images

- **T2w_reg.nii.gz**: T2-weighted image in template space
- **cord_seg_reg.nii.gz**: Spinal cord segmentation in template space
- **labels_reg.nii.gz**: Vertebral level labels in template space

### Transform Files

- **T2w_to_template_affine.mat**: Affine transformation matrix
- **T2w_to_template_warp.nii.gz**: Non-linear warp field (if used)
- **template_to_T2w_affine.mat**: Inverse affine transformation
- **template_to_T2w_warp.nii.gz**: Inverse non-linear warp field

### Quality Reports

- **registration_quality.json**: Quantitative quality metrics
- **registration_quality.html**: Visual quality assessment
- **registration_plots.png**: Registration visualization plots

## Registration Visualization

### Overlay Plots

SpinePrep generates overlay plots showing:

- Registered image overlaid on template
- Segmentation boundaries
- Vertebral level labels
- Quality metrics

### Quality Plots

- Dice coefficient over time
- Hausdorff distance distribution
- Jacobian determinant maps
- Registration error maps

## Troubleshooting Registration

### Common Issues

**Issue**: Poor segmentation quality
**Solutions**:
- Check image quality and contrast
- Verify SCT installation
- Try different segmentation parameters

**Issue**: Registration failure
**Solutions**:
- Check template compatibility
- Verify segmentation quality
- Try different registration parameters

**Issue**: Poor registration quality
**Solutions**:
- Check initial alignment
- Verify template space
- Consider different registration methods

### Debug Mode

Enable debug mode for detailed registration information:

```bash
spineprep --debug config.yaml
```

This will show:
- Registration command details
- Intermediate file paths
- Quality metric calculations
- Error messages

## Registration Best Practices

### Preprocessing

1. **Bias field correction**: Essential for good registration
2. **Intensity normalization**: Helps with template matching
3. **Cropping**: Focus on spinal cord region

### Quality Control

1. **Visual inspection**: Always check registration visually
2. **Quantitative metrics**: Use Dice and Hausdorff distances
3. **Template validation**: Verify template space and orientation

### Parameter Tuning

1. **Start with defaults**: Use recommended parameters
2. **Iterative refinement**: Adjust based on quality metrics
3. **Subject-specific tuning**: Adapt parameters for difficult cases

## Registration in Analysis

### Using Registration Outputs

```python
import nibabel as nib

# Load registered image
img_reg = nib.load('T2w_reg.nii.gz')
data_reg = img_reg.get_fdata()

# Load segmentation
seg_reg = nib.load('cord_seg_reg.nii.gz')
mask_reg = seg_reg.get_fdata() > 0

# Apply mask
data_masked = data_reg[mask_reg]
```

### Coordinate Systems

SpinePrep uses standard neuroimaging coordinate systems:

- **Template space**: PAM50 (RPI orientation)
- **Subject space**: Original image orientation
- **Transform files**: FSL/ANTs compatible

### Transform Applications

```python
# Apply transform to image
from sct_utils import apply_transfo

# Forward transform (subject to template)
img_reg = apply_transfo(img_subject, warp_file, template_file)

# Inverse transform (template to subject)
img_subject = apply_transfo(img_template, warp_inv_file, subject_file)
```
