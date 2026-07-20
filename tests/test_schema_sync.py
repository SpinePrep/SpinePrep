"""QC schemas must describe the output the steps actually write.

Regression for the 2026-07-19 audit: nothing in production validates any schema
(there is no check_S* call in bids_app.py; only S1 and S2 validate, and only in
the dev-only `spineprep check` path). Five schemas had drifted far enough to
reject real output:

  * S5's `mode` enum was ["topup","fugue","syn"] -- it rejected "none", the
    shipped fallback default emitted by 82% of the reference cohort, and listed
    "fugue", which is specified but never implemented.
  * S8's schema was missing all four metrics added on 2026-07-18.
  * S2's schema forbade WARN as a run status while the code assigns it.

These tests validate the schemas against the REAL cohort output when it is
present, and always check the drift cases above, so a schema and its step
cannot silently diverge again.
"""
import json
from pathlib import Path

import pytest

SCHEMA_DIR = Path("schemas")
COHORT = Path("/mnt/ssd1/spineprep_cohort_s2/logs")


def _schema(name):
    hits = list(SCHEMA_DIR.glob(f"qc_{name}*.json"))
    if not hits:
        pytest.skip(f"no schema for {name}")
    return json.loads(hits[0].read_text())


def _enums(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            out.append(node["enum"])
        for v in node.values():
            _enums(v, out)
    elif isinstance(node, list):
        for v in node:
            _enums(v, out)
    return out


def test_s5_schema_accepts_the_shipped_default_mode():
    """`none` is the fallback default; the schema used to reject it."""
    mode_enums = [e for e in _enums(_schema("S5")) if "topup" in e]
    assert mode_enums, "no mode enum found"
    for e in mode_enums:
        assert "none" in e, "schema rejects the shipped fallback mode"


def test_s5_schema_drops_unimplemented_fugue():
    for e in [e for e in _enums(_schema("S5")) if "topup" in e]:
        assert "fugue" not in e, "fugue is specified but not implemented"


@pytest.mark.parametrize("key", ["design_rank", "design_rank_deficit",
                                 "regressor_frame_ratio",
                                 "n_columns_dropped_degenerate"])
def test_s8_schema_knows_the_new_metrics(key):
    assert key in json.dumps(_schema("S8")), f"{key} missing from S8 schema"


def test_s2_schema_allows_warn():
    """The code assigns WARN in three places; the schema forbade it."""
    status_enums = [e for e in _enums(_schema("S2_anat"))
                    if "PASS" in e and "FAIL" in e]
    assert status_enums
    for e in status_enums:
        assert "WARN" in e


@pytest.mark.parametrize("step", [
    "S2_anat_cordref", "S4_func_motion_correction",
    "S5_func_distortion_correction", "S6_func_to_anat_registration",
    "S7_template_normalization", "S8_confounds",
    "S9_primary_functional_derivatives",
])
def test_real_cohort_output_validates_against_its_schema(step):
    """The strongest form of this check: validate what the pipeline wrote."""
    jsonschema = pytest.importorskip("jsonschema")
    hits = list(SCHEMA_DIR.glob(f"qc_{step}*.json"))
    if not hits:
        pytest.skip(f"no schema for {step}")
    schema = json.loads(hits[0].read_text())
    step_dir = COHORT / (step if (COHORT / step).exists()
                         else step.replace("S8_confounds",
                                           "S8_confounds_and_physio_regressors"))
    if not step_dir.exists():
        pytest.skip("reference cohort not present on this machine")
    qcs = sorted(step_dir.glob("*/qc.json"))
    if not qcs:
        pytest.skip("no qc.json in cohort")
    errors = []
    for qc in qcs[:3]:
        try:
            jsonschema.validate(json.loads(qc.read_text()), schema)
        except jsonschema.ValidationError as err:
            errors.append(f"{qc.parent.name}: {err.message[:140]}")
    assert not errors, "real output violates its schema:\n" + "\n".join(errors)
