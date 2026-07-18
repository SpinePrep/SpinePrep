"""Reference analysis (decision 3B): a non-canonical demonstration.

It must (a) NOT be part of the validated pipeline, (b) apply the confounds in one
simultaneous regression, (c) produce a per-level connectivity matrix from the
native-space derivatives, and (d) stamp every output as a demonstration.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pandas as pd
import nibabel as nib

from spineprep.reference_analysis import (
    run_reference_analysis, _confound_design, _residualize, BANNER,
)


def test_reference_analysis_is_not_in_participant_steps():
    """3B guardrail: the demonstration must never run in a normal participant call."""
    from spineprep.bids_app import PARTICIPANT_STEPS, GROUP_STEP
    joined = " ".join(PARTICIPANT_STEPS) + " " + GROUP_STEP
    assert "reference" not in joined.lower()


def test_confound_design_drops_constant_and_adds_intercept(tmp_path):
    tsv = tmp_path / "c.tsv"
    pd.DataFrame({
        "trans_x": [0.1, 0.2, -0.1, 0.0, 0.3],
        "const_col": [1.0, 1.0, 1.0, 1.0, 1.0],   # must be dropped
        "csf_pc0": [0.5, -0.5, 0.2, -0.2, 0.1],
        "deriv1": [np.nan, 0.1, -0.1, 0.0, 0.2],   # NaN imputed, not dropped
    }).to_csv(tsv, sep="\t", index=False)
    X, names = _confound_design(tsv)
    assert names[0] == "intercept"
    assert "const_col" not in names          # constant dropped
    assert "trans_x" in names and "csf_pc0" in names and "deriv1" in names
    assert not np.isnan(X).any()             # NaNs imputed


def test_residualize_removes_confound_variance():
    """A voxel time-course that IS a confound must residualize to ~zero."""
    rng = np.random.default_rng(0)
    T = 60
    conf = rng.normal(0, 1, T)
    X = np.column_stack([np.ones(T), conf])
    bold = np.zeros((2, 2, 1, T))
    bold[0, 0, 0, :] = 3.0 * conf + 5.0      # pure confound + offset
    bold[1, 1, 0, :] = rng.normal(0, 1, T)   # unrelated
    mask = np.zeros((2, 2, 1), dtype=bool); mask[0, 0, 0] = True
    resid = _residualize(bold, mask, X)
    assert np.abs(resid).max() < 1e-9        # the confound voxel is fully removed


def test_end_to_end_writes_stamped_connectivity(tmp_path):
    rng = np.random.default_rng(1)
    sub = "sub-01"; run_id = "sub-01_task-rest"
    func = tmp_path / "derivatives" / "spineprep" / sub / "func"
    func.mkdir(parents=True)
    T, nx, ny, nz = 80, 6, 6, 4
    aff = np.eye(4)
    # BOLD: two levels with distinct shared signals so correlation is non-trivial
    bold = rng.normal(0, 0.3, (nx, ny, nz, T))
    sA, sB = rng.normal(0, 1, T), rng.normal(0, 1, T)
    levels = np.zeros((nx, ny, nz), dtype=np.int32)
    levels[1:3, 1:3, :2] = 3; bold[1:3, 1:3, :2] += sA
    levels[3:5, 3:5, 2:] = 5; bold[3:5, 3:5, 2:] += sB
    nib.save(nib.Nifti1Image(bold.astype(np.float32), aff), func / f"{run_id}_desc-preproc_bold.nii.gz")
    nib.save(nib.Nifti1Image(levels, aff), func / f"{run_id}_desc-PAM50spinallevels.nii.gz")
    nib.save(nib.Nifti1Image((levels > 0).astype(np.uint8), aff), func / f"{run_id}_desc-PAM50cord_mask.nii.gz")
    pd.DataFrame({"trans_x": rng.normal(0, 0.1, T), "csf_pc0": rng.normal(0, 0.1, T)}
                 ).to_csv(func / f"{run_id}_desc-confounds_timeseries.tsv", sep="\t", index=False)

    res = run_reference_analysis(tmp_path, run_id, "01")
    assert res["status"] == "OK", res
    assert res["banner"] == BANNER
    assert res["n_levels"] == 2
    # matrix written + provenance stamped
    mtx = tmp_path / res["outputs"]["matrix_tsv"]
    assert mtx.exists()
    m = pd.read_csv(mtx, sep="\t", index_col=0)
    assert m.shape == (2, 2)
    assert abs(m.iloc[0, 0] - 1.0) < 1e-9    # diagonal is self-correlation
    prov = json.loads((tmp_path / res["outputs"]["provenance"]).read_text())
    assert prov["banner"] == BANNER
    assert "not validated" in prov["banner"]
    assert "group stats" in prov["note"]


def test_missing_inputs_skip_not_crash(tmp_path):
    res = run_reference_analysis(tmp_path, "sub-01_task-rest", "01")
    assert res["status"] == "SKIP"
    assert "missing inputs" in res["reason"]


# ---------------------------------------------------------------------------
# Slicewise confound selection
#
# The S8 table is built for a slicewise GLM. Regressing every column at once
# uses a median 139 regressors against 227 frames on the reference cohort, with
# 8.7% of runs having more regressors than frames. The demonstration must model
# the slicewise usage, not the flat one.
# ---------------------------------------------------------------------------


def test_confound_design_slicewise_keeps_only_that_slice(tmp_path):
    import pandas as pd
    import numpy as np
    from spineprep.reference_analysis import _confound_design
    n = 50
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "trans_x": rng.standard_normal(n),
        "cosine_00": rng.standard_normal(n),
        "csf_slice00_pc01": rng.standard_normal(n),
        "csf_slice01_pc01": rng.standard_normal(n),
        "csf_slice02_pc01": rng.standard_normal(n),
        "pnm_slice01_ev01": rng.standard_normal(n),
    })
    p = tmp_path / "c.tsv"
    df.to_csv(p, sep="\t", index=False)

    X, names = _confound_design(p, slice_index=1)
    assert "csf_slice01_pc01" in names
    assert "pnm_slice01_ev01" in names
    assert "csf_slice00_pc01" not in names
    assert "csf_slice02_pc01" not in names
    # global regressors always survive
    assert "trans_x" in names and "cosine_00" in names
    assert X.shape == (n, len(names))


def test_confound_design_flat_keeps_everything(tmp_path):
    import pandas as pd
    import numpy as np
    from spineprep.reference_analysis import _confound_design
    n = 50
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "trans_x": rng.standard_normal(n),
        "csf_slice00_pc01": rng.standard_normal(n),
        "csf_slice01_pc01": rng.standard_normal(n),
    })
    p = tmp_path / "c.tsv"
    df.to_csv(p, sep="\t", index=False)
    _, names = _confound_design(p)
    assert "csf_slice00_pc01" in names and "csf_slice01_pc01" in names


def test_confound_design_slicewise_is_narrower_than_flat(tmp_path):
    """The whole point: slicewise uses fewer degrees of freedom."""
    import pandas as pd
    import numpy as np
    from spineprep.reference_analysis import _confound_design
    n = 60
    rng = np.random.default_rng(2)
    cols = {"trans_x": rng.standard_normal(n)}
    for z in range(20):
        for pc in range(5):
            cols[f"csf_slice{z:02d}_pc{pc:02d}"] = rng.standard_normal(n)
    p = tmp_path / "c.tsv"
    pd.DataFrame(cols).to_csv(p, sep="\t", index=False)
    flat, _ = _confound_design(p)
    sw, _ = _confound_design(p, slice_index=3)
    assert sw.shape[1] < flat.shape[1]
    assert flat.shape[1] > n      # flat is wider than the run is long
    assert sw.shape[1] < n        # slicewise is not
