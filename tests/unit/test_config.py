"""Unit tests for configuration handling."""

from pathlib import Path

from spineprep.config import load_config


def test_motion_engine_defaults_and_enum(tmp_path: Path):
    """Test motion engine configuration defaults and enum validation."""
    p = tmp_path / "cfg.yaml"
    p.write_text(
        """
pipeline_version: "0.2.0"
project_name: "SpinePrep"
study: { name: "T" }
paths: { root: "%s" }
dataset: { sessions: null, runs_per_subject: null }
acq: { tr: 2.0, slice_timing: "ascending", pe_dir: "AP", echo_spacing_s: null }
options:
  ingest: { enable: false }
  denoise_mppca: false
  smoothing: { enable: false, fwhm_mm: 2.0 }
  sdc: { enable: false, mode: "auto" }
  first_level: { engine: "feat", feat_variant: "x" }
  cleanup: { keep_only_latest_stage: false }
  motion: { engine: rigid3d, slice_axis: z }
templates: { pam50_version: "1.0" }
tools: { sct: ">=5.8", fsl: "any" }
resources: { default_threads: 2, default_mem_gb: 2 }
qc: { subject_report: false, cohort_report: false }
registration: { enable: false, template: PAM50, guidance: SCT, levels: auto, use_gm_wm_masks: true, rootlets: { enable: false, mode: atlas } }
"""
        % tmp_path
    )
    cfg = load_config(str(p))
    assert cfg["options"]["motion"]["engine"] in (
        "sct",
        "rigid3d",
        "sct+rigid3d",
        "rigid3d",
    )
    assert cfg["options"]["motion"]["slice_axis"] in ("x", "y", "z")
