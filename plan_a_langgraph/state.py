"""
Plan A — LangGraph State Schema.

Defines the typed state that flows through the cyclic graph:
    TestingNode → RouterNode → FixerNode → TestingNode → ...

Uses TypedDict for LangGraph's state management. State deltas are
passed between nodes (only changed fields), keeping token usage low.
"""

from typing import TypedDict, Annotated
from operator import add


class FailureRecord(TypedDict):
    suite: str
    command: str
    check: str
    status: str
    notes: str
    severity: str


class PatchRecord(TypedDict):
    file: str
    description: str
    old_code: str
    new_code: str
    applied: bool
    iteration: int


class IterationSnapshot(TypedDict):
    iteration: int
    pass_rate: float
    total: int
    passed: int
    failed: int
    num_critical: int
    patches_applied: int
    analysis: str


class PipelineState(TypedDict):
    """The central state object threaded through the LangGraph cycle.

    LangGraph passes this state between nodes. Each node reads what it
    needs and writes back only the fields it changes.
    """
    # ── Cycle control ────────────────────────────────────────────────
    iteration: int                          # Current iteration (1-based)
    max_iterations: int                     # Safety cap
    target_pass_rate: float                 # Convergence threshold (0-100)
    suite: str                              # Test suite name ("all", "smoke", etc.)
    run_id: str                             # Unique run identifier
    status: str                             # "running", "converged", "stopped", "error"

    # ── Latest test results ──────────────────────────────────────────
    pass_rate: float                        # Current pass rate (0-100)
    total_tests: int
    passed_tests: int
    failed_tests: int
    error_tests: int
    failures: list[FailureRecord]           # All current failures
    critical_failures: list[FailureRecord]  # Only critical/high severity
    report_path: str                        # Path to latest markdown report
    raw_json_path: str                      # Path to latest qa_results_all.json

    # ── Patch history ────────────────────────────────────────────────
    all_patches: list[PatchRecord]          # Cumulative patches across all iterations
    latest_patches: list[PatchRecord]       # Patches from the most recent iteration
    latest_analysis: str                    # Fixer's analysis of failures

    # ── History (append-only) ────────────────────────────────────────
    history: Annotated[list[IterationSnapshot], add]  # LangGraph auto-appends

    # ── Error tracking ───────────────────────────────────────────────
    error_message: str                      # Non-empty if the cycle hit a fatal error
