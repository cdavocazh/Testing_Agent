"""
Plan D — Custom Python Orchestrator.

A lightweight, zero-dependency (beyond openai) orchestrator that cycles:

    Testing Agent  →  evaluate results  →  Financial Fixer  →  apply patches  →  repeat

until the pass rate target is met, critical failures reach zero, or max
iterations are exhausted.

Usage:
    python orchestrator.py                         # Full cycle (all suites)
    python orchestrator.py --suite smoke           # Quick cycle (macro + equity)
    python orchestrator.py --max-iter 3            # Limit to 3 iterations
    python orchestrator.py --target 99.0           # Set pass rate target
    python orchestrator.py --dry-run               # Run tests only, no patches
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure plan_d_custom is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    FINANCIAL_AGENT_ROOT,
    ARTIFACTS_DIR,
    MAX_ITERATIONS,
    TARGET_PASS_RATE,
    TARGET_ZERO_CRITICAL,
    GIT_AUTO_BRANCH,
    GIT_BRANCH_PREFIX,
)
from test_runner import run_tests, TestRunResult
from financial_fixer import generate_patches, apply_patches


def _create_git_branch(run_id: str) -> str | None:
    """Create a new git branch in the Financial Agent repo for safety."""
    if not GIT_AUTO_BRANCH:
        return None
    branch_name = f"{GIT_BRANCH_PREFIX}/{run_id}"
    try:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(FINANCIAL_AGENT_ROOT),
            capture_output=True, text=True, check=True,
        )
        print(f"  Created git branch: {branch_name}")
        return branch_name
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: Could not create git branch: {e.stderr.strip()}")
        return None


def _git_commit_patches(iteration: int, num_patches: int):
    """Commit applied patches in the Financial Agent repo."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(FINANCIAL_AGENT_ROOT),
            capture_output=True, check=True,
        )
        msg = f"orchestrator: iteration {iteration} — applied {num_patches} patches"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(FINANCIAL_AGENT_ROOT),
            capture_output=True, text=True, check=True,
        )
        print(f"  Git commit: {msg}")
    except subprocess.CalledProcessError:
        pass  # No changes to commit (all patches may have been skipped)


def _is_converged(result: TestRunResult) -> bool:
    """Check if the test results meet convergence criteria."""
    rate_ok = result.pass_rate >= TARGET_PASS_RATE
    critical_ok = (not TARGET_ZERO_CRITICAL) or (len(result.critical_failures) == 0)
    return rate_ok and critical_ok


