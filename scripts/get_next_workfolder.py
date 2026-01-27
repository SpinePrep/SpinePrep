#!/usr/bin/env python3
"""
Helper script to get next workfolder for bash scripts.

Usage:
    python3 scripts/get_next_workfolder.py <type>
    
Returns the path to the next workfolder (e.g., work/wf_smoke_001)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from spinalfmriprep.workfolder import get_next_workfolder

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: get_next_workfolder.py <type>", file=sys.stderr)
        print("  type: smoke, reg, or full", file=sys.stderr)
        sys.exit(1)
    
    wf_type = sys.argv[1]
    if wf_type not in ("smoke", "reg", "full"):
        print(f"ERROR: Invalid type '{wf_type}'. Must be smoke, reg, or full", file=sys.stderr)
        sys.exit(1)
    
    work_root = Path(__file__).parent.parent / "work"
    next_wf = get_next_workfolder(wf_type, work_root)
    print(str(next_wf))


