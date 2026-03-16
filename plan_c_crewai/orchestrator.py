"""
Plan C — CrewAI Role-Based Team Orchestrator.

Uses CrewAI's Crew and Agent abstractions to orchestrate the cycle:

    QA Orchestrator (manager)
        ├── delegates "run tests" to Testing Specialist
        ├── delegates "fix failures" to Financial Engineer
        └── evaluates progress, decides whether to iterate

The outer loop is in Python (not the LLM), ensuring deterministic cycle
control. Within each iteration, CrewAI agents reason autonomously.

Usage:
    python orchestrator.py                          # Full cycle
    python orchestrator.py --suite smoke            # Quick cycle
    python orchestrator.py --max-iter 3             # Limit iterations
    python orchestrator.py --target 99.0            # Pass rate target
    python orchestrator.py --dry-run                # Test once, no fixes
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure plan_c_crewai is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crewai import Crew, Process

from agents import (
    create_qa_orchestrator,
    create_testing_specialist,
    create_financial_engineer,
)
from tasks import (
    create_run_tests_task,
    create_fix_failures_task,
    create_evaluate_progress_task,
)
from config import (
    FINANCIAL_AGENT_ROOT,
    ARTIFACTS_DIR,
    MAX_ITERATIONS,
    TARGET_PASS_RATE,
    GIT_AUTO_BRANCH,
    GIT_BRANCH_PREFIX,
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


def _extract_pass_rate(crew_output) -> float:
    """Try to extract pass_rate from CrewAI task output."""
    try:
        raw = str(crew_output)
        # Try JSON parsing
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    if "pass_rate" in data:
                        return float(data["pass_rate"])
                    if "current_pass_rate" in data:
                        return float(data["current_pass_rate"])
                except (json.JSONDecodeError, ValueError):
                    pass

        # Fallback: regex for "pass_rate": XX.X or XX.X%
        import re
        match = re.search(r'"?pass_rate"?\s*[:=]\s*(\d+\.?\d*)', raw)
        if match:
            return float(match.group(1))
        match = re.search(r'(\d+\.?\d*)%?\s*pass\s*rate', raw, re.IGNORECASE)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return 0.0


def _should_continue(crew_output) -> bool:
    """Try to extract the continue decision from the orchestrator's evaluation."""
    try:
        raw = str(crew_output)
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    if "continue" in data:
                        return bool(data["continue"])
                except (json.JSONDecodeError, ValueError):
                    pass
        # Fallback: look for keywords
        lower = raw.lower()
        if "continue: true" in lower or '"continue": true' in lower:
            return True
        if "continue: false" in lower or '"continue": false' in lower:
            return False
    except Exception:
        pass
    return False


def _save_iteration_artifacts(iteration: int, test_output, fix_output, eval_output):
    """Save CrewAI outputs for each iteration."""
    iter_dir = ARTIFACTS_DIR / f"iteration_{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    (iter_dir / "test_output.txt").write_text(str(test_output))
    if fix_output:
        (iter_dir / "fix_output.txt").write_text(str(fix_output))
    if eval_output:
        (iter_dir / "eval_output.txt").write_text(str(eval_output))


