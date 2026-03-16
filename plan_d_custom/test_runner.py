"""
Plan D — Test Runner: invokes the Testing Agent and parses results.

Wraps testing_agent.py --direct as a subprocess and parses the
structured outputs (JSON + markdown report) into a normalized format
for the orchestrator.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import (
    TESTING_AGENT_ROOT,
    TEST_SUITE,
    TEST_TIMEOUT_SECONDS,
    ARTIFACTS_DIR,
)


@dataclass
class TestRunResult:
    """Normalized result of a single testing-agent invocation."""
    iteration: int
    pass_rate: float                  # 0.0 – 100.0
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    elapsed: str = ""
    failures: list[dict] = field(default_factory=list)
    critical_failures: list[dict] = field(default_factory=list)
    report_path: str = ""
    raw_json_path: str = ""
    timestamp: str = ""
    returncode: int = 0
    stderr_snippet: str = ""


def run_tests(iteration: int, suite: str = "") -> TestRunResult:
    """Execute the Testing Agent in --direct mode and return parsed results.

    Args:
        iteration: Current cycle iteration number.
        suite: Override test suite name. Falls back to config.TEST_SUITE.

    Returns:
        TestRunResult with parsed pass/fail data and failure details.
    """
    suite = suite or TEST_SUITE
    result = TestRunResult(iteration=iteration, timestamp=datetime.now().isoformat())

    cmd = [
        sys.executable,
        str(TESTING_AGENT_ROOT / "testing_agent.py"),
        "--direct",
        "--suite", suite,
    ]

    print(f"\n{'─' * 60}")
    print(f"  [Iteration {iteration}] Running Testing Agent  (suite={suite})")
    print(f"{'─' * 60}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(TESTING_AGENT_ROOT),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
        result.returncode = proc.returncode

        if proc.returncode != 0:
            result.stderr_snippet = proc.stderr[-500:] if proc.stderr else ""
            print(f"  WARNING: testing_agent.py exited with code {proc.returncode}")
            if result.stderr_snippet:
                print(f"  stderr: {result.stderr_snippet[:200]}")

        # Print stdout tail for visibility
        stdout_lines = proc.stdout.strip().splitlines() if proc.stdout else []
        for line in stdout_lines[-8:]:
            print(f"  {line}")

    except subprocess.TimeoutExpired:
        print(f"  ERROR: Testing Agent timed out after {TEST_TIMEOUT_SECONDS}s")
        result.stderr_snippet = f"Timed out after {TEST_TIMEOUT_SECONDS}s"
        return result

    # ── Parse results ────────────────────────────────────────────────
    result = _parse_test_outputs(result)

    # ── Archive artifacts ────────────────────────────────────────────
    _archive_artifacts(result)

    return result


def _parse_test_outputs(result: TestRunResult) -> TestRunResult:
    """Parse the Testing Agent's JSON and markdown outputs."""

    # 1. Try to find the most recent test report (markdown)
    report_files = sorted(
        TESTING_AGENT_ROOT.glob("test_report_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if report_files:
        result.report_path = str(report_files[0])

    # 2. Parse summary from stdout / report
    if result.report_path:
        try:
            report_text = Path(result.report_path).read_text()
            result = _extract_summary_from_report(result, report_text)
        except Exception as e:
            print(f"  WARNING: Could not parse report: {e}")

    # 3. Parse detailed failures from the JSON results
    qa_json_path = TESTING_AGENT_ROOT / "qa_results_all.json"
    if qa_json_path.exists():
        result.raw_json_path = str(qa_json_path)
        try:
            rows = json.loads(qa_json_path.read_text())
            result = _extract_failures_from_json(result, rows)
        except Exception as e:
            print(f"  WARNING: Could not parse qa_results_all.json: {e}")

    return result


def _extract_summary_from_report(result: TestRunResult, text: str) -> TestRunResult:
    """Extract pass/fail/rate from the markdown report table."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| Total Tests"):
            val = line.split("|")[2].strip()
            result.total = int(val) if val.isdigit() else 0
        elif line.startswith("| Passed"):
            val = line.split("|")[2].strip()
            result.passed = int(val) if val.isdigit() else 0
        elif line.startswith("| Failed"):
            val = line.split("|")[2].strip()
            result.failed = int(val) if val.isdigit() else 0
        elif line.startswith("| Errors"):
            val = line.split("|")[2].strip()
            result.errors = int(val) if val.isdigit() else 0
        elif line.startswith("| Pass Rate"):
            val = line.split("|")[2].strip().rstrip("%")
            try:
                result.pass_rate = float(val)
            except ValueError:
                pass
        elif line.startswith("| Total Time"):
            result.elapsed = line.split("|")[2].strip()
    return result


def _extract_failures_from_json(result: TestRunResult, rows: list) -> TestRunResult:
    """Extract failure details from qa_results_all.json.

    Each row: [suite, command, check_name, status, notes, severity, elapsed]
    """
    failures = []
    critical = []
    for row in rows:
        if len(row) < 6:
            continue
        suite, command, check_name, status, notes, severity = row[:6]
        if status in ("FAIL", "ERROR"):
            entry = {
                "suite": suite,
                "command": command,
                "check": check_name,
                "status": status,
                "notes": notes,
                "severity": severity,
            }
            failures.append(entry)
            if severity in ("critical", "high"):
                critical.append(entry)

    result.failures = failures
    result.critical_failures = critical

    # Recalculate counts from raw data if report parsing missed them
    if result.total == 0 and rows:
        result.total = len(rows)
        result.passed = sum(1 for r in rows if len(r) >= 4 and r[3] == "PASS")
        result.failed = sum(1 for r in rows if len(r) >= 4 and r[3] == "FAIL")
        result.errors = sum(1 for r in rows if len(r) >= 4 and r[3] == "ERROR")
        if result.total > 0:
            result.pass_rate = round(result.passed / result.total * 100, 1)

    return result


def _archive_artifacts(result: TestRunResult):
    """Copy current-iteration artifacts into the artifacts directory."""
    iter_dir = ARTIFACTS_DIR / f"iteration_{result.iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    # Copy report
    if result.report_path and Path(result.report_path).exists():
        dest = iter_dir / f"test_report_iter{result.iteration}.md"
        dest.write_text(Path(result.report_path).read_text())

    # Copy JSON results
    if result.raw_json_path and Path(result.raw_json_path).exists():
        dest = iter_dir / f"qa_results_iter{result.iteration}.json"
        dest.write_text(Path(result.raw_json_path).read_text())

    # Save structured summary
    summary = {
        "iteration": result.iteration,
        "timestamp": result.timestamp,
        "pass_rate": result.pass_rate,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "errors": result.errors,
        "num_failures": len(result.failures),
        "num_critical": len(result.critical_failures),
        "critical_failures": result.critical_failures,
    }
    summary_path = iter_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"  Artifacts saved to: {iter_dir}")
