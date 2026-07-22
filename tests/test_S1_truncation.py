"""S1 must detect a truncated or partially-downloaded image.

Regression for the 2026-07-19 audit: every S1 check read only the NIfTI HEADER,
which a truncated file preserves intact because it sits at the front of the
file. A half-downloaded scan therefore passed input verification as clean and
only surfaced later as a gzip EOFError inside S3. The known-truncated sub-22 in
ds005883 passed S1 with no issues at all.

Both checks are O(1): the .nii branch compares file size against the size the
header implies; the .nii.gz branch reads ISIZE from the 4-byte gzip trailer.
Decompressing a 292 MB cohort file to verify it would be correct but far too
slow to run over a whole dataset.
"""
import numpy as np
import nibabel as nib
import pytest

from spineprep.steps.s1.validate import _validate_nifti


def _write(tmp_path, name, shape=(12, 12, 8, 20)):
    d = (np.random.rand(*shape) * 500).astype(np.float32)
    p = tmp_path / name
    nib.save(nib.Nifti1Image(d, np.eye(4)), p)
    return p


def _truncate(p, frac):
    n = int(p.stat().st_size * frac)
    head = p.read_bytes()[:n]
    p.write_bytes(head)
    return p


def _truncation_issues(issues):
    return [i for i in issues if "runcated" in i["message"] or "corrupt" in i["message"]]


@pytest.mark.parametrize("frac", [0.1, 0.4, 0.75, 0.99])
def test_truncated_gz_is_failed(tmp_path, frac):
    p = _truncate(_write(tmp_path, "sub-01_task-x_bold.nii.gz"), frac)
    hits = _truncation_issues(_validate_nifti(p, expect_4d=True))
    assert hits, f"truncation at {frac:.0%} not detected"
    assert hits[0]["severity"] == "FAIL"


@pytest.mark.parametrize("frac", [0.25, 0.5, 0.9])
def test_truncated_plain_nii_is_failed(tmp_path, frac):
    p = _truncate(_write(tmp_path, "sub-01_task-x_bold.nii"), frac)
    hits = _truncation_issues(_validate_nifti(p, expect_4d=True))
    assert hits, f"truncation at {frac:.0%} not detected"
    assert hits[0]["severity"] == "FAIL"


def test_intact_gz_is_clean(tmp_path):
    """No false positive -- verified across 400 real cohort files."""
    p = _write(tmp_path, "sub-01_task-x_bold.nii.gz")
    assert _truncation_issues(_validate_nifti(p, expect_4d=True)) == []


def test_intact_plain_nii_is_clean(tmp_path):
    p = _write(tmp_path, "sub-01_task-x_bold.nii")
    assert _truncation_issues(_validate_nifti(p, expect_4d=True)) == []


def test_intact_3d_anat_is_clean(tmp_path):
    p = _write(tmp_path, "sub-01_T2w.nii.gz", shape=(16, 16, 12))
    assert _truncation_issues(_validate_nifti(p, expect_4d=False)) == []


def test_empty_file_is_failed(tmp_path):
    p = _write(tmp_path, "sub-01_task-x_bold.nii.gz")
    p.write_bytes(b"")
    issues = _validate_nifti(p, expect_4d=True)
    assert any(i["severity"] == "FAIL" for i in issues)


def test_check_is_cheap(tmp_path):
    """Must stay O(1); a full decompress would make S1 unusable on a cohort."""
    import time
    p = _write(tmp_path, "sub-01_task-x_bold.nii.gz", shape=(40, 40, 30, 60))
    t0 = time.time()
    for _ in range(20):
        _validate_nifti(p, expect_4d=True)
    assert (time.time() - t0) / 20 < 0.05


# ---------------------------------------------------------------------------
# Regression 2026-07-22: a COMPLETE file carrying a NIfTI header extension has
# an uncompressed size LARGER than header+voxels, because the extension sits
# between them. The trailer-vs-expected check counted only header+voxels, so
# isize > expected and the file was branded "truncated". This false-positived
# 46 complete motor runs (a 6 kB AFNI extension) and failed the whole dataset.
# ---------------------------------------------------------------------------


def _write_with_extension(tmp_path, name, ext_len=6139, shape=(12, 12, 8, 20)):
    d = (np.random.rand(*shape) * 500).astype(np.int16)
    img = nib.Nifti1Image(d, np.eye(4))
    img.header.extensions.append(nib.nifti1.Nifti1Extension(4, b"A" * ext_len))
    p = tmp_path / name
    nib.save(img, p)
    return p


def test_complete_file_with_header_extension_is_clean(tmp_path):
    p = _write_with_extension(tmp_path, "sub-01_task-x_bold.nii.gz")
    assert _truncation_issues(_validate_nifti(p, expect_4d=True)) == []


def test_truncated_file_with_extension_still_failed(tmp_path):
    # even with an extension, cutting the tail must still be caught
    p = _write_with_extension(tmp_path, "sub-01_task-x_bold.nii.gz")
    _truncate(p, 0.5)
    hits = _truncation_issues(_validate_nifti(p, expect_4d=True))
    assert hits and hits[0]["severity"] == "FAIL"


def test_failure_message_surfaces_run_level_reason():
    """A FAIL whose cause is a per-run issue (not a dataset check) must still
    report a reason -- an unexplained FAIL is itself a QC-honesty failure."""
    from spineprep.steps.s1.validate import _failure_message
    runs = [
        {"path": "sub-22/func/sub-22_task-pain_bold.nii.gz", "status": "FAIL",
         "issues": [{"severity": "FAIL", "message": "Truncated or corrupt NIfTI: ..."}]},
        {"path": "sub-01/func/sub-01_bold.nii.gz", "status": "PASS"},
    ]
    msg = _failure_message("FAIL", checks=[], issues=[], runs=runs)
    assert msg is not None
    assert "sub-22" in msg and "Truncated" in msg
