
import pytest
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make the package importable regardless of test-module order or editable install
# (several test modules insert this themselves; doing it here makes the whole
# suite order-independent so any test file can run in isolation).
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ---------------------------------------------------------------------------
# Skip tests that shell out to neuroimaging binaries when those binaries are
# absent (e.g. plain CI runners). They exercise the real pipeline and pass on
# a machine / in the container that has SCT, FSL and ANTs installed. Everything
# else — the bulk of the suite — runs everywhere. Skips are precise: only the
# tests that actually invoke a missing tool are skipped, so CI still fails on a
# genuine regression in the pure-Python code.
# ---------------------------------------------------------------------------

# (test-file basename, name substring or None for the whole file, required tools)
_TOOL_REQUIREMENTS = [
    ("test_s3_subtask_integration.py", None, ("sct_deepseg", "flirt")),
    ("test_S4_unit.py", "test_coarse_bulk_xy_correction", ("flirt",)),
]


def _missing_tools(*tools):
    return [t for t in tools if shutil.which(t) is None]


def pytest_collection_modifyitems(config, items):
    for item in items:
        fname = Path(str(item.fspath)).name
        for req_file, name_sub, tools in _TOOL_REQUIREMENTS:
            if fname == req_file and (name_sub is None or name_sub in item.name):
                missing = _missing_tools(*tools)
                if missing:
                    item.add_marker(
                        pytest.mark.skip(
                            reason=(
                                f"requires {', '.join(missing)} "
                                "(installed in the SpinePrep container; absent on this host)"
                            )
                        )
                    )

# Monkeypatch thinc if present to avoid random seed error
try:
    import thinc.util
    # Replace fix_random_seed with a no-op or safe version
    def safe_fix_random_seed(seed=None):
        pass
    thinc.util.fix_random_seed = safe_fix_random_seed
except ImportError:
    pass
