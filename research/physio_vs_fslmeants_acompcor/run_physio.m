function run_physio()
% Run PhysIO noise_rois (aCompCor) on slice01 only.
% Output: physio_slice01.txt with [mean, pc1..pc5] z-scored.

addpath('/home/kiomars/Documents/MATLAB/spm12');
addpath(genpath('/home/kiomars/Documents/MATLAB/tapas/PhysIO'));

bold = '/tmp/physio_verify/bold.nii';
mask = '/tmp/physio_verify/mask_slice01.nii';

header = niftiinfo(bold);
TR       = header.PixelDimensions(4);
NSlices  = header.ImageSize(3);
NVolumes = header.ImageSize(4);

fprintf('TR=%g NSlices=%d NVolumes=%d\n', TR, NSlices, NVolumes);

clear matlabbatch
matlabbatch{1}.spm.tools.physio.save_dir = {'/tmp/physio_verify'};
matlabbatch{1}.spm.tools.physio.log_files.vendor = 'Siemens';
matlabbatch{1}.spm.tools.physio.log_files.cardiac = {''};
matlabbatch{1}.spm.tools.physio.log_files.respiration = {''};
matlabbatch{1}.spm.tools.physio.log_files.scan_timing = {''};
matlabbatch{1}.spm.tools.physio.log_files.sampling_interval = 0.005;
matlabbatch{1}.spm.tools.physio.log_files.relative_start_acquisition = 0;
matlabbatch{1}.spm.tools.physio.log_files.align_scan = 'last';
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.Nslices = NSlices;
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.NslicesPerBeat = [];
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.TR = TR;
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.Ndummies = 4;
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.Nscans = NVolumes;
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.onset_slice = 10;
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.time_slice_to_slice = [];
matlabbatch{1}.spm.tools.physio.scan_timing.sqpar.Nprep = 0;
matlabbatch{1}.spm.tools.physio.scan_timing.sync.nominal = struct([]);
matlabbatch{1}.spm.tools.physio.preproc.cardiac.modality = 'ECG';
matlabbatch{1}.spm.tools.physio.preproc.cardiac.filter.no = struct([]);
matlabbatch{1}.spm.tools.physio.preproc.cardiac.initial_cpulse_select.auto_matched.min = 0.4;
matlabbatch{1}.spm.tools.physio.preproc.cardiac.initial_cpulse_select.auto_matched.file = 'initial_cpulse_kRpeakfile.mat';
matlabbatch{1}.spm.tools.physio.preproc.cardiac.initial_cpulse_select.auto_matched.max_heart_rate_bpm = 120;
matlabbatch{1}.spm.tools.physio.preproc.cardiac.posthoc_cpulse_select.off = struct([]);
matlabbatch{1}.spm.tools.physio.preproc.respiratory.filter.passband = [0.01 2];
matlabbatch{1}.spm.tools.physio.preproc.respiratory.despike = false;
matlabbatch{1}.spm.tools.physio.model.output_multiple_regressors = 'physio_slice01.txt';
matlabbatch{1}.spm.tools.physio.model.output_physio = 'physio_slice01.mat';
matlabbatch{1}.spm.tools.physio.model.orthogonalise = 'none';
matlabbatch{1}.spm.tools.physio.model.censor_unreliable_recording_intervals = false;
matlabbatch{1}.spm.tools.physio.model.retroicor.no = struct([]);
matlabbatch{1}.spm.tools.physio.model.rvt.no = struct([]);
matlabbatch{1}.spm.tools.physio.model.hrv.no = struct([]);
matlabbatch{1}.spm.tools.physio.model.noise_rois.yes.fmri_files = {bold};
matlabbatch{1}.spm.tools.physio.model.noise_rois.yes.roi_files = {mask};
matlabbatch{1}.spm.tools.physio.model.noise_rois.yes.force_coregister = 'No';
matlabbatch{1}.spm.tools.physio.model.noise_rois.yes.thresholds = 0.9;
matlabbatch{1}.spm.tools.physio.model.noise_rois.yes.n_voxel_crop = 0;
matlabbatch{1}.spm.tools.physio.model.noise_rois.yes.n_components = 5;
matlabbatch{1}.spm.tools.physio.model.movement.no = struct([]);
matlabbatch{1}.spm.tools.physio.model.other.no = struct([]);
matlabbatch{1}.spm.tools.physio.verbose.level = 0;
matlabbatch{1}.spm.tools.physio.verbose.fig_output_file = '';
matlabbatch{1}.spm.tools.physio.verbose.use_tabs = false;

spm('defaults','FMRI');
spm_jobman('initcfg');
spm_jobman('run', matlabbatch);

fprintf('PhysIO done.\n');

end
