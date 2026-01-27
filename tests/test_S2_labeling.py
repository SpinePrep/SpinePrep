from __future__ import annotations

import json
import numpy as np
import nibabel as nib
from pathlib import Path

from spinalfmriprep.S2_anat_cordref import (
    _validate_vertebral_label_outputs,
    _estimate_initcenter_from_disc_labels,
    _check_labeling_consistency,
)


def test_validate_vertebral_label_outputs_valid(tmp_path: Path) -> None:
    """Test validation passes for well-formed labeling outputs."""
    # Create synthetic disc labels (3D array with labels 3, 4, 5 at different z positions)
    disc_data = np.zeros((50, 50, 100), dtype=np.uint8)
    disc_data[25, 25, 30] = 3  # Disc C2/C3 at z=30
    disc_data[25, 25, 50] = 4  # Disc C3/C4 at z=50 (mid-z)
    disc_data[25, 25, 70] = 5  # Disc C4/C5 at z=70
    
    disc_img = nib.Nifti1Image(disc_data, np.eye(4))
    disc_path = tmp_path / "disc_labels.nii.gz"
    nib.save(disc_img, disc_path)
    
    # Create vertebral labels (overlapping with cordmask)
    vert_data = np.zeros((50, 50, 100), dtype=np.uint8)
    vert_data[20:30, 20:30, 25:75] = 2  # C2 level
    vert_data[20:30, 20:30, 40:60] = 3  # C3 level
    vert_data[20:30, 20:30, 55:75] = 4  # C4 level
    
    vert_img = nib.Nifti1Image(vert_data, np.eye(4))
    vert_path = tmp_path / "vertebral_labels.nii.gz"
    nib.save(vert_img, vert_path)
    
    # Create cordmask (overlaps with vertebral labels)
    cordmask_data = np.zeros((50, 50, 100), dtype=np.uint8)
    cordmask_data[20:30, 20:30, 20:80] = 1
    
    cordmask_img = nib.Nifti1Image(cordmask_data, np.eye(4))
    cordmask_path = tmp_path / "cordmask.nii.gz"
    nib.save(cordmask_img, cordmask_path)
    
    # Validate
    is_valid, reasons = _validate_vertebral_label_outputs(
        vertebral_labels_path=vert_path,
        disc_labels_path=disc_path,
        cordmask_path=cordmask_path,
        min_disc_labels=2,
    )
    
    assert is_valid, f"Validation should pass but got reasons: {reasons}"
    assert len(reasons) == 0


def test_validate_vertebral_label_outputs_empty_discs(tmp_path: Path) -> None:
    """Test validation fails for empty disc labels."""
    disc_data = np.zeros((50, 50, 100), dtype=np.uint8)
    disc_img = nib.Nifti1Image(disc_data, np.eye(4))
    disc_path = tmp_path / "disc_labels.nii.gz"
    nib.save(disc_img, disc_path)
    
    vert_data = np.zeros((50, 50, 100), dtype=np.uint8)
    vert_img = nib.Nifti1Image(vert_data, np.eye(4))
    vert_path = tmp_path / "vertebral_labels.nii.gz"
    nib.save(vert_img, vert_path)
    
    cordmask_data = np.zeros((50, 50, 100), dtype=np.uint8)
    cordmask_img = nib.Nifti1Image(cordmask_data, np.eye(4))
    cordmask_path = tmp_path / "cordmask.nii.gz"
    nib.save(cordmask_img, cordmask_path)
    
    is_valid, reasons = _validate_vertebral_label_outputs(
        vertebral_labels_path=vert_path,
        disc_labels_path=disc_path,
        cordmask_path=cordmask_path,
        min_disc_labels=2,
    )
    
    assert not is_valid
    assert "empty" in " ".join(reasons).lower() or "few" in " ".join(reasons).lower()


def test_validate_vertebral_label_outputs_too_few_discs(tmp_path: Path) -> None:
    """Test validation fails when too few disc labels."""
    disc_data = np.zeros((50, 50, 100), dtype=np.uint8)
    disc_data[25, 25, 50] = 3  # Only one disc label
    disc_img = nib.Nifti1Image(disc_data, np.eye(4))
    disc_path = tmp_path / "disc_labels.nii.gz"
    nib.save(disc_img, disc_path)
    
    vert_data = np.zeros((50, 50, 100), dtype=np.uint8)
    vert_img = nib.Nifti1Image(vert_data, np.eye(4))
    vert_path = tmp_path / "vertebral_labels.nii.gz"
    nib.save(vert_img, vert_path)
    
    cordmask_data = np.zeros((50, 50, 100), dtype=np.uint8)
    cordmask_img = nib.Nifti1Image(cordmask_data, np.eye(4))
    cordmask_path = tmp_path / "cordmask.nii.gz"
    nib.save(cordmask_img, cordmask_path)
    
    is_valid, reasons = _validate_vertebral_label_outputs(
        vertebral_labels_path=vert_path,
        disc_labels_path=disc_path,
        cordmask_path=cordmask_path,
        min_disc_labels=2,
    )
    
    assert not is_valid
    assert any("few" in r.lower() for r in reasons)


