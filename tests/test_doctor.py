from __future__ import annotations
import json
from pathlib import Path
from spineprep.doctor import build_report, save_report
import jsonschema

SCHEMA = json.loads(Path("schemas/doctor.schema.json").read_text())

def test_report_shape_pass(tmp_path: Path, monkeypatch):
    # fake SCT + PAM50 present
    monkeypatch.setenv("PATH", "/bin")  # will still fail, so we patch functions instead
    from spineprep import doctor as d
    monkeypatch.setattr(d, "detect_sct", lambda: d.DepStatus(found=True, version="6.0", path="/usr/bin/sct_version"))
    monkeypatch.setattr(d, "detect_pam50", lambda explicit: d.DepStatus(found=True, path="/opt/PAM50", files_ok=True))
    monkeypatch.setattr(d, "detect_python_deps", lambda: {"numpy":"1.26.0"})

    rep = build_report(None)
    assert rep["status"] in {"pass","warn","fail"}
    jsonschema.validate(rep, SCHEMA)
    art = save_report(rep, tmp_path, None)
    assert art.exists()

def test_fail_on_missing_sct_and_pam50(monkeypatch):
    from spineprep import doctor as d
    monkeypatch.setattr(d, "detect_sct", lambda: d.DepStatus(found=False))
    monkeypatch.setattr(d, "detect_pam50", lambda explicit: d.DepStatus(found=False, files_ok=False))
    rep = build_report(None)
    assert rep["status"] == "fail"
    assert any("SCT not found" in n for n in rep["notes"])