def run_cycle(suite: str, max_iterations: int, target: float, dry_run: bool):
    """Execute the CrewAI orchestration cycle."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'═' * 70}")
    print(f"  PLAN C — CrewAI Role-Based Team")
    print(f"  Run ID:       {run_id}")
    print(f"  Suite:        {suite}")
    print(f"  Max iter:     {max_iterations}")
    print(f"  Target rate:  {target}%")
    print(f"  Dry run:      {dry_run}")
    print(f"  FA root:      {FINANCIAL_AGENT_ROOT}")
    print(f"{'═' * 70}")

    # Create agents
    qa_lead = create_qa_orchestrator()
    tester = create_testing_specialist()
    engineer = create_financial_engineer()

    # Create safety branch
    if not dry_run:
        _create_git_branch(run_id)

    history: list[dict] = []

    for iteration in range(1, max_iterations + 1):
        iter_start = time.time()

        print(f"\n{'━' * 60}")
        print(f"  [CrewAI] ITERATION {iteration}/{max_iterations}")
        print(f"{'━' * 60}")

        # ── Phase 1: Run tests ───────────────────────────────────────
        test_task = create_run_tests_task(
            agent=tester,
            suite=suite,
            iteration=iteration,
        )

        test_crew = Crew(
            agents=[tester],
            tasks=[test_task],
            process=Process.sequential,
            verbose=True,
        )

        print(f"\n  Phase 1: Running tests...")
        test_output = test_crew.kickoff()

        pass_rate = _extract_pass_rate(test_output)
        print(f"\n  Test results: {pass_rate}% pass rate")

        iter_record = {
            "iteration": iteration,
            "pass_rate": pass_rate,
            "patches_applied": 0,
            "converged": False,
            "elapsed_seconds": 0,
        }

        # Check convergence
        if pass_rate >= target:
            iter_record["converged"] = True
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            _save_iteration_artifacts(iteration, test_output, None, None)
            print(f"\n  CONVERGED at iteration {iteration}! ({pass_rate}% >= {target}%)")
            break

        if dry_run:
            print(f"\n  [Dry run] Stopping after test phase.")
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            _save_iteration_artifacts(iteration, test_output, None, None)
            break

        # ── Phase 2: Fix failures ────────────────────────────────────
        fix_task = create_fix_failures_task(
            agent=engineer,
            iteration=iteration,
            context_tasks=[test_task],
        )

        fix_crew = Crew(
            agents=[engineer],
            tasks=[fix_task],
            process=Process.sequential,
            verbose=True,
        )

        print(f"\n  Phase 2: Fixing failures...")
        fix_output = fix_crew.kickoff()
        print(f"\n  Fix phase complete.")

        # ── Phase 3: Evaluate progress ───────────────────────────────
        eval_task = create_evaluate_progress_task(
            agent=qa_lead,
            iteration=iteration,
            target_pass_rate=target,
            max_iterations=max_iterations,
            context_tasks=[test_task, fix_task],
        )

        eval_crew = Crew(
            agents=[qa_lead],
            tasks=[eval_task],
            process=Process.sequential,
            verbose=True,
        )

        print(f"\n  Phase 3: Evaluating progress...")
        eval_output = eval_crew.kickoff()

        should_continue = _should_continue(eval_output)
        print(f"\n  Orchestrator decision: {'CONTINUE' if should_continue else 'STOP'}")

        iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
        history.append(iter_record)
        _save_iteration_artifacts(iteration, test_output, fix_output, eval_output)

        if not should_continue:
            print(f"\n  QA Orchestrator decided to stop.")
            break

        print(f"\n  Continuing to iteration {iteration + 1}...")

    # ── Final report ─────────────────────────────────────────────────
    _save_run_summary(run_id, history)
    _print_final_report(history, run_id)


def _save_run_summary(run_id: str, history: list[dict]):
    """Save run summary."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"run_{run_id}.json"
    path.write_text(json.dumps({
        "run_id": run_id,
        "finished": datetime.now().isoformat(),
        "iterations": len(history),
        "history": history,
        "final_pass_rate": history[-1]["pass_rate"] if history else 0,
        "converged": history[-1].get("converged", False) if history else False,
    }, indent=2))
    print(f"\n  Run summary: {path}")


def _print_final_report(history: list[dict], run_id: str):
    """Print summary."""
    print(f"\n{'═' * 70}")
    print(f"  CREWAI ORCHESTRATION COMPLETE — Run {run_id}")
    print(f"{'═' * 70}")
    print(f"  {'Iter':<6} {'Pass Rate':<12} {'Patches':<10} {'Time':<10} {'Status'}")
    print(f"  {'─' * 48}")
    for h in history:
        status = "CONVERGED" if h.get("converged") else "CONTINUE"
        if h == history[-1] and not h.get("converged"):
            status = "STOPPED"
        print(f"  {h['iteration']:<6} {h['pass_rate']:<12.1f} "
              f"{h.get('patches_applied', 0):<10} "
              f"{h.get('elapsed_seconds', 0):<10.1f} {status}")
    print(f"{'═' * 70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Plan C — CrewAI Role-Based Team Orchestrator",
    )
    parser.add_argument("--suite", default="all",
                        help="Test suite (default: all)")
    parser.add_argument("--max-iter", type=int, default=MAX_ITERATIONS,
                        help=f"Maximum iterations (default: {MAX_ITERATIONS})")
    parser.add_argument("--target", type=float, default=TARGET_PASS_RATE,
                        help=f"Target pass rate %% (default: {TARGET_PASS_RATE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run tests once only, no patches")
    args = parser.parse_args()

    run_cycle(
        suite=args.suite,
        max_iterations=args.max_iter,
        target=args.target,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
