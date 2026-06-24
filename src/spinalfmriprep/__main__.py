"""Enable `python -m spinalfmriprep ...` (BIDS-App + per-step CLI)."""
from spinalfmriprep.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
