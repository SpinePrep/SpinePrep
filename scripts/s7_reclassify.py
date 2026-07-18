#!/usr/bin/env python3
"""Reclassify S7 run status from persisted metrics -- no reprocessing.

Why this is safe
----------------
S7's gate is a pure function of `metrics` and the policy thresholds: `_classify`
reads `cord_dice_per_level` / `cord_dice_native_func` and returns a status plus
reasons. It never touches image data, and the warps S7 produced are unchanged by
a threshold edit. So when the per-level gate gained its WARN band (0.90 PASS
level kept, 0.85 FAIL floor added), every run's status could be recomputed from
the qc.json already on disk.

This mirrors `scripts/s4_recompute_fd.py`: rewrite a reported CLASSIFICATION,
not the data behind it.

Usage
-----
    python3 scripts/s7_reclassify.py --dry-run    # report transitions only
    python3 scripts/s7_reclassify.py              # rewrite qc.json
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from spineprep.steps.s7.process import _classify  # noqa: E402

OUT = Path("/mnt/ssd1/spineprep_cohort_s2")
QC = OUT / "logs" / "S7_template_normalization"
POLICY = REPO / "policy" / "S7_template_normalization.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    qc_root = Path(args.out) / "logs" / "S7_template_normalization"
    thresholds = yaml.safe_load(POLICY.read_text()).get("qc_thresholds", {})

    trans = collections.Counter()
    recovered: list[tuple[str, str, str]] = []
    n = 0

    for qcp in sorted(qc_root.glob("*/qc.json")):
        ds = qcp.parent.name
        j = json.loads(qcp.read_text())
        changed = False
        for r in j.get("runs", []):
            m = r.get("metrics") or {}
            if not m:
                continue
            old = r.get("status")
            new, reasons = _classify(m, thresholds)
            trans[f"{old}->{new}"] += 1
            n += 1
            if old == "FAIL" and new != "FAIL":
                recovered.append((ds, r.get("run_id"), new))
            if new != old or reasons != r.get("failure_reasons"):
                r["status"] = new
                r["failure_reasons"] = reasons
                changed = True

        if changed and not args.dry_run:
            bak = qcp.with_suffix(".json.pre_reclassify")
            if not bak.exists():
                shutil.copy2(qcp, bak)
            c = collections.Counter(x.get("status") for x in j.get("runs", []))
            total = len(j.get("runs", []))
            j["status"] = ("PASS" if c.get("PASS", 0) == total
                           else "FAIL" if c.get("PASS", 0) == 0 and c.get("WARN", 0) == 0
                           else "WARN")
            qcp.write_text(json.dumps(j, indent=2))

    print(f"runs reclassified: {n}")
    print("\nstatus transitions:")
    for k, v in sorted(trans.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<14} {v}")
    if recovered:
        print(f"\nrecovered from FAIL ({len(recovered)}) -- need S8+ rerun:")
        for ds, rid, new in sorted(recovered):
            print(f"  {new:5s} {ds[:38]:40s} {rid}")
    if args.dry_run:
        print("\n(dry run - nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
