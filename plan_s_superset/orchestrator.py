"""
Plan S — Superset.sh Hybrid Orchestrator.

Uses Superset's MCP API for workspace isolation and Claude Code OAuth,
while implementing the cyclic testing→fixing→re-testing loop externally.

Architecture:
    This script (the orchestrator)
        │
        ├── Creates a Superset workspace (isolated Git worktree)
        │
        ├── LOOP:
        │   ├── Launch Claude Code session → "run testing agent, report failures"
        │   ├── Wait for completion, read test results from worktree
        │   ├── Check convergence (pass rate, critical failures)
        │   ├── If not converged:
        │   │   ├── Launch Claude Code session → "fix these failures in the codebase"
        │   │   ├── Wait for completion
        │   │   └── Continue loop
        │   └── If converged: break
        │
        └── Print final report

Both sessions run in the SAME workspace (same worktree, same branch)
so the fixer's patches are visible to the next test run.

Superset provides:
    - Git worktree isolation (no risk to main branch)
    - Claude Code OAuth authentication
    - Terminal session management and monitoring
    - Built-in diff viewer for reviewing all changes at the end

This script provides:
    - Cyclic loop logic (what Superset lacks)
    - Convergence detection
    - Result parsing and routing between agents
    - Iteration history and artifacts

Usage:
    python orchestrator.py                          # Full cycle
    python orchestrator.py --suite smoke            # Quick cycle
    python orchestrator.py --max-iter 3             # Limit iterations
    python orchestrator.py --target 99.0            # Pass rate target
    python orchestrator.py --dry-run                # Test once, no fixes

Prerequisites:
    - Superset.sh desktop app running locally
    - SUPERSET_API_KEY env var set (sk_live_... format)
    - SUPERSET_PROJECT_ID env var set
    - Claude Code authenticated inside Superset
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    TESTING_AGENT_ROOT,
    FINANCIAL_AGENT_ROOT,
    ARTIFACTS_DIR,
    MAX_ITERATIONS,
    TARGET_PASS_RATE,
    TARGET_ZERO_CRITICAL,
    TEST_SUITE,
)
from superset_client import SupersetClient


# ═════════════════════════════════════════════════════════════════════════
# PROMPT TEMPLATES
# ═════════════════════════════════════════════════════════════════════════

def _build_test_prompt(suite: str, iteration: int) -> str:
    """Build the prompt for the Testing Agent Claude Code session."""
    return f"""You are a QA Testing Agent. Run the Financial Agent test suite and report results.

## Instructions
1. Navigate to the Testing Agent directory
2. Run: python testing_agent.py --direct --suite {suite}
3. After tests complete, read the generated test report and qa_results_all.json
4. Summarize the results in this EXACT JSON format (output ONLY this JSON, nothing else):

```json
{{
  "iteration": {iteration},
  "pass_rate": <number>,
  "total": <number>,
  "passed": <number>,
  "failed": <number>,
  "errors": <number>,
  "failures": [
    {{
      "suite": "<suite>",
      "command": "<command>",
      "check": "<check description>",
      "notes": "<failure notes>",
      "severity": "<critical|high|normal|low>"
    }}
  ],
  "critical_failures": [<same format, only critical/high severity>]
}}
```

5. Save this JSON to: plan_s_superset/artifacts/iteration_{iteration}/test_results.json

Be precise. Report ALL failures, not just a summary."""


def _build_fix_prompt(failures_json: str, iteration: int) -> str:
    """Build the prompt for the Financial Fixer Claude Code session."""
    return f"""You are a Senior Financial Software Engineer. Fix the test failures listed below.

## Rules
- Only fix what the tests report as broken. Do NOT refactor or add features.
- Keep patches minimal (1-5 lines preferred).
- Read the source file BEFORE modifying it.
- If a failure is caused by external data (API down, stale CSV), skip it.
- After fixing, run a quick verification if possible.

## Test Failures (Iteration {iteration})

{failures_json}

## Instructions
1. For each failure, identify the relevant source file in the Financial Agent tools/ directory
2. Read the file, understand the bug
3. Apply the minimal fix
4. After all fixes, save a summary to: plan_s_superset/artifacts/iteration_{iteration}/fix_summary.json

