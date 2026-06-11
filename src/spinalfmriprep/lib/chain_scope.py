"""Derive the chain scope from a workfolder, for scope-portable cross-step lookups.

The full-chain runner allocates ``wf_<scope>_NNN`` folders and promotes each step
to ``work/done/<scope>/S<N>``. Cross-step input lookups must resolve the *same*
scope as the workfolder they run in — hardcoding ``reg`` breaks every non-reg
chain (e.g. the balgrist ``exp`` experiment). Use ``chain_scope(out_dir)`` to get
the scope and build ``work/done/<scope>/...`` paths instead of literal ``reg``.
"""

from __future__ import annotations

from pathlib import Path


def chain_scope(out_dir: Path | str, default: str = "reg") -> str:
    """Scope (e.g. ``reg`` / ``exp`` / ``full``) from a ``wf_<scope>_NNN`` folder.

    Falls back to ``default`` when the name isn't a ``wf_<scope>_NNN`` workfolder.
    """
    name = Path(out_dir).name
    if name.startswith("wf_") and "_" in name[3:]:
        return name[3:].rsplit("_", 1)[0]
    return default
