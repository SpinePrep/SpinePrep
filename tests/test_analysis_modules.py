"""Unit tests for the analysis endpoint modules built on top of the GLM.

Covers the load-bearing logic: laterality direction, the group aggregations, the
biological-validity guardrails (single-subject laterality vs group-only horn),
confound-family selection and benefit-per-DOF, and the distortion falsification
statistic. Heavy GLM/NIfTI paths are exercised in the driver integration test,
not here; these tests pin the math.
"""
import numpy as np
import pytest

from analysis import effects, biological_validity as bv
from analysis import confound_benchmark as cb
from analysis import distortion as dist


# --------------------------------------------------------------------------
# effects
# --------------------------------------------------------------------------

def test_condition_side_mapping():
    assert effects._condition_side("left") == "L"
    assert effects._condition_side("Right") == "R"
    assert effects._condition_side("motorL") == "L"
    assert effects._condition_side("heat") is None


def test_group_effects_cohens_d_and_detection():
    # 4 subjects, one effect_t row each in the same parcel/condition
    rows = [{"dataset": "D", "subject": f"s{i}", "session": None, "run_id": "r",
             "mask_source": "PAM50_warped", "tier": "cord", "parcel": "cord",
             "metric": "effect_t", "value": v, "condition": "heat", "n": 400}
            for i, v in enumerate([2.5, 3.0, 3.5, 4.0])]  # positive, real variance
    out = effects.group_effects(rows, t_threshold=2.0)
    d = next(r for r in out if r["metric"] == "effect_d")
    det = next(r for r in out if r["metric"] == "detect_frac")
    assert d["value"] > 2           # mean 3.25, sd ~0.65 -> d ~5
    assert det["value"] == 1.0      # all 4 exceed threshold 2.0
    assert d["n"] == 4


# --------------------------------------------------------------------------
# biological validity
# --------------------------------------------------------------------------

def test_laterality_recovery_single_subject_fraction():
    rows = [{"dataset": "D", "subject": f"s{i}", "session": None, "run_id": "r",
             "mask_source": "PAM50_warped", "tier": "hemicord", "parcel": "ipsi-R",
             "metric": "laterality_index", "value": v, "condition": "right", "n": 40}
            for i, v in enumerate([0.3, 0.2, 0.1, -0.1, 0.05])]
    out = bv.laterality_recovery(rows)
    assert len(out) == 1
    assert out[0]["metric"] == "laterality_ipsi_frac"
    assert out[0]["value"] == pytest.approx(0.8)     # 4 of 5 ipsi-dominant
    assert out[0]["level"] == "single-subject"


def test_dorsal_ventral_needs_a_group():
    # only 2 subjects -> below the group floor -> no horn row emitted
    rows = []
    for i in range(2):
        for parcel, val in (("gm-dorsal-L", 3.0), ("gm-ventral-L", 1.0)):
            rows.append({"dataset": "openneuro_ds004926_dorsalhorn_pain",
                         "subject": f"s{i}", "session": None, "run_id": "r",
                         "mask_source": "PAM50_warped", "tier": "gmhorn",
                         "parcel": parcel, "metric": "effect_t", "value": val,
                         "condition": "heat", "n": 8})
    assert bv.dorsal_ventral_recovery(rows) == []


def test_dorsal_ventral_group_dissociation():
    rows = []
    # 4 subjects, dorsal > ventral (pain); real variance so Cohen's d is defined
    for i, (dorsal, ventral) in enumerate([(3.0, 1.0), (3.5, 1.2),
                                           (2.8, 0.9), (3.2, 1.1)]):
        for parcel, val in (("gm-dorsal-L", dorsal), ("gm-ventral-L", ventral)):
            rows.append({"dataset": "openneuro_ds004926_dorsalhorn_pain",
                         "subject": f"s{i}", "session": None, "run_id": "r",
                         "mask_source": "PAM50_warped", "tier": "gmhorn",
                         "parcel": parcel, "metric": "effect_t", "value": val,
                         "condition": "heat", "n": 8})
    out = bv.dorsal_ventral_recovery(rows)
    d = next(r for r in out if r["metric"] == "horn_dissociation_d")
    frac = next(r for r in out if r["metric"] == "horn_expected_frac")
    assert d["value"] > 0            # expected horn (dorsal) stronger
    assert frac["value"] == 1.0
    assert d["level"] == "group"


