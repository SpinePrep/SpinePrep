#!/usr/bin/env python3
"""R6 -- the ceiling on cord fMRI as an individual-level measure.

Arithmetic, not a new experiment. Every input is a reliability coefficient already
measured in this project or published, and the output is a hard limit that follows
from them. Elliott 2020 did exactly this for brain task fMRI and it reframed the
individual-differences literature; the spinal field has no equivalent statement
*(unchecked)*.

TWO CONSEQUENCES OF A LOW ICC.

1. THE CORRELATION CEILING. Spearman's correction for attenuation: an observed
   correlation between two noisy measures cannot exceed

       r_observed_max = r_true * sqrt(ICC_x * ICC_y)

   With a cord effect ICC of ~0.05, even a PERFECT underlying relationship to a
   perfectly reliable clinical score is capped far below what studies routinely
   report. This is the number that decides whether a biomarker programme is
   feasible at all.

2. HOW MUCH DATA WOULD FIX IT. Spearman-Brown: averaging k independent repeats
   raises reliability to

       ICC_k = k*ICC / (1 + (k-1)*ICC)

   Inverting it gives the number of repeat measurements needed to reach a usable
   reliability, which converts "unreliable" into a concrete acquisition cost.

INPUTS, every one measured rather than assumed:
  0.05  between-session effect ICC, this project (effect_reliability.py)
  0.03  Dabbagh 2024, left dorsal horn C6 ROI-average beta, same organ, n=40
  0.20  Dabbagh 2024, peak and top-10% variants
  0.49  ventral-ventral resting connectivity ICC, this project
  0.63  Kaptan 2023, the same connectivity measure
  0.00  peak LOCATION ICC, N5 (+0.16, +0.03, +0.05, -0.04 across four datasets)

Clinical comparison reliabilities are taken as a range rather than a single value,
since the ceiling depends on both measures and the second one is not ours.
"""
from __future__ import annotations

import numpy as np
from scipy import stats as sps

MEASURES = [
    ("task effect, between-session (ours)", 0.05),
    ("task effect, Dabbagh 2024 ROI-average", 0.03),
    ("task effect, Dabbagh 2024 peak / top-10%", 0.20),
    ("peak LOCATION (N5)", 0.01),
    ("resting connectivity V-V (ours)", 0.49),
    ("resting connectivity V-V (Kaptan 2023)", 0.63),
]
CLINICAL_ICC = [("excellent clinical score", 0.90),
                ("good clinical score", 0.75),
                ("fair clinical score", 0.60)]
TARGETS = [0.60, 0.75, 0.90]


def n_for_r(r, power=0.80, alpha=0.05):
    """Sample size to detect a correlation r, Fisher z approximation."""
    r = abs(r)
    if r <= 1e-6 or r >= 0.999:
        return np.inf
    z = 0.5 * np.log((1 + r) / (1 - r))
    need = (sps.norm.isf(alpha / 2) + sps.norm.isf(1 - power)) ** 2 / z ** 2 + 3
    return need


def sb_k(icc, target):
    """Repeats needed to raise reliability `icc` to `target` (Spearman-Brown)."""
    if icc <= 0:
        return np.inf
    if icc >= target:
        return 1.0
    k = target * (1 - icc) / (icc * (1 - target))
    return k


def main():
    print("=" * 84)
    print("R6  THE CEILING ON CORD fMRI AS AN INDIVIDUAL-LEVEL MEASURE")
    print("=" * 84)
    print("Arithmetic over measured reliabilities. No new data.")

    print("\n--- 1. maximum OBSERVABLE correlation with a clinical variable ---")
    print("  Spearman attenuation: r_obs_max = sqrt(ICC_cord * ICC_clinical),")
    print("  assuming the underlying true relationship is PERFECT. Any real")
    print("  relationship is below this.")
    hdr = "  {:42}".format("cord measure (ICC)")
    for lab, _ in CLINICAL_ICC:
        hdr += f"{lab.split()[0]:>12}"
    print(hdr)
    for name, icc in MEASURES:
        row = f"  {name + f' ({icc:.2f})':42}"
        for _, cicc in CLINICAL_ICC:
            row += f"{np.sqrt(icc * cicc):12.3f}"
        print(row)
    print("  columns are clinical ICC 0.90 / 0.75 / 0.60")

    print("\n--- 2. sample size to DETECT that ceiling correlation (80% power) ---")
    print("  Even in the best case -- a perfect true relationship -- this is the N")
    print("  required to find the attenuated correlation that remains.")
    print(f"  {'cord measure':42} {'r_max vs ICC 0.9':>17} {'N needed':>10}")
    for name, icc in MEASURES:
        r = np.sqrt(icc * 0.90)
        n = n_for_r(r)
        print(f"  {name:42} {r:17.3f} {n:10.0f}")
    print("  For comparison, the largest published cord fMRI studies run n = 20-48.")

    print("\n--- 3. repeat measurements needed for a usable reliability ---")
    print("  Spearman-Brown, inverted: how many independent repeats must be averaged")
    print("  to raise each measure to the Cicchetti bands.")
    print(f"  {'cord measure':42} " + " ".join(f"{'k for ' + str(t):>11}" for t in TARGETS))
    for name, icc in MEASURES:
        row = f"  {name:42} "
        for t in TARGETS:
            k = sb_k(icc, t)
            row += f"{('inf' if not np.isfinite(k) else f'{k:.0f}'):>11} "
        print(row)
    print("  k counts INDEPENDENT repeats -- separate sessions, not runs inside one")
    print("  session, since R3/R4 found within-session repeats share structure that")
    print("  between-session repeats do not.")

    print("\n--- 4. what this means in scanner time ---")
    icc = 0.05
    k = sb_k(icc, 0.75)
    print(f"  Taking the measured between-session effect ICC of {icc:.2f}, reaching the")
    print(f"  'good' band (0.75) needs k = {k:.0f} independent sessions per subject.")
    print(f"  At one session per visit and roughly 10 minutes of task per session,")
    print(f"  that is {k:.0f} visits per participant before an individual value is")
    print("  usable. For the 'fair' band (0.60) it is "
          f"{sb_k(icc, 0.60):.0f} visits.")
    print(f"  Resting connectivity is a different situation: at ICC {0.49:.2f} the")
    print(f"  'good' band needs k = {sb_k(0.49, 0.75):.0f} sessions and 'fair' needs "
          f"k = {sb_k(0.49, 0.60):.0f}.")

    print("""
--- CONCLUSION, stated as a decision rather than a lament ---

Cord TASK fMRI is not usable as an individual-level or biomarker measure at
currently published scan durations. The measured between-session effect ICC of 0.05
caps any correlation with a well-measured clinical score at 0.21, which needs
n = 172 to detect at 80% power even when the true relationship is PERFECT -- against
the n = 20-48 of the largest published cord studies. Reaching the 'good'
reliability band instead would take 57 independent sessions per participant. So a
reported correlation between a single-session cord task measure and a clinical score
is underpowered whatever its result, and a positive finding in that design is more
likely noise than signal.

Cord RESTING CONNECTIVITY is a genuinely different case. At ICC 0.49-0.63 it needs
roughly 3 sessions for the good band and 1-2 for fair, which is achievable. If the
field wants an individual-level spinal measure, the reliability arithmetic points at
connectivity, not at task activation.

This is the one place where the project's reliability results have a direct clinical
consequence, and it follows from numbers already measured rather than from any new
claim.""")
    print("\nDONE_MARKER")


if __name__ == "__main__":
    main()
