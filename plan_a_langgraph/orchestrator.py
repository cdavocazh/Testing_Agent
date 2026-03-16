"""
Plan A — LangGraph Cyclic State Machine Orchestrator.

Builds a StateGraph with a cyclic topology:

    ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
    │ testing_node │ ──→ │ router_node  │ ──→ │ fixer_node  │
    └─────────────┘     └──────────────┘     └─────────────┘
           ↑                   │                     │
           │                   │ "done"              │
           │                   ↓                     │
           │              ┌─────────┐                │
           │              │   END   │                │
           │              └─────────┘                │
           │                                         │
           └─────────── (cycle back) ────────────────┘

Usage:
    python orchestrator.py                          # Full cycle
    python orchestrator.py --suite smoke            # Quick cycle
    python orchestrator.py --max-iter 3             # Limit iterations
    python orchestrator.py --target 99.0            # Pass rate target
    python orchestrator.py --dry-run                # Test once, no fixes
    python orchestrator.py --visualize              # Export graph PNG
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Ensure plan_a_langgraph is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, END

from state import PipelineState
from nodes import testing_node, router_node, fixer_node
from config import (
    MAX_ITERATIONS,
    TARGET_PASS_RATE,
    FINANCIAL_AGENT_ROOT,
    ARTIFACTS_DIR,
    GIT_AUTO_BRANCH,
    GIT_BRANCH_PREFIX,
)


def build_graph() -> StateGraph:
    """Construct the LangGraph cyclic state machine.

    Graph topology:
        START → testing_node → (router decision)
                                  ├─ "fix"  → fixer_node → testing_node (cycle)
                                  └─ "done" → END
    """
    graph = StateGraph(PipelineState)

    # ── Add nodes ────────────────────────────────────────────────────
    graph.add_node("testing_node", testing_node)
    graph.add_node("fixer_node", fixer_node)

    # ── Set entry point ──────────────────────────────────────────────
    graph.set_entry_point("testing_node")

    # ── Add edges ────────────────────────────────────────────────────
    # After testing, route based on results
    graph.add_conditional_edges(
        "testing_node",
        router_node,
        {
            "fix": "fixer_node",
            "done": END,
        },
    )

    # After fixing, go back to testing (the cycle)
    graph.add_edge("fixer_node", "testing_node")

    return graph


def create_initial_state(
    suite: str,
    max_iterations: int,
    target_pass_rate: float,
    run_id: str,
) -> PipelineState:
    """Create the initial state for the pipeline."""
    return PipelineState(
        iteration=1,
        max_iterations=max_iterations,
        target_pass_rate=target_pass_rate,
        suite=suite,
        run_id=run_id,
        status="running",
        pass_rate=0.0,
        total_tests=0,
        passed_tests=0,
        failed_tests=0,
        error_tests=0,
        failures=[],
        critical_failures=[],
        report_path="",
        raw_json_path="",
        all_patches=[],
        latest_patches=[],
        latest_analysis="",
        history=[],
        error_message="",
    )


def _create_git_branch(run_id: str):
    """Create a safety branch in the Financial Agent repo."""
    if not GIT_AUTO_BRANCH:
        return
    branch = f"{GIT_BRANCH_PREFIX}/{run_id}"
    try:
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(FINANCIAL_AGENT_ROOT),
            capture_output=True, text=True, check=True,
        )
        print(f"  Created git branch: {branch}")
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: Could not create git branch: {e.stderr.strip()}")


def _save_final_report(final_state: PipelineState):
    """Save the orchestration run summary."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = final_state.get("run_id", "unknown")

    summary = {
        "run_id": run_id,
        "finished": datetime.now().isoformat(),
        "final_status": final_state.get("status", "unknown"),
        "final_pass_rate": final_state.get("pass_rate", 0),
        "total_iterations": final_state.get("iteration", 0),
        "total_patches_applied": len(final_state.get("all_patches", [])),
        "history": final_state.get("history", []),
        "final_failures": len(final_state.get("failures", [])),
        "final_critical": len(final_state.get("critical_failures", [])),
        "error_message": final_state.get("error_message", ""),
    }

    path = ARTIFACTS_DIR / f"run_{run_id}.json"
    path.write_text(json.dumps(summary, indent=2))
    print(f"\n  Run summary: {path}")