Format:
```json
{{
  "iteration": {iteration},
  "patches_applied": <number>,
  "patches": [
    {{"file": "<path>", "description": "<what you fixed>"}}
  ],
  "skipped": [
    {{"check": "<failure>", "reason": "<why skipped>"}}
  ]
}}
```"""


# ═════════════════════════════════════════════════════════════════════════
# RESULT PARSING
# ═════════════════════════════════════════════════════════════════════════

def _read_test_results(iteration: int) -> dict | None:
    """Read test results saved by the Claude Code testing session.

    The testing session is instructed to save results to a known path.
    Falls back to parsing qa_results_all.json if the agent didn't follow
    the exact save instruction.
    """
    # Primary: look for the structured JSON saved by the agent
    results_path = ARTIFACTS_DIR / f"iteration_{iteration}" / "test_results.json"
    if results_path.exists():
        try:
            return json.loads(results_path.read_text())
        except json.JSONDecodeError:
            pass

    # Fallback: parse qa_results_all.json directly
    qa_json = TESTING_AGENT_ROOT / "qa_results_all.json"
    if not qa_json.exists():
        return None

    try:
        rows = json.loads(qa_json.read_text())
    except json.JSONDecodeError:
        return None

    total = len(rows)
    passed = sum(1 for r in rows if len(r) >= 4 and r[3] == "PASS")
    failed = sum(1 for r in rows if len(r) >= 4 and r[3] == "FAIL")
    errors = sum(1 for r in rows if len(r) >= 4 and r[3] == "ERROR")
    pass_rate = round(passed / total * 100, 1) if total > 0 else 0

    failures = []
    critical = []
    for row in rows:
        if len(row) >= 6 and row[3] in ("FAIL", "ERROR"):
            entry = {
                "suite": row[0], "command": row[1], "check": row[2],
                "status": row[3], "notes": row[4], "severity": row[5],
            }
            failures.append(entry)
            if row[5] in ("critical", "high"):
                critical.append(entry)

    return {
        "iteration": iteration,
        "pass_rate": pass_rate,
        "total": total, "passed": passed, "failed": failed, "errors": errors,
        "failures": failures,
        "critical_failures": critical,
    }


def _is_converged(results: dict) -> bool:
    """Check if test results meet convergence criteria."""
    rate_ok = results.get("pass_rate", 0) >= TARGET_PASS_RATE
    critical_ok = (not TARGET_ZERO_CRITICAL) or len(results.get("critical_failures", [])) == 0
    return rate_ok and critical_ok


# ═════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION LOOP
# ═════════════════════════════════════════════════════════════════════════

def run_cycle(suite: str, max_iterations: int, target: float, dry_run: bool):
    """Execute the Superset-mediated testing→fixing cycle."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'═' * 70}")
    print(f"  PLAN S — Superset.sh Hybrid Orchestrator")
    print(f"  Run ID:       {run_id}")
    print(f"  Suite:        {suite}")
    print(f"  Max iter:     {max_iterations}")
    print(f"  Target rate:  {target}%")
    print(f"  Dry run:      {dry_run}")
    print(f"{'═' * 70}")

    # ── Initialize Superset client ───────────────────────────────────
    try:
        client = SupersetClient()
    except ValueError as e:
        print(f"\n  ERROR: {e}")
        print(f"  Set SUPERSET_API_KEY and SUPERSET_PROJECT_ID env vars.")
        print(f"  Get your API key from Superset.sh Settings > API Keys")
        return

    # ── Create workspace ─────────────────────────────────────────────
    ws_name = f"qa-cycle-{run_id}"
    print(f"\n  Creating Superset workspace: {ws_name}")
    try:
        workspace = client.create_workspace(ws_name)
        print(f"  Workspace ID: {workspace.workspace_id}")
        print(f"  Branch: {workspace.branch}")
        print(f"  Path: {workspace.path}")
    except Exception as e:
        print(f"  ERROR: Failed to create workspace: {e}")
        print(f"  Make sure Superset.sh is running and the project is configured.")
        return

    history: list[dict] = []

    for iteration in range(1, max_iterations + 1):
        iter_start = time.time()
        iter_dir = ARTIFACTS_DIR / f"iteration_{iteration}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'━' * 60}")
        print(f"  [Superset] ITERATION {iteration}/{max_iterations}")
        print(f"{'━' * 60}")

        # ── Phase 1: Launch Testing Agent via Claude Code ────────────
        print(f"\n  Phase 1: Launching Testing Agent (Claude Code session)...")
        test_prompt = _build_test_prompt(suite, iteration)

        try:
            test_session = client.launch_agent_session(
                workspace_id=workspace.workspace_id,
                agent_type="claude",
                task_prompt=test_prompt,
            )
            print(f"  Session ID: {test_session.session_id}")

            # Wait for completion
            print(f"  Waiting for testing to complete...")
            test_status = client.wait_for_session(test_session.session_id)
            print(f"  Testing session status: {test_status}")

        except Exception as e:
            print(f"  ERROR: Testing session failed: {e}")
            history.append({
                "iteration": iteration,
                "pass_rate": 0, "error": str(e),
                "elapsed_seconds": round(time.time() - iter_start, 1),
            })
            break

        # ── Phase 2: Read and evaluate results ───────────────────────
        print(f"\n  Phase 2: Reading test results...")
        results = _read_test_results(iteration)

        if not results:
            print(f"  WARNING: Could not read test results. Stopping.")
            history.append({
                "iteration": iteration,
                "pass_rate": 0, "error": "Could not parse results",
                "elapsed_seconds": round(time.time() - iter_start, 1),
            })
            break

        pr = results.get("pass_rate", 0)
        nf = len(results.get("failures", []))
        nc = len(results.get("critical_failures", []))
        print(f"  Results: {pr}% pass rate | {nf} failures | {nc} critical")

        iter_record = {
            "iteration": iteration,
            "pass_rate": pr,
            "total": results.get("total", 0),
            "failures": nf,
            "critical": nc,
            "patches_applied": 0,
            "converged": False,
            "elapsed_seconds": 0,
        }

        # Save results artifact
        (iter_dir / "test_results.json").write_text(json.dumps(results, indent=2))

        # ── Convergence check ────────────────────────────────────────
        if _is_converged(results):
            iter_record["converged"] = True
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            print(f"\n  CONVERGED at iteration {iteration}! ({pr}% >= {target}%)")
            break

        if dry_run:
            print(f"\n  [Dry run] Stopping after test phase.")
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            break

        # ── Phase 3: Launch Financial Fixer via Claude Code ──────────
        print(f"\n  Phase 3: Launching Financial Fixer (Claude Code session)...")

        # Prioritize critical failures
        failures_to_fix = results.get("critical_failures", []) + [
            f for f in results.get("failures", [])
            if f not in results.get("critical_failures", [])
        ]
        failures_json = json.dumps(failures_to_fix[:30], indent=2)
        fix_prompt = _build_fix_prompt(failures_json, iteration)

        try:
            fix_session = client.launch_agent_session(
                workspace_id=workspace.workspace_id,
                agent_type="claude",
                task_prompt=fix_prompt,
            )
            print(f"  Session ID: {fix_session.session_id}")

            print(f"  Waiting for fixes to complete...")
            fix_status = client.wait_for_session(fix_session.session_id)
            print(f"  Fix session status: {fix_status}")

        except Exception as e:
            print(f"  ERROR: Fix session failed: {e}")
            iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
            history.append(iter_record)
            break

        iter_record["elapsed_seconds"] = round(time.time() - iter_start, 1)
        history.append(iter_record)

        print(f"\n  Iteration {iteration} complete. Continuing to next cycle...")

    # ── Final report ─────────────────────────────────────────────────
    _save_run_summary(run_id, history)
    _print_final_report(history, run_id)

    # Remind user to review in Superset
    print(f"\n  Open Superset.sh to review all changes in workspace '{ws_name}'.")
    print(f"  Use the built-in diff viewer to inspect patches, then merge or discard.\n")


