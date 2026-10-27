from spineprep.steps.s7.process import _anat_link_warps


def test_unset_means_no_link(monkeypatch):
    monkeypatch.delenv("SPINEPREP_T2LINK_ROOT", raising=False)
    assert _anat_link_warps("01") is None


def test_link_found_for_subject(tmp_path, monkeypatch):
    d = tmp_path / "sub-01"
    d.mkdir()
    for n in ("warp_T2star_to_T2w.nii.gz", "warp_T2w_to_T2star.nii.gz"):
        (d / n).write_bytes(b"x")
    monkeypatch.setenv("SPINEPREP_T2LINK_ROOT", str(tmp_path))
    fwd, inv = _anat_link_warps("01")
    assert fwd.name == "warp_T2star_to_T2w.nii.gz" and inv.name == "warp_T2w_to_T2star.nii.gz"


def test_other_subject_or_half_pair_gets_no_link(tmp_path, monkeypatch):
    d = tmp_path / "sub-01"
    d.mkdir()
    (d / "warp_T2star_to_T2w.nii.gz").write_bytes(b"x")
    monkeypatch.setenv("SPINEPREP_T2LINK_ROOT", str(tmp_path))
    assert _anat_link_warps("01") is None
    assert _anat_link_warps("02") is None
