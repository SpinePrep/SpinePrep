"""
Tests for subtask execution infrastructure.

Tests the subtask decorator, context manager, and execution context logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from spineprep.subtask import (
    ExecutionContext,
    get_execution_context,
    set_execution_context,
    should_exit_after_subtask,
    subtask,
    subtask_context,
)


def test_execution_context_no_target():
    """Test ExecutionContext with no target subtask (runs all)."""
    context = ExecutionContext(target_subtask=None)

    # Should execute all subtasks
    assert context.is_subtask_active("S3.1") is True
    assert context.is_subtask_active("S3.2") is True
    assert context.is_subtask_active("S3.3") is True

    # Should continue after all subtasks
    assert context.should_continue_after_subtask("S3.1") is True
    assert context.should_continue_after_subtask("S3.2") is True
    assert context.should_continue_after_subtask("S3.3") is True


def test_execution_context_with_target():
    """Test ExecutionContext with target subtask."""
    context = ExecutionContext(target_subtask="S3.1")

    # Should execute S3.1
    assert context.is_subtask_active("S3.1") is True

    # Should not continue after S3.1 (target reached)
    assert context.should_continue_after_subtask("S3.1") is False

    # Should continue after earlier subtasks (if any)
    # Note: In practice, subtasks execute in order, so this tests the logic


def test_execution_context_subtask_ordering():
    """Test that subtask ordering is respected."""
    context = ExecutionContext(target_subtask="S3.2")

    # S3.1 should be active (needed to reach S3.2)
    assert context.is_subtask_active("S3.1") is True

    # S3.2 should be active (target)
    assert context.is_subtask_active("S3.2") is True

    # S3.3 should not be active (beyond target)
    # Note: This depends on implementation - if we want to allow
    # running only S3.2 when S3.1 outputs exist, this might be False
    # For now, we'll test the basic ordering logic
    assert context.is_subtask_active("S3.3") is False


def test_subtask_decorator_with_context():
    """Test @subtask decorator with execution context."""
    set_execution_context(ExecutionContext(target_subtask="S3.1"))

    call_count = {"S3.1": 0, "S3.2": 0}

    @subtask("S3.1")
    def func_s3_1():
        call_count["S3.1"] += 1
        return "S3.1_result"

    @subtask("S3.2")
    def func_s3_2():
        call_count["S3.2"] += 1
        return "S3.2_result"

    # S3.1 should execute
    result = func_s3_1()
    assert result == "S3.1_result"
    assert call_count["S3.1"] == 1

    # S3.2 should not execute (target is S3.1)
    result = func_s3_2()
    assert result is None
    assert call_count["S3.2"] == 0

    # Clean up
    set_execution_context(None)


def test_subtask_decorator_no_context():
    """Test @subtask decorator without execution context."""
    set_execution_context(None)

    call_count = 0

    @subtask("S3.1")
    def func_s3_1():
        nonlocal call_count
        call_count += 1
        return "result"

    # Should execute normally when no context
    result = func_s3_1()
    assert result == "result"
    assert call_count == 1


def test_subtask_context_manager():
    """Test subtask_context context manager."""
    set_execution_context(ExecutionContext(target_subtask="S3.1"))

    executed = []

    with subtask_context("S3.1") as should_run:
        if should_run:
            executed.append("S3.1")

    with subtask_context("S3.2") as should_run:
        if should_run:
            executed.append("S3.2")

    # S3.1 should execute, S3.2 should not
    assert "S3.1" in executed
    assert "S3.2" not in executed

    # Clean up
    set_execution_context(None)


def test_should_exit_after_subtask():
    """Test should_exit_after_subtask helper function."""
    # No context - should not exit
    set_execution_context(None)
    assert should_exit_after_subtask("S3.1") is False

    # Context with target S3.1 - should exit after S3.1
    set_execution_context(ExecutionContext(target_subtask="S3.1"))
    assert should_exit_after_subtask("S3.1") is True
    assert should_exit_after_subtask("S3.2") is False  # Not reached yet

    # Context with target S3.2 - should not exit after S3.1
    set_execution_context(ExecutionContext(target_subtask="S3.2"))
    assert should_exit_after_subtask("S3.1") is False
    assert should_exit_after_subtask("S3.2") is True

    # Clean up
    set_execution_context(None)


def test_execution_context_completed_subtasks():
    """Test that completed subtasks are tracked."""
    context = ExecutionContext(target_subtask="S3.2")

    assert len(context.completed_subtasks) == 0

    context.mark_subtask_completed("S3.1")
    assert "S3.1" in context.completed_subtasks
    assert len(context.completed_subtasks) == 1

    context.mark_subtask_completed("S3.2")
    assert "S3.2" in context.completed_subtasks
    assert len(context.completed_subtasks) == 2


def test_execution_context_current_subtask():
    """Test current subtask tracking."""
    context = ExecutionContext(target_subtask="S3.1")

    assert context.current_subtask is None

    context.set_current_subtask("S3.1")
    assert context.current_subtask == "S3.1"

    context.set_current_subtask(None)
    assert context.current_subtask is None


def test_subtask_decorator_preserves_function_metadata():
    """Test that @subtask decorator preserves function metadata."""
    @subtask("S3.1")
    def example_func(arg1: int, arg2: str = "default") -> str:
        """Example function docstring."""
        return f"{arg1}_{arg2}"

    # Check that metadata is preserved
    assert example_func.__name__ == "example_func"
    assert "Example function docstring" in example_func.__doc__

    # Check that function still works
    result = example_func(1, "test")
    assert result == "1_test"


def test_subtask_context_manager_exception_handling():
    """Test that subtask_context properly handles exceptions."""
    set_execution_context(ExecutionContext(target_subtask="S3.1"))

    executed = []

    try:
        with subtask_context("S3.1"):
            executed.append("start")
            raise ValueError("Test exception")
            executed.append("end")  # Should not execute
    except ValueError:
        pass

    # Should have executed start, but not end
    assert "start" in executed
    assert "end" not in executed

    # Context should still be cleaned up
    context = get_execution_context()
    assert context is not None
    assert context.current_subtask is None

    # Clean up
    set_execution_context(None)

