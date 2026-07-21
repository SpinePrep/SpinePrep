#!/usr/bin/env python3
"""Machine-readable GLM specification for the SpinePrep cohort.

ANALYSIS module -- not part of the preprocessing toolbox, and deliberately
outside src/spineprep/. SpinePrep stops at GLM-ready derivatives; this encodes
what a correct first-level model needs, so the facts verified on 2026-07-21 are
applied by code rather than remembered.

Every entry below was checked against the data or an authoritative source. The
non-obvious ones, and why they matter:

TIMING
  Events are on the FULL-acquisition clock, including the dummy volumes S3
  removed. Proven two ways: by BIDS definition (onset is relative to the first
  volume of the file, and volumes were removed from the front), and by boundary
  evidence -- ds004616's last event lands on 600.0 s against a full acquisition
  of exactly 600.0 s. So `StartTime` must be subtracted from every onset. It is
  6.2-13.0 s for seven datasets and 0 for the two CoSpine ones; hardcoding a
  constant is wrong either way.

BASELINE
  cospigvs and ds004616 tile 100% of the run with modelled conditions, so
  including the `rest` regressor makes the design sum to a constant and collide
  with the intercept. Measured max VIF 23.3 and 25.2; with rest as the implicit
  baseline, 1.50 and 1.31. Dropping it is not a preference, it is required.

ds004616 ONSET OFFSET
  The grip-force traces shipped with the dataset show the actual grasp begins
  +2.5 s after the events.tsv onset and lasts 16.0 s, not 15.0 s -- measured
  across 384 blocks, IQR +2.35 to +2.64 s, force flat until then (not a ramp).
  Fitting the events as written correlates 0.86 with the timing-corrected
  regressor, so roughly a quarter of the sensitivity is lost. The dataset also
  ships the force trace, which the source paper used as its %MVC regressor.

CONDITIONS FROM FILENAME
  ds005884's events.tsv has no trial_type at all (its README wrongly claims one).
  The condition is the task entity: task-motorL / task-motorR, one per run.

EXCLUSIONS
  ds005883 sub-22 is truncated -- 60 MiB clean cut, corrupt gzip stream. It is
  the only truncated BOLD in 474 checked.
"""
from __future__ import annotations

from typing import Any, Optional

# --------------------------------------------------------------------------
# Per-dataset GLM specification
# --------------------------------------------------------------------------

