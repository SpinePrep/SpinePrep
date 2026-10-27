from spineprep.lib.run import only_subjects

RUNS = [{"subject": "01"}, {"subject": "sub-02"}, {"subject": "03"}]


def test_unset_keeps_all(monkeypatch):
    monkeypatch.delenv("SPINEPREP_ONLY_SUBJECTS", raising=False)
    assert only_subjects(RUNS) == RUNS


def test_filter_accepts_both_label_forms(monkeypatch):
    monkeypatch.setenv("SPINEPREP_ONLY_SUBJECTS", "sub-01, 02")
    assert [r["subject"] for r in only_subjects(RUNS)] == ["01", "sub-02"]


def test_unknown_subject_keeps_none(monkeypatch):
    monkeypatch.setenv("SPINEPREP_ONLY_SUBJECTS", "99")
    assert only_subjects(RUNS) == []