def test_painmotor_both_is_skipped_not_misreported():
    rows = [{"dataset": "internal_balgrist_painmotor_21", "subject": f"s{i}",
             "session": None, "run_id": "r", "mask_source": "PAM50_warped",
             "tier": "gmhorn", "parcel": "gm-dorsal-L", "metric": "effect_t",
             "value": 2.0, "condition": "mixed", "n": 8} for i in range(4)]
    assert bv.dorsal_ventral_recovery(rows) == []   # 'both' -> no overall claim


# --------------------------------------------------------------------------
# confound benchmark
# --------------------------------------------------------------------------

def test_family_builder_selects_columns(tmp_path):
    tsv = tmp_path / "conf.tsv"
    tsv.write_text(
        "trans_x\trot_z\tcosine00\tcsf_slice00_pc01\tretroicor_ev01\tmotion_outlier00\n"
        + "\n".join("\t".join("0.1" if k % 6 else "0" for k in range(row * 6, row * 6 + 6))
                    for row in range(5)) + "\n")
    n = 5
    X, names = cb.family_builder(("motion",))(tsv, n)
    assert all(nm.startswith(("trans_", "rot_")) for nm in names)
    X2, names2 = cb.family_builder(("csf", "retroicor"))(tsv, n)
    assert all(nm.startswith(("csf_", "retroicor")) for nm in names2)


def test_family_builder_drops_zero_variance(tmp_path):
    tsv = tmp_path / "c.tsv"
    tsv.write_text("trans_x\ttrans_y\n" + "\n".join("1.0\t0.0" for _ in range(4)) + "\n")
    # trans_x is constant 1.0 (zero variance), trans_y constant 0.0 -> both dropped
    X, names = cb.family_builder(("motion",))(tsv, 4)
    assert names == []


# --------------------------------------------------------------------------
# distortion falsification statistic
# --------------------------------------------------------------------------

def _metrics(before, after):
    z = list(range(len(before)))
    return {"per_slice_z": z, "displacement_before_mm": before,
            "displacement_after_mm": after}

def test_distortion_identity_fidelity_is_one():
    before = [2.0, 3.0, 1.5, 2.5]
    after = [0.5, 0.6, 0.4, 0.7]
    m = _metrics(before, after)
    r = dist.compare_run(m, m, "run", "ds")
    assert r["syn_fidelity"] == pytest.approx(1.0)

def test_distortion_half_correction_fidelity_is_half():
    before = np.array([2.0, 3.0, 1.5, 2.5])
    after = np.array([0.5, 0.6, 0.4, 0.7])
    half = (before - 0.5 * (before - after)).tolist()
    r = dist.compare_run(_metrics(before.tolist(), after.tolist()),
                         _metrics(before.tolist(), half), "run", "ds")
    assert r["syn_fidelity"] == pytest.approx(0.5, abs=0.02)

def test_distortion_worsened_frac_counts_pushed_slices():
    before = [1.0, 1.0, 1.0, 1.0]
    topup = [0.2, 0.2, 0.2, 0.2]
    syn = [2.0, 2.0, 0.5, 0.5]        # 2 of 4 slices pushed further than before
    r = dist.compare_run(_metrics(before, topup), _metrics(before, syn), "run", "ds")
    assert r["worsened_frac"] == pytest.approx(0.5)

def test_distortion_non_finite_slices_skipped():
    before = [1.0, float("nan"), 1.0]
    topup = [0.2, 0.2, 0.2]
    syn = [0.5, 0.5, 0.5]
    r = dist.compare_run(_metrics(before, topup), _metrics(before, syn), "run", "ds")
    assert r["n_slices"] == 2         # the nan slice dropped
