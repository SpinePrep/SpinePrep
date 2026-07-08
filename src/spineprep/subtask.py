"""
Subtask execution infrastructure for SpinePrep.

Provides decorators and context managers to mark code sections as belonging to
specific subtasks, enabling selective execution via --subtask CLI flag.
"""

from __future__ import annotations

import contextlib
import functools
from typing import Any, Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class ExecutionContext:
    """Tracks current and target subtask during step execution."""

    def __init__(self, target_subtask: Optional[str] = None):
        """
        Initialize execution context.

        Args:
            target_subtask: The subtask ID to execute (e.g., "S3.1").
                          If None, all subtasks are executed.
        """
        self.target_subtask = target_subtask
        self.current_subtask: Optional[str] = None
        self.completed_subtasks: list[str] = []

    def should_continue_after_subtask(self, subtask_id: str) -> bool:
        """
        Check if execution should continue after completing a subtask.

        Args:
            subtask_id: The subtask ID that just completed.

        Returns:
            True if execution should continue, False if it should stop.
        """
        if self.target_subtask is None:
            # No target specified, continue with all subtasks
            return True

        # If we just completed the target subtask, stop
        if subtask_id == self.target_subtask:
            return False

        # If target is later in sequence, continue
        # (This assumes subtasks are executed in order)
        return True

    def is_subtask_active(self, subtask_id: str) -> bool:
        """
        Check if a subtask should be executed.

        Args:
            subtask_id: The subtask ID to check.

        Returns:
            True if the subtask should be executed, False if it should be skipped.
        """
        if self.target_subtask is None:
            # No target specified, execute all subtasks
            return True

        # If it's the target subtask, execute it
        if subtask_id == self.target_subtask:
            return True

        # Check if we need to execute earlier subtasks to reach the target
        # Extract step number and subtask number for comparison
        try:
            step_num, subtask_num = subtask_id.split(".")
            target_step, target_subtask_num = self.target_subtask.split(".")
            if step_num == target_step:
                # Same step, only execute if subtask number is <= target
                # This allows running S3.1 when target is S3.3 (dependency)
                return int(subtask_num) <= int(target_subtask_num)
            else:
                # Different step, don't execute
                return False
        except (ValueError, IndexError):
            # Invalid format, don't execute to be safe
            return False

        return False

    def mark_subtask_completed(self, subtask_id: str) -> None:
        """Mark a subtask as completed."""
        if subtask_id not in self.completed_subtasks:
            self.completed_subtasks.append(subtask_id)
        self.current_subtask = None

    def set_current_subtask(self, subtask_id: str) -> None:
        """Set the currently executing subtask."""
        self.current_subtask = subtask_id


# Global execution context (thread-local would be better for multi-threading,
# but SpinePrep is single-threaded)
_execution_context: Optional[ExecutionContext] = None


def set_execution_context(context: ExecutionContext) -> None:
    """Set the global execution context."""
    global _execution_context
    _execution_context = context


def get_execution_context() -> Optional[ExecutionContext]:
    """Get the global execution context."""
    return _execution_context


def subtask(subtask_id: str) -> Callable[[F], F]:
    """
    Decorator to mark a function as belonging to a specific subtask.

    Args:
        subtask_id: The subtask ID (e.g., "S3.1")

    Returns:
        Decorated function that checks execution context before running.

    Example:
        @subtask("S3.1")
        def _localize_and_crop_func_ref0_s2_spec(...):
            # S3.1 logic here
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            context = get_execution_context()
            if context is None:
                # No context, execute normally
                return func(*args, **kwargs)

            # Check if this subtask should be executed
            if not context.is_subtask_active(subtask_id):
                # Skip this subtask
                return None

            # Set current subtask and execute
            context.set_current_subtask(subtask_id)
            try:
                result = func(*args, **kwargs)
                context.mark_subtask_completed(subtask_id)
                return result
            finally:
                context.set_current_subtask(None)

        return wrapper  # type: ignore

    return decorator


@contextlib.contextmanager
def subtask_context(subtask_id: str):
    """
    Context manager to mark a code block as belonging to a specific subtask.

    Args:
        subtask_id: The subtask ID (e.g., "S3.1")

    Example:
        with subtask_context("S3.3"):
            # S3.3 crop logic
            ...
    """
    context = get_execution_context()
    if context is None:
        # No context, execute normally
        yield True
        return

    # Check if this subtask should be executed
    if not context.is_subtask_active(subtask_id):
        # Skip this subtask - yield False to indicate skip
        # Note: Code inside will still execute, but can check the return value
        yield False
        return

    # Set current subtask and execute
    context.set_current_subtask(subtask_id)
    try:
        yield True
        context.mark_subtask_completed(subtask_id)
    finally:
        context.set_current_subtask(None)


def should_exit_after_subtask(subtask_id: str) -> bool:
    """
    Check if execution should exit after completing a subtask.

    This is a convenience function for use in step functions.

    Args:
        subtask_id: The subtask ID that just completed.

    Returns:
        True if execution should exit, False if it should continue.
    """
    context = get_execution_context()
    if context is None:
        return False
    return not context.should_continue_after_subtask(subtask_id)

