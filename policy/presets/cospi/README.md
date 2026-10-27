# Preset `cospi`

The settings the CoSpi study runs SpinePrep with. Select with `SPINEPREP_PRESET=cospi`;
the defaults in `policy/` are unchanged. Each file holds only the keys it changes.

| Step | Setting | Default | cospi |
|---|---|---|---|
| S2B | MP-PCA denoising | off | on, 8 threads |
| S5 | distortion correction | auto (topup when a reversed-phase pair exists) | none |
| S9 | cord-aware smoothing | off | on, with the default sigma 1/1/5 mm (not changed by the preset) |