def _save_run_summary(run_id: str, history: list[dict]):
    """Save the full orchestration run summary."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACTS_DIR / f"run_{run_id}.json"
    summary_path.write_text(json.dumps({
        "run_id": run_id,
        "started": history[0]["timestamp"] if history else "",
        "finished": datetime.now().isoformat(),
        "iterations": len(history),
        "history": history,
        "final_pass_rate": history[-1]["pass_rate"] if history else 0,
        "converged": history[-1].get("converged", False) if history else False,
    }, indent=2))
    print(f"\n  Run summary saved to: {summary_path}")


def run_cycle(suite: str, max_iterations: int, target: float, dry_run: bool):
    """Execute the full testing → fixing → re-testing cycle."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    history: list[dict] = []
    all_patches_applied: list[dict] = []

    print(f"\n{'═' * 70}")
    print(f"  PLAN D — Custom Orchestrator")
    print(f"  Run ID:       {run_id}")
    print(f"  Suite:        {suite}")
    print(f"  Max iter:     {max_iterations}")
    print(f"  Target rate:  {target}%")
    print(f"  Dry run:      {dry_run}")
    print(f"  FA root:      {FINANCIAL_AGENT_ROOT}")
    print(f"{'═' * 70}")

    # Create a safety branch (if git is available)
    if not dry_run:
        _create_git_branch(run_id)

    for iteration in range(1, max_iterations + 1):
        iter_start = time.time()

        # ── Step 1: Run tests ────────────────────────────────────────
        test_result = run_tests(iteration=iteration, suite=suite)

        print(f"\n  Results: {test_result.passed}/{test_result.total} passed "
              f"({test_result.pass_rate}%) | "
              f"{len(test_result.failures)} failures | "
              f"{len(test_result.critical_failures)} critical")

        iter_record = {
            "iteration": iteration,
            "timestamp": test_result.timestamp,
            "pass_rate": test_result.pass_rate,
            "total": test_result.total,
            "passed": test_result.passed,
            "failed": test_result.failed,
            "errors": test_result.errors,
            "num_failures": len(test_result.failures),
            "num_critical": len(test_result.critical_failures),
            "patches_proposed": 0,
            "patches_applied": 0,
            "converged": False,
            "elapsed_seconds": 0,
        }

        # ── Step 2: Check convergence ────────────────────────────────
        if _is_converged(test_result):
            iter_record["converged"] = True
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            print(f"\n  CONVERGED at iteration {iteration}!")
            print(f"  Pass rate: {test_result.pass_rate}% >= {target}%")
            print(f"  Critical failures: {len(test_result.critical_failures)}")
            break

        if dry_run:
            print(f"\n  [Dry run] Skipping patch generation.")
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            break

        # ── Step 3: Generate patches ─────────────────────────────────
        # Prioritize critical/high failures, then include others
        failures_to_fix = test_result.critical_failures + [
            f for f in test_result.failures
            if f not in test_result.critical_failures
        ]

        patch_result = generate_patches(
            failures=failures_to_fix,
            iteration=iteration,
            previous_patches=all_patches_applied,
        )

        patches = patch_result.get("patches", [])
        iter_record["patches_proposed"] = len(patches)
        iter_record["analysis"] = patch_result.get("analysis", "")

        if not patches:
            print(f"\n  No patches proposed. Stopping cycle.")
            print(f"  Analysis: {patch_result.get('analysis', 'N/A')[:200]}")
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            break

        # ── Step 4: Apply patches ────────────────────────────────────
        apply_results = apply_patches(patches, iteration)
        applied_count = sum(1 for r in apply_results if r["applied"])
        iter_record["patches_applied"] = applied_count
        all_patches_applied.extend(
            p for p, r in zip(patches, apply_results) if r["applied"]
        )

        # Save patch details to artifacts
        patch_artifact_dir = ARTIFACTS_DIR / f"iteration_{iteration}"
        patch_artifact_dir.mkdir(parents=True, exist_ok=True)
        (patch_artifact_dir / "patches.json").write_text(
            json.dumps({"proposed": patches, "results": apply_results}, indent=2)
        )

        # Git commit if patches were applied
        if applied_count > 0:
            _git_commit_patches(iteration, applied_count)

        if applied_count == 0:
            print(f"\n  No patches could be applied. Stopping cycle.")
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            break

        iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
        history.append(iter_record)

        print(f"\n  Iteration {iteration} complete. "
              f"Applied {applied_count}/{len(patches)} patches. "
              f"Continuing to next iteration...")

    # ── Final report ─────────────────────────────────────────────────
    _save_run_summary(run_id, history)
    _print_final_report(history, run_id)


def _print_final_report(history: list[dict], run_id: str):
    """Print a summary table of all iterations."""
    print(f"\n{'═' * 70}")
    print(f"  ORCHESTRATION COMPLETE — Run {run_id}")
    print(f"{'═' * 70}")
    print(f"  {'Iter':<6} {'Pass Rate':<12} {'Failures':<10} {'Critical':<10} "
          f"{'Patches':<10} {'Time':<10} {'Status'}")
    print(f"  {'─' * 64}")
    for h in history:
        status = "CONVERGED" if h.get("converged") else "CONTINUE"
        if h == history[-1] and not h.get("converged"):
            status = "STOPPED"
        print(f"  {h['iteration']:<6} {h['pass_rate']:<12.1f} {h['num_failures']:<10} "
              f"{h['num_critical']:<10} {h.get('patches_applied', 0):<10} "
              f"{h.get('elapsed_seconds', 0):<10.1f} {status}")
    print(f"{'═' * 70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Plan D — Custom Python Orchestrator for Testing→Fixing cycle",
    )
    parser.add_argument("--suite", default="all",
                        help="Test suite to run (default: all)")
    parser.add_argument("--max-iter", type=int, default=MAX_ITERATIONS,
                        help=f"Maximum iterations (default: {MAX_ITERATIONS})")
    parser.add_argument("--target", type=float, default=TARGET_PASS_RATE,
                        help=f"Target pass rate %% (default: {TARGET_PASS_RATE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run tests only, do not generate or apply patches")
    args = parser.parse_args()

    run_cycle(
        suite=args.suite,
        max_iterations=args.max_iter,
        target=args.target,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
