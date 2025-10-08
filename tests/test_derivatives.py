"""Tests for BIDS-Derivatives tree layout and sidecars."""

from __future__ import annotations

import json


def test_confounds_sidecar_schema():
    """Test that confounds JSON sidecar matches required schema."""
    from spineprep.derivatives import build_confounds_sidecar

    sidecar = build_confounds_sidecar(
        fd_method="power_fd",
        dvars_method="std_dvars",
        tr_s=2.0,
        censor_params={
            "fd_thresh_mm": 0.5,
            "dvars_thresh": 1.5,
            "n_censored": 10,
            "n_kept": 190,
        },
        acompcor_meta={},
    )

    # Required keys
    assert "GeneratedBy" in sidecar
    assert "Sources" in sidecar
    assert "confounds" in sidecar

    # GeneratedBy structure
    gen_by = sidecar["GeneratedBy"]
    assert isinstance(gen_by, list)
    assert len(gen_by) > 0
    assert gen_by[0]["Name"] == "SpinePrep"
    assert "Version" in gen_by[0]
    assert "CodeURL" in gen_by[0]

    # Confounds columns
    confounds = sidecar["confounds"]
    assert "framewise_displacement" in confounds
    assert confounds["framewise_displacement"]["method"] == "power_fd"
    assert "dvars" in confounds
    assert confounds["dvars"]["method"] == "std_dvars"


def test_motion_sidecar_schema():
    """Test that motion params JSON sidecar has required structure."""
    from spineprep.derivatives import build_motion_sidecar

    sidecar = build_motion_sidecar(
        engine="sct+rigid3d",
        slice_axis="IS",
        sources=["/bids/sub-01/func/sub-01_task-rest_run-01_bold.nii.gz"],
    )

    # Required keys
    assert "GeneratedBy" in sidecar
    assert "Sources" in sidecar
    assert "Parameters" in sidecar

    # Parameters
    params = sidecar["Parameters"]
    assert "engine" in params
    assert params["engine"] == "sct+rigid3d"
    assert "slice_axis" in params


def test_derivatives_dataset_description():
    """Test that dataset_description.json has required BIDS-Derivatives fields."""
    from spineprep.derivatives import build_dataset_description

    desc = build_dataset_description(
        source_datasets=["/data/bids"],
        pipeline_version="0.1.0-dev",
    )

    # Required BIDS-Derivatives fields
    assert desc["Name"] == "SpinePrep Derivatives"
    assert desc["BIDSVersion"] == "1.8.0"
    assert desc["DatasetType"] == "derivative"
    assert "GeneratedBy" in desc
    assert len(desc["GeneratedBy"]) > 0
    assert desc["GeneratedBy"][0]["Name"] == "SpinePrep"
    assert desc["GeneratedBy"][0]["Version"] == "0.1.0-dev"
    assert "SourceDatasets" in desc


def test_provenance_snapshot():
    """Test that provenance snapshot captures key environment details."""
    from spineprep.derivatives import build_provenance_snapshot

    prov = build_provenance_snapshot(
        config_path="/path/to/config.yaml",
        bids_root="/data/bids",
        deriv_root="/data/derivatives/spineprep",
    )

    # Required fields
    assert "pipeline_version" in prov
    assert "timestamp" in prov
    assert "environment" in prov
    assert "paths" in prov

    # Environment details
    env = prov["environment"]
    assert "python_version" in env
    assert "os" in env

    # Paths
    paths = prov["paths"]
    assert "bids_root" in paths
    assert "deriv_root" in paths
    assert "config_path" in paths


def test_derivatives_path_rules():
    """Test that derivative file paths follow BIDS-Derivatives naming."""
    from spineprep.derivatives import derive_paths

    paths = derive_paths(
        deriv_root="/data/derivatives/spineprep",
        sub="sub-01",
        task="rest",
        run="01",
        session=None,
    )

    # Check confounds paths
    assert "confounds_tsv" in paths
    assert "sub-01" in paths["confounds_tsv"]
    assert "task-rest" in paths["confounds_tsv"]
    assert "run-01" in paths["confounds_tsv"]
    assert "desc-confounds_timeseries.tsv" in paths["confounds_tsv"]

    # Check motion paths
    assert "motion_params_tsv" in paths
    assert "desc-motion_params.tsv" in paths["motion_params_tsv"]


def test_write_provenance_json(tmp_path):
    """Test that provenance JSON is written correctly."""
    from spineprep.derivatives import write_provenance_json

    prov_data = {
        "pipeline_version": "0.1.0-dev",
        "timestamp": "2025-10-08T12:00:00",
        "environment": {"python_version": "3.11.0"},
    }

    out_file = tmp_path / "provenance.json"
    write_provenance_json(prov_data, out_file)

    assert out_file.exists()

    # Validate content
    with open(out_file) as f:
        loaded = json.load(f)

    assert loaded["pipeline_version"] == "0.1.0-dev"
    assert "timestamp" in loaded


def test_intended_for_field():
    """Test that IntendedFor field is correctly formatted."""
    from spineprep.derivatives import build_intended_for

    # For a motion-corrected BOLD
    intended = build_intended_for(
        sources=["/bids/sub-01/func/sub-01_task-rest_run-01_bold.nii.gz"],
        deriv_root="/data/derivatives/spineprep",
    )

    assert isinstance(intended, list)
    if intended:
        # Should be relative BIDS paths
        assert "sub-01" in intended[0]
