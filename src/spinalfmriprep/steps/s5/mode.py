"""S5 mode selection: per-run decision tree for distortion correction.

Picks one of {"topup", "syn"} from S1 inventory metadata + the
BIDS `IntendedFor` field. Pure functions; no I/O beyond reading qc/runs
JSON the caller already loaded.

See private/SPEC/S5_func_distortion_correction.md §S5.1 for the rule.
"""

from __future__ import annotations

from typing import Any, Optional


def _opposite_pe(pe_a: Optional[str], pe_b: Optional[str]) -> bool:
    """True iff the two BIDS PhaseEncodingDirection values flip sign on
    the same axis (e.g. "j" + "j-", "i-" + "i", "k" + "k-")."""
    if not pe_a or not pe_b:
        return False
    a_axis = pe_a.rstrip("-")
    b_axis = pe_b.rstrip("-")
    if a_axis != b_axis:
        return False
    return pe_a.endswith("-") != pe_b.endswith("-")


def _pe_from_run(run: dict) -> Optional[str]:
    """Pull PhaseEncodingDirection from the run's acquisition dict if S1
    extracted it (post-A5 commit); else fall back to the BIDS `dir-`
    filename entity. dir-AP -> j-, dir-PA -> j (standard cervical EPI
    convention; LR/RL not used in our v1_validation set)."""
    acq = run.get("acquisition") or {}
    pe = acq.get("PhaseEncodingDirection") if isinstance(acq, dict) else None
    if pe:
        return pe
    # Fall back to the BIDS `dir-XX` entity in the filename
    path = run.get("path", "").lower()
    import re
    m = re.search(r"_dir-([a-z]+)_", path)
    if not m:
        return None
    label = m.group(1)
    return {
        "ap": "j-",
        "pa": "j",
        "lr": "i-",
        "rl": "i",
        "is": "k-",
        "si": "k",
    }.get(label)


def _intended_for_matches(fmap_run: dict, bold_relpath: str) -> bool:
    """True if the fmap's IntendedFor field (a string or list of strings,
    relative to subject dir per BIDS) points at this BOLD run.

    Falls back to TRUE if no IntendedFor is recorded — many older datasets
    omit it, and refusing them would block topup for legitimate data.
    """
    acq = fmap_run.get("acquisition", {})
    intended = acq.get("IntendedFor") if isinstance(acq, dict) else None
    if intended is None:
        return True  # permissive fallback
    if isinstance(intended, str):
        intended = [intended]
    # IntendedFor entries are subject-relative; bold_relpath is bids-root-relative.
    # Strip the leading subject (and optional session) directory from bold_relpath
    # to compare. e.g. bold_relpath = "sub-02/func/sub-02_task-motor_bold.nii.gz"
    # intended[0] = "func/sub-02_task-motor_bold.nii.gz"
    bold_tail = "/".join(bold_relpath.split("/")[1:])  # drop sub-XX/
    return any(bold_tail.endswith(s.strip("/")) for s in intended)


def select_mode(
    bold_run: dict,
    fmap_runs: list[dict],
) -> tuple[str, list[dict]]:
    """Return (mode, eligible_fmaps).

    Args:
        bold_run: an entry from S1 inventory `runs` (modality=="func").
        fmap_runs: all entries from S1 inventory `runs` with modality=="fmap"
            that target the same subject/session as bold_run.

    Returns:
        mode: one of "topup", "syn".
        eligible_fmaps: the fmap entries that drove the decision (empty for
            syn). The orchestrator uses these to build acqparams.
    """
    same_sub_ses = [
        f for f in fmap_runs
        if f.get("subject") == bold_run.get("subject")
        and f.get("session") == bold_run.get("session")
    ]
    intended = [
        f for f in same_sub_ses
        if _intended_for_matches(f, bold_run.get("path", ""))
    ]

    # Topup: at least one pair of opposite-PE fmap volumes.
    epi_fmaps = [
        f for f in intended
        if f.get("path", "").endswith(("_epi.nii.gz", "_epi.nii"))
    ]
    for i in range(len(epi_fmaps)):
        for j in range(i + 1, len(epi_fmaps)):
            pe_i = _pe_from_run(epi_fmaps[i])
            pe_j = _pe_from_run(epi_fmaps[j])
            if _opposite_pe(pe_i, pe_j):
                # Ensure each fmap has a usable PE recorded for downstream
                # writers (acqparams.txt)
                for ent, pe in ((epi_fmaps[i], pe_i), (epi_fmaps[j], pe_j)):
                    acq = ent.setdefault("acquisition", {}) or {}
                    if not isinstance(acq, dict):
                        acq = {}
                        ent["acquisition"] = acq
                    acq.setdefault("PhaseEncodingDirection", pe)
                return "topup", [epi_fmaps[i], epi_fmaps[j]]

    # Image-only SyN otherwise. (GRE phasediff/magnitude fieldmaps would in
    # principle drive a FUGUE path, but FUGUE was removed in v1: no GRE-fieldmap
    # data exists in the validation cohort and the path was never exercised. Such
    # data falls through to SyN — recorded honestly as the image-based fallback.
    # See .claude/specs/v1-claims-ledger.md.)
    return "syn", []