SPEC: dict[str, dict[str, Any]] = {
    "internal_balgrist_cospigvs_11": {
        "task_conditions": ["hand", "gvs", "combined"],
        "implicit_baseline": "rest",          # REQUIRED: conditions tile the run
        "onset_shift_s": 0.0,
        "duration_override_s": None,
        "condition_from_filename": False,
        "exclude_runs": [],
        "hrf_tail_s": 2.6,                    # last block's response is truncated
        "notes": ("4 conditions x 5 blocks x 30 s = 600 s, exactly the run length. "
                  "Modelling `rest` gives max VIF 23.3; as implicit baseline, 1.50."),
        "verified": "events + VIF measured; internal dataset, no external source",
    },
    "internal_balgrist_motor_11": {
        "task_conditions": ["motion"],
        "implicit_baseline": None,            # 51% coverage, real unmodelled rest
        "onset_shift_s": 0.0,
        "duration_override_s": None,
        "condition_from_filename": False,
        "exclude_runs": [],
        "hrf_tail_s": 0.6,
        "notes": ("20 blocks x 15 s in a 590 s run. Single condition vs implicit "
                  "rest. NO events.json ships with this dataset, so the meaning of "
                  "`motion` is undocumented beyond the filename."),
        "verified": "events measured; UNDOCUMENTED - no events.json, no publication",
    },
    "internal_balgrist_painmotor_21": {
        "task_conditions": ["motion", "pain", "interaction", "instruction", "rating"],
        "implicit_baseline": None,            # 62% coverage
        "onset_shift_s": 0.0,
        "duration_override_s": None,
        "condition_from_filename": False,
        "exclude_runs": [],
        "hrf_tail_s": 21.2,
        "notes": ("Canonical 36 events (12 instruction / 12 rating / 4 each of "
                  "motion, pain, interaction). Four runs have fewer pain trials "
                  "(sub-02 run1=2, sub-10 run1=3, sub-16 run2=3, sub-17 run1=3) "
                  "because thermal stimuli were not delivered -- thermode issues. "
                  "The dataset's own events.json states undelivered blocks are "
                  "simply absent and NO extra 'expected-no-stim' regressor is "
                  "needed. sub-19 ran a SWAPPED paradigm order (already excluded "
                  "upstream); never pool it naively if recovered."),
        "verified": "events measured + dataset events.json documents both anomalies",
    },
    "openneuro_ds004616_spinalcord_handgrasp_task": {
        "task_conditions": ["left", "right"],
        "implicit_baseline": "rest",          # REQUIRED: conditions tile the run
        "onset_shift_s": 2.5,                 # measured from grip-force traces
        "duration_override_s": 16.0,          # actual grasp, not the nominal 15.0
        "condition_from_filename": False,
        "exclude_runs": [],
        "hrf_tail_s": 0.0,                    # no post-block data at all
        "notes": ("Grip force (physio channels right_grip/left_grip) proves the "
                  "task was performed: 52/52 runs correctly lateralised, force in "
                  "the opposite hand ~0.003 of peak. The same traces show the "
                  "grasp starts +2.5 s after the events onset and runs 16.0 s. "
                  "Fitting as written costs ~26% of the variance. ses-02 follows a "
                  "30-min acute intermittent hypoxia protocol -- do NOT treat the "
                  "two sessions as repeat measurements."),
        "verified": "events + grip force (384 blocks) + Hemmerling 2023 methods",
    },
    "openneuro_ds004926_dorsalhorn_pain": {
        "task_conditions": ["heat"],
        "implicit_baseline": None,            # 8% coverage, sparse event design
        "onset_shift_s": 0.0,
        "duration_override_s": None,
        "condition_from_filename": False,
        "exclude_runs": [],
        "hrf_tail_s": 17.4,
        "notes": ("EVENT-RELATED, not block: 1 s stimulus at 48 C with a 70 C/s "
                  "thermode ramp, verified against Dabbagh 2025. `duration` means "
                  "the stimulus. Four runs lack the `rating` column (sub-03 and "
                  "sub-31, both sessions, run-02) -- only matters for parametric "
                  "modulation. Our local copy is the te40 reliability subset (80 "
                  "runs); the full release has ~5 runs/session at different TEs."),
        "verified": "events measured + Dabbagh 2025 (doi:10.1162/imag_a_00273)",
    },
    "openneuro_ds005883_cospine_pain": {
        "task_conditions": ["pain", "rating"],
        "implicit_baseline": None,            # 39% coverage
        "onset_shift_s": 0.0,
        "duration_override_s": None,
        "condition_from_filename": False,
        "exclude_runs": ["sub-22_task-pain"],   # truncated BOLD, corrupt gzip
        "hrf_tail_s": 12.3,
        "notes": ("15 pain + 15 rating per run. PR = pain intensity, UpR = "
                  "unpleasantness, both 0-10 VAS (documented in the dataset's "
                  "events.json). The 4 s event is the 3 s plateau plus 40 C/s "
                  "ramps. The published 'rating 5 s each' does not reconcile with "
                  "the 11 s rating event -- UNVERIFIED gap, does not block fitting."),
        "verified": "events measured + Wei 2025 (doi:10.1038/s41597-025-05982-x)",
    },
    "openneuro_ds005884_cospine_motor": {
        "task_conditions": None,               # taken from the filename entity
        "implicit_baseline": None,             # 36% coverage
        "onset_shift_s": 0.0,
        "duration_override_s": None,
        "condition_from_filename": True,       # task-motorL / task-motorR
        "exclude_runs": [],
        "hrf_tail_s": 18.2,
        "notes": ("events.tsv has ONLY onset and duration -- no trial_type. The "
                  "dataset README wrongly claims one. Condition is the task entity: "
                  "one run is one hand. 12 blocks of 8 s PER RUN (the README's "
                  "'12 total, 6 per hand' is also wrong). Run lengths vary "
                  "115-170 volumes: build the design per run."),
        "verified": "events measured + Wei 2025; README contradicted by the data",
    },
}

# Resting-state: no task model.
RESTING = ["openneuro_ds004386_spinalcord_rest_testretest",
           "openneuro_ds005075_brain_spine_rest"]


def spec_for(dataset_key: str) -> Optional[dict[str, Any]]:
    return SPEC.get(dataset_key)


def conditions_for(dataset_key: str, run_id: str) -> list[str]:
    """Modelled conditions for one run, excluding the implicit baseline."""
    s = SPEC.get(dataset_key)
    if not s:
        return []
    if s.get("condition_from_filename"):
        import re
        m = re.search(r"task-([A-Za-z0-9]+)", run_id or "")
        return [m.group(1)] if m else []
    return list(s.get("task_conditions") or [])


def is_excluded(dataset_key: str, run_id: str) -> bool:
    s = SPEC.get(dataset_key)
    return bool(s and run_id in (s.get("exclude_runs") or []))


def corrected_events(dataset_key: str, rows: list[dict], start_time_s: float,
                     run_id: str = "") -> list[dict]:
    """Apply every verified correction to one run's events.

    Returns rows with `onset` on the PREPROCESSED series clock and only the
    modelled conditions retained. Order matters: the StartTime shift is a
    property of the derivative, the dataset offset a property of the paradigm.
    """
    s = SPEC.get(dataset_key)
    if not s:
        return []
    keep = set(conditions_for(dataset_key, run_id))
    shift = float(s.get("onset_shift_s") or 0.0)
    dur_override = s.get("duration_override_s")
    out: list[dict] = []
    for r in rows:
        cond = (r.get("trial_type") or "").strip()
        if s.get("condition_from_filename"):
            cond = next(iter(keep), "task")
        elif cond not in keep:
            continue                      # baseline + unmodelled conditions
        try:
            onset = float(r["onset"]) - float(start_time_s) + shift
            dur = float(dur_override if dur_override is not None
                        else (r.get("duration") or 0.0))
        except (TypeError, ValueError, KeyError):
            continue
        if onset + dur <= 0:
            continue                      # entirely inside the discarded period
        out.append({"onset": round(onset, 4), "duration": round(dur, 4),
                    "trial_type": cond})
    return out
