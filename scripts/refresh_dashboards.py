#!/usr/bin/env python3
"""Force-refresh every workfolder's dashboard + the project-root
"latest" landing page.

Run this when you've made changes to the dashboard renderer itself,
or any time you suspect a dashboard is stale. Per-step `run()` calls
already refresh the relevant dashboard, so this is for bulk refresh
only.

Usage:
    python scripts/refresh_dashboards.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spineprep.dashboard_latest import write_latest_landing
from spineprep.qc_dashboard import generate_dashboard


def main() -> int:
    work_root = Path(__file__).parent.parent / "work"
    if not work_root.exists():
        print(f"ERROR: {work_root} not found")
        return 1

    wfs = sorted(
        d for d in work_root.iterdir()
        if d.is_dir() and d.name.startswith("wf_")
    )
    print(f"Refreshing dashboards in {len(wfs)} workfolders...")

    for wf in wfs:
        try:
            r = generate_dashboard(wf)
            print(f"  {wf.name:25s}  indexed={r.indexed_qc_files:3d}  "
                  f"errors={len(r.errors)}")
        except Exception as e:
            print(f"  {wf.name:25s}  FAILED: {e}")

    landing = write_latest_landing(work_root.resolve())
    print()
    print(f"Latest landing: {landing}")
    print(f"Open in browser: file://{landing.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