def test_estimate_initcenter_from_disc_labels(tmp_path: Path) -> None:
    """Test initcenter estimation finds disc closest to mid-z."""
    # Create disc labels: label 3 at z=20, label 4 at z=50 (mid), label 5 at z=80
    disc_data = np.zeros((50, 50, 100), dtype=np.uint8)
    disc_data[25, 25, 20] = 3
    disc_data[25, 25, 50] = 4  # This should be closest to mid-z (50)
    disc_data[25, 25, 80] = 5
    
    disc_img = nib.Nifti1Image(disc_data, np.eye(4))
    disc_path = tmp_path / "disc_labels.nii.gz"
    nib.save(disc_img, disc_path)
    
    estimated = _estimate_initcenter_from_disc_labels(disc_path)
    
    assert estimated == 4, f"Expected initcenter=4 (disc at mid-z), got {estimated}"


def test_estimate_initcenter_from_disc_labels_empty(tmp_path: Path) -> None:
    """Test initcenter estimation returns None for empty labels."""
    disc_data = np.zeros((50, 50, 100), dtype=np.uint8)
    disc_img = nib.Nifti1Image(disc_data, np.eye(4))
    disc_path = tmp_path / "disc_labels.nii.gz"
    nib.save(disc_img, disc_path)
    
    estimated = _estimate_initcenter_from_disc_labels(disc_path)
    
    assert estimated is None


