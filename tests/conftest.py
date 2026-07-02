
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make the package importable regardless of test-module order or editable install
# (several test modules insert this themselves; doing it here makes the whole
# suite order-independent so any test file can run in isolation).
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Monkeypatch thinc if present to avoid random seed error
try:
    import thinc.util
    # Replace fix_random_seed with a no-op or safe version
    def safe_fix_random_seed(seed=None):
        pass
    thinc.util.fix_random_seed = safe_fix_random_seed
except ImportError:
    pass