def _print_report(final_state: PipelineState):
    """Print the final orchestration report."""
    history = final_state.get("history", [])

    print(f"\n{'═' * 70}")
    print(f"  LANGGRAPH ORCHESTRATION COMPLETE — Run {final_state.get('run_id', '?')}")
    print(f"{'═' * 70}")
    print(f"  Final status:    {final_state.get('status', '?')}")
    print(f"  Final pass rate: {final_state.get('pass_rate', 0):.1f}%")
    print(f"  Iterations run:  {len(history)}")
    print(f"  Total patches:   {len(final_state.get('all_patches', []))}")
    print()

    if history:
        print(f"  {'Iter':<6} {'Pass Rate':<12} {'Failed':<10} {'Critical':<10} "
              f"{'Patches':<10}")
        print(f"  {'─' * 48}")
        for h in history:
            print(f"  {h.get('iteration', '?'):<6} {h.get('pass_rate', 0):<12.1f} "
                  f"{h.get('failed', 0):<10} {h.get('num_critical', 0):<10} "
                  f"{h.get('patches_applied', 0):<10}")

    print(f"{'═' * 70}\n")


def run(suite: str, max_iterations: int, target: float, dry_run: bool, visualize: bool):
    """Execute the LangGraph orchestration pipeline."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'═' * 70}")
    print(f"  PLAN A — LangGraph Cyclic State Machine")
    print(f"  Run ID:       {run_id}")
    print(f"  Suite:        {suite}")
    print(f"  Max iter:     {max_iterations}")
    print(f"  Target rate:  {target}%")
    print(f"  Dry run:      {dry_run}")
    print(f"  FA root:      {FINANCIAL_AGENT_ROOT}")
    print(f"{'═' * 70}")

    # Build the graph
    graph = build_graph()

    # Optionally export visualization
    if visualize:
        try:
            compiled = graph.compile()
            png_data = compiled.get_graph().draw_mermaid_png()
            viz_path = ARTIFACTS_DIR / "graph.png"
            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            viz_path.write_bytes(png_data)
            print(f"  Graph visualization saved to: {viz_path}")
        except Exception as e:
            print(f"  WARNING: Could not generate visualization: {e}")

    # For dry-run, limit to 1 iteration with an unreachable target
    if dry_run:
        max_iterations = 1
        target = 100.1  # Unreachable, so it runs once and stops at router

    # Create safety branch
    if not dry_run:
        _create_git_branch(run_id)

    # Build initial state
    initial_state = create_initial_state(
        suite=suite,
        max_iterations=max_iterations,
        target_pass_rate=target,
        run_id=run_id,
    )

    # Compile and run the graph
    compiled = graph.compile()
    final_state = compiled.invoke(initial_state)

    # Mark convergence
    if final_state.get("pass_rate", 0) >= target and final_state.get("status") != "error":
        final_state["status"] = "converged"

    # Save and print results
    _save_final_report(final_state)
    _print_report(final_state)


def main():
    parser = argparse.ArgumentParser(
        description="Plan A — LangGraph Cyclic Orchestrator",
    )
    parser.add_argument("--suite", default="all",
                        help="Test suite (default: all)")
    parser.add_argument("--max-iter", type=int, default=MAX_ITERATIONS,
                        help=f"Maximum iterations (default: {MAX_ITERATIONS})")
    parser.add_argument("--target", type=float, default=TARGET_PASS_RATE,
                        help=f"Target pass rate %% (default: {TARGET_PASS_RATE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run tests once only, no patches")
    parser.add_argument("--visualize", action="store_true",
                        help="Export graph visualization to PNG")
    args = parser.parse_args()

    run(
        suite=args.suite,
        max_iterations=args.max_iter,
        target=args.target,
        dry_run=args.dry_run,
        visualize=args.visualize,
    )


if __name__ == "__main__":
    main()
