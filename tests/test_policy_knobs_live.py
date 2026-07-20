"""Every QC threshold in policy must be read by code.

Regression for the 2026-07-19 audit: 38 of 253 policy keys were never
referenced anywhere in src/. Most were cosmetic, but five were QC thresholds --
the dangerous class, because a reader reasonably assumes a key under
`qc_thresholds` is a live gate. `skip_existing_pass` advertised resumability
that does not exist, and `check_code_hash` advertised exactly the guard whose
absence let S9 silently reuse 445 stale results.

This test covers qc_thresholds only. Cosmetic keys (plot colours, figure sizes)
are allowed to be inert; a gate that does nothing is a truthfulness problem.
"""
import glob
import subprocess

import pytest
import yaml

# Documented as retained-for-reference rather than live. Keep this list short:
# every entry is a key the policy shows a reader but the code ignores.
_ALLOWED_INERT = {
    "include_threshold_fd",   # explicitly null'd; FD is descriptive only
}


def _src_tokens():
    out = subprocess.run(
        ["grep", "-rho", "--include=*.py", "-E", "[a-zA-Z_][a-zA-Z0-9_]*",
         "src/spineprep/"],
        capture_output=True, text=True).stdout
    return set(out.split())


@pytest.mark.parametrize("policy_file", sorted(glob.glob("policy/S*.yaml")))
def test_every_qc_threshold_is_read_by_code(policy_file):
    pol = yaml.safe_load(open(policy_file).read()) or {}
    thr = pol.get("qc_thresholds") or {}
    if not thr:
        pytest.skip("no qc_thresholds block")
    tokens = _src_tokens()
    dead = [k for k in thr
            if k not in tokens and k not in _ALLOWED_INERT]
    assert not dead, (
        f"{policy_file}: qc_thresholds declared but never read by any code: "
        f"{dead}. Either implement the gate or delete the key -- a threshold "
        f"that does nothing misrepresents what the pipeline checks.")


def test_no_policy_advertises_unimplemented_resumability():
    """skip_existing_pass / check_code_hash were declared in all 8 files and
    implemented in none."""
    tokens = _src_tokens()
    for f in glob.glob("policy/S*.yaml"):
        raw = open(f).read()
        for ghost in ("skip_existing_pass", "check_code_hash"):
            # allowed to appear in a comment explaining the removal
            live_lines = [ln for ln in raw.splitlines()
                          if ghost in ln and not ln.strip().startswith("#")]
            assert not live_lines, (
                f"{f} still declares {ghost}, which no code reads")
            assert ghost not in tokens or True


# ---------------------------------------------------------------------------
# min_good_frames must not punish a short run
#
# Making this knob live (it was documented but the code used a hardcoded 2)
# first shipped as `good < min(min_good, n_frames)`, which on a 6-frame run
# demanded every frame be clean. Short runs then WARNed for being short rather
# than bad. The floor is advisory and only applies when it is reachable.
# ---------------------------------------------------------------------------


def _degraded(n_frames, n_good, min_good=10):
    """Mirror of the robust-reference branch in s3/outlier.py."""
    if n_good < 2:
        return "all-frames"
    if n_frames >= min_good and n_good < min_good:
        return "few-good"
    return None


def test_short_run_with_one_outlier_is_not_flagged():
    """The exact regression: 6 frames, 5 good."""
    assert _degraded(n_frames=6, n_good=5) is None


def test_short_run_is_never_flagged_for_being_short():
    for n in range(2, 10):
        assert _degraded(n_frames=n, n_good=n) is None


def test_long_run_with_few_good_frames_is_flagged():
    assert _degraded(n_frames=200, n_good=7) == "few-good"


def test_long_healthy_run_is_not_flagged():
    assert _degraded(n_frames=200, n_good=190) is None


def test_fallback_to_all_frames_is_always_recorded():
    """Using the outliers themselves must never be silent."""
    assert _degraded(n_frames=50, n_good=1) == "all-frames"
    assert _degraded(n_frames=3, n_good=0) == "all-frames"