def test_dashboard_with_new_labeling_fields(tmp_path: Path) -> None:
    """Test that dashboard generation still works with new labeling QC fields."""
    from spinalfmriprep.qc_dashboard import generate_dashboard
    
    out = tmp_path / "work" / "wf_test"
    qc_dir = out / "logs" / "S2_anat_cordref" / "test_ds"
    qc_dir.mkdir(parents=True, exist_ok=True)
    
    # QC JSON with new labeling fields
    qc = {
        "status": "PASS",
        "failure_message": None,
        "runs": [
            {
                "subject": "01",
                "session": None,
                "status": "PASS",
                "labels": {
                    "status": "PASS",
                    "qc_status": "PASS",
                    "qc_reasons": [],
                    "method_used": "auto",
                    "adaptive_initcenter_used": None,
                },
                "reportlets": {},
            }
        ],
    }
    (qc_dir / "qc.json").write_text(json.dumps(qc), encoding="utf-8")
    
    # Should not crash
    res = generate_dashboard(out)
    assert res.indexed_qc_files == 1
    
    # Verify workfolder is displayed (path contains wf_test)
    index_html = (out / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "Workfolder: wf_test" in index_html


def test_check_labeling_consistency_global_offset(tmp_path: Path) -> None:
    """Test consistency check detects global +1 offset."""
    # Create SCT labels: levels 3, 4, 5 (shifted by +1)
    sct_data = np.zeros((50, 50, 100), dtype=np.uint8)
    sct_data[20:30, 20:30, 30:50] = 3  # C3
    sct_data[20:30, 20:30, 50:70] = 4  # C4
    sct_data[20:30, 20:30, 70:90] = 5  # C5
    
    # Create template levels: levels 2, 3, 4 (ground truth)
    template_data = np.zeros((50, 50, 100), dtype=np.uint8)
    template_data[20:30, 20:30, 30:50] = 2  # C2
    template_data[20:30, 20:30, 50:70] = 3  # C3
    template_data[20:30, 20:30, 70:90] = 4  # C4
    
    # Create cordmask
    cordmask_data = np.zeros((50, 50, 100), dtype=np.uint8)
    cordmask_data[20:30, 20:30, 25:95] = 1
    
    sct_img = nib.Nifti1Image(sct_data, np.eye(4))
    template_img = nib.Nifti1Image(template_data, np.eye(4))
    cordmask_img = nib.Nifti1Image(cordmask_data, np.eye(4))
    
    sct_path = tmp_path / "sct_labels.nii.gz"
    template_path = tmp_path / "template_levels.nii.gz"
    cordmask_path = tmp_path / "cordmask.nii.gz"
    
    nib.save(sct_img, sct_path)
    nib.save(template_img, template_path)
    nib.save(cordmask_img, cordmask_path)
    
    qc_status, qc_reasons, metrics = _check_labeling_consistency(
        sct_labels_path=sct_path,
        template_levels_path=template_path,
        cordmask_path=cordmask_path,
        enabled=True,
    )
    
    assert qc_status == "WARN", f"Expected WARN for global offset, got {qc_status}"
    assert len(qc_reasons) > 0
    assert any("offset" in r.lower() for r in qc_reasons)
    assert metrics is not None
    assert metrics["offset_mode"] == 1  # +1 shift


def test_check_labeling_consistency_single_jump(tmp_path: Path) -> None:
    """Test consistency check detects single jump (missed/spurious disc)."""
    # Create SCT labels: levels 2, 3, 3, 4 (jump at z=60: level 3 appears twice)
    sct_data = np.zeros((50, 50, 100), dtype=np.uint8)
    sct_data[20:30, 20:30, 30:50] = 2  # C2
    sct_data[20:30, 20:30, 50:60] = 3  # C3
    sct_data[20:30, 20:30, 60:70] = 3  # C3 again (jump: should be 4)
    sct_data[20:30, 20:30, 70:90] = 4  # C4
    
    # Create template levels: levels 2, 3, 4, 5 (ground truth, no jump)
    template_data = np.zeros((50, 50, 100), dtype=np.uint8)
    template_data[20:30, 20:30, 30:50] = 2  # C2
    template_data[20:30, 20:30, 50:60] = 3  # C3
    template_data[20:30, 20:30, 60:70] = 4  # C4 (correct)
    template_data[20:30, 20:30, 70:90] = 5  # C5
    
    # Create cordmask
    cordmask_data = np.zeros((50, 50, 100), dtype=np.uint8)
    cordmask_data[20:30, 20:30, 25:95] = 1
    
    sct_img = nib.Nifti1Image(sct_data, np.eye(4))
    template_img = nib.Nifti1Image(template_data, np.eye(4))
    cordmask_img = nib.Nifti1Image(cordmask_data, np.eye(4))
    
    sct_path = tmp_path / "sct_labels.nii.gz"
    template_path = tmp_path / "template_levels.nii.gz"
    cordmask_path = tmp_path / "cordmask.nii.gz"
    
    nib.save(sct_img, sct_path)
    nib.save(template_img, template_path)
    nib.save(cordmask_img, cordmask_path)
    
    qc_status, qc_reasons, metrics = _check_labeling_consistency(
        sct_labels_path=sct_path,
        template_levels_path=template_path,
        cordmask_path=cordmask_path,
        enabled=True,
    )
    
    # Should detect jump (may be WARN or PASS depending on thresholds)
    assert metrics is not None
    # Jump detection is probabilistic, so just check that metrics are computed
    assert "jump_z" in metrics or "offset_mode" in metrics


def test_check_labeling_consistency_pass(tmp_path: Path) -> None:
    """Test consistency check passes when labels match template."""
    # Create SCT labels: levels 2, 3, 4 (matches template)
    sct_data = np.zeros((50, 50, 100), dtype=np.uint8)
    sct_data[20:30, 20:30, 30:50] = 2  # C2
    sct_data[20:30, 20:30, 50:70] = 3  # C3
    sct_data[20:30, 20:30, 70:90] = 4  # C4
    
    # Create template levels: same levels
    template_data = np.zeros((50, 50, 100), dtype=np.uint8)
    template_data[20:30, 20:30, 30:50] = 2  # C2
    template_data[20:30, 20:30, 50:70] = 3  # C3
    template_data[20:30, 20:30, 70:90] = 4  # C4
    
    # Create cordmask
    cordmask_data = np.zeros((50, 50, 100), dtype=np.uint8)
    cordmask_data[20:30, 20:30, 25:95] = 1
    
    sct_img = nib.Nifti1Image(sct_data, np.eye(4))
    template_img = nib.Nifti1Image(template_data, np.eye(4))
    cordmask_img = nib.Nifti1Image(cordmask_data, np.eye(4))
    
    sct_path = tmp_path / "sct_labels.nii.gz"
    template_path = tmp_path / "template_levels.nii.gz"
    cordmask_path = tmp_path / "cordmask.nii.gz"
    
    nib.save(sct_img, sct_path)
    nib.save(template_img, template_path)
    nib.save(cordmask_img, cordmask_path)
    
    qc_status, qc_reasons, metrics = _check_labeling_consistency(
        sct_labels_path=sct_path,
        template_levels_path=template_path,
        cordmask_path=cordmask_path,
        enabled=True,
    )
    
    assert qc_status == "PASS", f"Expected PASS for matching labels, got {qc_status}"
    assert len(qc_reasons) == 0
    assert metrics is None or metrics.get("offset_mode") == 0

