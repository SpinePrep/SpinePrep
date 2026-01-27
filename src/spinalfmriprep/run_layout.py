"""
Step execution layout and utilities.

Provides helpers for step execution with subtask support.
"""

from __future__ import annotations

from typing import Optional

from spinalfmriprep.subtask import ExecutionContext, set_execution_context


def setup_subtask_context(subtask_id: Optional[str] = None) -> ExecutionContext:
    """
    Set up execution context for subtask execution.

    Args:
        subtask_id: Optional subtask ID to execute (e.g., "S3.1").

    Returns:
        ExecutionContext instance.
    """
    context = ExecutionContext(target_subtask=subtask_id)
    set_execution_context(context)
    return context