def _save_run_summary(run_id: str, history: list[dict]):
    """Save run summary."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"run_{run_id}.json"
    path.write_text(json.dumps({
        "run_id": run_id,
        "framework": "superset.sh",
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
    print(f"  SUPERSET ORCHESTRATION COMPLETE — Run {run_id}")
    print(f"{'═' * 70}")
    print(f"  {'Iter':<6} {'Pass Rate':<12} {'Failures':<10} {'Critical':<10} "
          f"{'Time':<10} {'Status'}")
    print(f"  {'─' * 58}")
    for h in history:
        status = "CONVERGED" if h.get("converged") else "CONTINUE"
        if h == history[-1] and not h.get("converged"):
            status = "STOPPED"
        print(f"  {h['iteration']:<6} {h.get('pass_rate', 0):<12.1f} "
              f"{h.get('failures', 0):<10} {h.get('critical', 0):<10} "
              f"{h.get('elapsed_seconds', 0):<10.1f} {status}")
    print(f"{'═' * 70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Plan S — Superset.sh Hybrid Orchestrator",
    )
    parser.add_argument("--suite", default="all",
                        help="Test suite (default: all)")
    parser.add_argument("--max-iter", type=int, default=MAX_ITERATIONS,
                        help=f"Maximum iterations (default: {MAX_ITERATIONS})")
    parser.add_argument("--target", type=float, default=TARGET_PASS_RATE,
                        help=f"Target pass rate %% (default: {TARGET_PASS_RATE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run tests once only, no fixes")
    args = parser.parse_args()

    run_cycle(
        suite=args.suite,
        max_iterations=args.max_iter,
        target=args.target,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
