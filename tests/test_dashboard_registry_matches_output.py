"""The dashboard registry must match what the steps actually emit.

Drift here is silent and runs in both directions, and both were live until
2026-07-23: S4_dvars_plot stayed in REPORTLET_ORDER after S4 stopped emitting it
(a dead slot in the report), while S4_slicewise_heatmap was emitted every run and
never displayed at all -- a diagnostic generated for nobody.

These tests pin the registry against the renderers, so a reportlet added or
dropped in a step must be reflected in the dashboard.
"""
from spineprep.qc_dashboard_html import REPORTLET_ORDER, REPORTLET_LABELS


def test_every_ordered_reportlet_has_a_label():
    missing = []
    for step, keys in REPORTLET_ORDER.items():
        labels = REPORTLET_LABELS.get(step, {})
        for k in keys:
            if k not in labels:
                missing.append(f"{step}/{k}")
    assert not missing, f"ordered reportlets with no label: {missing}"


def test_every_label_is_ordered():
    extra = []
    for step, labels in REPORTLET_LABELS.items():
        keys = set(REPORTLET_ORDER.get(step, []))
        for k in labels:
            if k not in keys:
                extra.append(f"{step}/{k}")
    assert not extra, f"labelled reportlets missing from REPORTLET_ORDER: {extra}"


def test_s4_registry_matches_the_three_reportlets_s4_emits():
    """S4 emits motion_traces, slicewise_heatmap, tsnr_comparison -- no dvars."""
    keys = REPORTLET_ORDER["S4_func_motion_correction"]
    assert "S4_dvars_plot" not in keys, "S4 no longer emits a DVARS plot"
    assert "S4_slicewise_heatmap" in keys, "S4 emits a slicewise heatmap; display it"
    assert set(keys) == {
        "S4_motion_traces", "S4_slicewise_heatmap", "S4_tsnr_comparison"}


def test_subject_report_registry_has_no_dead_dvars_entry():
    """The per-subject report keeps its OWN registry (s10/reports.py), separate
    from the dashboard's. Both carried the dropped DVARS plot; fixing one and
    not the other leaves the drift half-repaired."""
    from spineprep.steps.s10.reports import HEADLINE_FIG, SECONDARY_FIG
    s4 = HEADLINE_FIG.get("S4", []) + SECONDARY_FIG.get("S4", [])
    assert "dvars" not in s4, "S4 no longer emits a DVARS plot"
    assert "slicewise_heatmap" in s4, "S4 emits a slicewise heatmap; show it"
