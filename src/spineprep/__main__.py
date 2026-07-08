"""Enable `python -m spineprep ...` (BIDS-App + per-step CLI)."""
from spineprep.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
