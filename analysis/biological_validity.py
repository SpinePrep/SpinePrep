#!/usr/bin/env python3
"""Biological-validity endpoints: does the pipeline recover known cord anatomy?

ANALYSIS module -- not part of the preprocessing toolbox. Candidate C3.

Consumes the per-run effect rows from effects.run_effects and asks three
anatomically-grounded questions, each at the level the literature supports:

  laterality       unilateral limb -> IPSILATERAL hemicord. Strong and
                   single-subject reliable (Hemmerling 2023, Weber 2016), so
                   reported PER SUBJECT: fraction of subjects ipsi-dominant.

  dorsal/ventral   pain -> dorsal horn, motor -> ventral horn. Single-subject
                   ICC is 0.03-0.24 at 1x1x5 mm (Dabbagh 2024), so this is
                   reported GROUP LEVEL ONLY: the across-subject horn contrast,
                   never a per-subject claim.

The expected anatomy per dataset is declared, not inferred. Two named confounds
travel with the dorsal/ventral result in the manuscript, not here: draining-vein
signal biasing dorsal pain, and motor-to-dorsal reafferent leak.
"""
from __future__ import annotations

import collections
from typing import Optional

import numpy as np

from analysis.endpoints import record
from analysis import estimators as ES

# Declared expected anatomy per dataset. `laterality` = has sided limb
# conditions (ipsi test); `dorsal`/`ventral` = the horn the task should drive.
# Rest datasets and the vestibular set carry no task-anatomy claim.
EXPECTED = {
    "openneuro_ds004926_dorsalhorn_pain":   {"horn": "dorsal"},
    "openneuro_ds005883_cospine_pain":      {"horn": "dorsal"},
    "internal_balgrist_painmotor_21":       {"horn": "both"},   # within-subject
    "openneuro_ds004616_spinalcord_handgrasp_task": {"horn": "ventral", "laterality": True},
    "openneuro_ds005884_cospine_motor":     {"horn": "ventral", "laterality": True},
    "internal_balgrist_motor_11":           {"horn": "ventral"},
    # cospigvs (vestibular), ds004386 / ds005075 (rest): no horn claim.
}


def _horn_value(rows, dataset, subject, horn):
    """Per-subject mean effect_t across the two horns of a side-pair, over runs
    and conditions. Returns None if that subject has no horn rows."""
    keep = [r["value"] for r in rows
            if r["dataset"] == dataset and r["subject"] == subject
            and r["tier"] == "gmhorn" and r["metric"] == "effect_t"
            and r["parcel"] in (f"gm-{horn}-L", f"gm-{horn}-R")
            and r["value"] is not None]
    return float(np.mean(keep)) if keep else None


def laterality_recovery(effect_rows: list[dict]) -> list[dict]:
    """Per dataset: fraction of subjects whose sided conditions are
    ipsilateral-dominant (LI > 0). Single-subject level, as the literature allows."""
    out: list[dict] = []
    li = [r for r in effect_rows if r.get("metric") == "laterality_index"
          and r.get("value") is not None]
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in li:
        by[r["dataset"]][r["subject"]].append(r["value"])
    for ds in sorted(by):
        # one number per subject: mean LI across that subject's sided runs
        subj_li = {s: float(np.mean(v)) for s, v in by[ds].items()}
        frac = float(np.mean([v > 0 for v in subj_li.values()]))
        record(out, dataset=ds, subject=None, session=None, run_id=None,
               mask_source="PAM50_warped", tier="hemicord", parcel="ipsi",
               metric="laterality_ipsi_frac", value=frac, n=len(subj_li),
               level="single-subject")
    return out


def dorsal_ventral_recovery(effect_rows: list[dict]) -> list[dict]:
    """Per dataset, GROUP LEVEL: the across-subject contrast between the expected
    horn and the other horn. Emits the paired Cohen's d of (expected - other) and
    the fraction of subjects with the expected horn stronger. Never per subject."""
    out: list[dict] = []
    for ds, spec in EXPECTED.items():
        horn = spec.get("horn")
        # 'both' (painmotor) would need per-condition horn mapping (pain->dorsal,
        # motor->ventral within the same run); an overall dorsal-vs-ventral
        # contrast on a mixed task is not interpretable, so it is skipped here
        # rather than reported misleadingly.
        if horn in (None, "both"):
            pairs = []
        else:
            pairs = [(horn, "ventral" if horn == "dorsal" else "dorsal")]
        for expected_horn, other_horn in pairs:
            subs = {r["subject"] for r in effect_rows
                    if r["dataset"] == ds and r["tier"] == "gmhorn"}
            diffs, wins = [], []
            for s in subs:
                ev = _horn_value(effect_rows, ds, s, expected_horn)
                ov = _horn_value(effect_rows, ds, s, other_horn)
                if ev is None or ov is None:
                    continue
                diffs.append(ev - ov)
                wins.append(ev > ov)
            if len(diffs) < 3:                    # group claim needs a group
                continue
            d = ES.cohens_d(diffs)                # one-sample d of the difference
            record(out, dataset=ds, subject=None, session=None, run_id=None,
                   mask_source="PAM50_warped", tier="gmhorn",
                   parcel=f"{expected_horn}-vs-{other_horn}",
                   metric="horn_dissociation_d", value=d, n=len(diffs),
                   level="group")
            record(out, dataset=ds, subject=None, session=None, run_id=None,
                   mask_source="PAM50_warped", tier="gmhorn",
                   parcel=f"{expected_horn}-vs-{other_horn}",
                   metric="horn_expected_frac", value=float(np.mean(wins)),
                   n=len(wins), level="group")
    return out


def biological_validity(effect_rows: list[dict]) -> list[dict]:
    """Both dissociations, each at its supported level."""
    return laterality_recovery(effect_rows) + dorsal_ventral_recovery(effect_rows)
