"""S1 must report subjects the policy subset drops.

The subset filter removes a subject's files before they enter the inventory, so
an excluded subject left NO trace: S1 reported n_runs_ok == n_runs_total and
"0 issues" while a complete subject sat unprocessed on disk. Measured on the
cohort, 5 subjects were dropped this way with nothing reported (ds004616
sub-04/sub-05, ds005075 sub-P030, ds005883 sub-22, ds005884 sub-22) -- sub-22
apparently via a copy-paste artifact in policy/datasets.yaml rather than a
decision. Whether an exclusion is deliberate is the operator's call; being
silent about it is not.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.steps.s1.inventory import _build_inventory
from spineprep.steps.s1.validate import _apply_selection_check


def _dataset(tmp_path, subjects):
    for s in subjects:
        d = tmp_path / f"sub-{s}" / "func"
        d.mkdir(parents=True)
        (d / f"sub-{s}_task-rest_bold.nii.gz").write_bytes(b"")
        (d / f"sub-{s}_task-rest_bold.json").write_text("{}")
    return tmp_path


def _entry(subjects):
    return SimpleNamespace(
        selection=SimpleNamespace(mode="subset", subjects=subjects, sessions=[])
    )


def test_inventory_records_excluded_subjects(tmp_path):
    root = _dataset(tmp_path, ["01", "02", "22"])
    inv = _build_inventory(root, "ds", _entry(["01", "02"]))   # '22' omitted
    sel = inv["selection"]
    assert sel["n_subjects_on_disk"] == 3
    assert sel["n_subjects_selected"] == 2
    assert sel["subjects_excluded"] == ["22"]


def test_no_selection_means_nothing_excluded(tmp_path):
    root = _dataset(tmp_path, ["01", "02"])
    inv = _build_inventory(root, "ds", None)
    assert inv["selection"]["subjects_excluded"] == []
    assert inv["selection"]["n_subjects_selected"] == 2


def test_excluded_subject_raises_a_visible_warn(tmp_path):
    root = _dataset(tmp_path, ["01", "22"])
    inv = _build_inventory(root, "ds", _entry(["01"]))
    checks, issues = [], []
    _apply_selection_check(inv, checks, issues)
    assert len(issues) == 1 and issues[0]["severity"] == "WARN"
    assert "sub-22" in issues[0]["message"]
    c = [c for c in checks if c["name"] == "policy_selection_covers_disk"][0]
    assert c["passed"] is False


def test_full_coverage_passes_the_check(tmp_path):
    root = _dataset(tmp_path, ["01", "02"])
    inv = _build_inventory(root, "ds", _entry(["01", "02"]))
    checks, issues = [], []
    _apply_selection_check(inv, checks, issues)
    assert issues == []
    assert [c for c in checks if c["name"] == "policy_selection_covers_disk"][0]["passed"] is True


def test_zs_normalisation_still_selects(tmp_path):
    """'ZS001' in the list selects sub-01 -- the real cohort relies on this."""
    root = _dataset(tmp_path, ["01"])
    inv = _build_inventory(root, "ds", _entry(["ZS001"]))
    assert inv["selection"]["subjects_excluded"] == []
