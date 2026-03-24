
import pytest
import sys
from unittest.mock import MagicMock

# Monkeypatch thinc if present to avoid random seed error
try:
    import thinc.util
    # Replace fix_random_seed with a no-op or safe version
    def safe_fix_random_seed(seed=None):
        pass
    thinc.util.fix_random_seed = safe_fix_random_seed
except ImportError:
    pass
