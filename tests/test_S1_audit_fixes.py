"""Regression tests for the S1 audit fixes (2026-07-14).

F2: any NIfTI under anat/ is anatomical (T2*/MEGRE/PSIR/MP2RAGE no longer dropped).
F3: acquisition-metadata pre-flight (RepetitionTime, fmap PE-dir/readout).
See .claude/specs/s1-algorithm-audit.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.steps.s1.inventory import _classify_path
from spineprep.steps.s1.validate import _apply_acquisition_metadata_checks


# --- F2: anat contrast recognition ------------------------------------------

def test_classify_recognizes_non_t1t2_anat():
    for name in (
        "sub-01/anat/sub-01_acq-MEGRE_run-01_echo-1_part-mag_T2star.nii.gz",
        "sub-01/anat/sub-01_T2starw.nii.gz",
        "sub-01/anat/sub-01_PSIR.nii.gz",
        "sub-01/anat/sub-01_UNIT1.nii.gz",
    ):
        mod, cls = _classify_path(Path(name))
        assert mod == "anat", f"{name} should classify as anat, got {mod}"


def test_classify_still_recognizes_t1t2_and_bold():
    assert _classify_path(Path("sub-01/anat/sub-01_T2w.nii.gz"))[0] == "anat"
    assert _classify_path(Path("sub-01/func/sub-01_task-rest_bold.nii.gz")) == ("func", "cord_likely")


# --- F3: acquisition-metadata checks ----------------------------------------

def test_tr_check_flags_missing_repetition_time():
    runs = {
        "a": {"modality": "func", "classification": "cord_likely", "acquisition": {}, "issues": []},
        "b": {"modality": "func", "classification": "cord_likely",
              "acquisition": {"RepetitionTime": 2.0}, "issues": []},
    }
    checks, issues = [], []
    _apply_acquisition_metadata_checks(runs, checks, issues)
    tr = next(c for c in checks if c["name"] == "bold_repetition_time_present")
    assert tr["passed"] is False
    assert any("RepetitionTime" in i["message"] for i in runs["a"]["issues"])
    assert runs["b"]["issues"] == []


def test_tr_check_passes_when_all_present():
    runs = {"a": {"modality": "func", "classification": "cord_likely",
                  "acquisition": {"RepetitionTime": 1.66}, "issues": []}}
    checks, issues = [], []
    _apply_acquisition_metadata_checks(runs, checks, issues)
    assert next(c for c in checks if c["name"] == "bold_repetition_time_present")["passed"] is True


def test_fmap_missing_pe_dir_flagged():
    runs = {"f": {"modality": "fmap", "classification": "non_cord_likely",
                  "acquisition": {"PhaseEncodingDirection": "j-"}, "issues": []}}
    checks, issues = [], []
    _apply_acquisition_metadata_checks(runs, checks, issues)
    assert any("TotalReadoutTime" in i["message"] for i in runs["f"]["issues"])
