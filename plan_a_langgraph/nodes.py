"""
Plan A — LangGraph Node definitions.

Three nodes that form the cycle:
    testing_node  →  router_node  →  fixer_node  →  (back to testing_node)

Each node is a pure function: (PipelineState) -> partial PipelineState update.
LangGraph merges the returned dict into the running state automatically.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from state import PipelineState, FailureRecord, PatchRecord, IterationSnapshot
from config import (
    TESTING_AGENT_ROOT,
    FINANCIAL_AGENT_ROOT,
    TOOLS_DIR,
    ARTIFACTS_DIR,
    TEST_TIMEOUT_SECONDS,
    TARGET_PASS_RATE,
    TARGET_ZERO_CRITICAL,
    FIXER_TEMPERATURE,
)


# ═════════════════════════════════════════════════════════════════════════
# NODE 1: TESTING NODE
# ═════════════════════════════════════════════════════════════════════════

def testing_node(state: PipelineState) -> dict:
    """Run the Testing Agent and parse results into state.

    Reads: iteration, suite
    Writes: pass_rate, total_tests, passed_tests, failed_tests, error_tests,
            failures, critical_failures, report_path, raw_json_path, history
    """
    iteration = state["iteration"]
    suite = state.get("suite", "all")

    print(f"\n{'━' * 60}")
    print(f"  [LangGraph] TESTING NODE — Iteration {iteration}  (suite={suite})")
    print(f"{'━' * 60}")

    cmd = [
        sys.executable,
        str(TESTING_AGENT_ROOT / "testing_agent.py"),
        "--direct",
        "--suite", suite,
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(TESTING_AGENT_ROOT),
            capture_output=True, text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )

        # Print tail of stdout
        for line in (proc.stdout or "").strip().splitlines()[-6:]:
            print(f"  {line}")

        if proc.returncode != 0:
            print(f"  WARNING: exit code {proc.returncode}")

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error_message": f"Testing Agent timed out after {TEST_TIMEOUT_SECONDS}s",
        }

    # ── Parse outputs ────────────────────────────────────────────────
    update: dict = {}

    # Find latest report
    reports = sorted(
        TESTING_AGENT_ROOT.glob("test_report_*.md"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if reports:
        update["report_path"] = str(reports[0])
        _parse_report(update, reports[0].read_text())

    # Parse JSON failures
    qa_json = TESTING_AGENT_ROOT / "qa_results_all.json"
    if qa_json.exists():
        update["raw_json_path"] = str(qa_json)
        _parse_json_failures(update, json.loads(qa_json.read_text()))

    # Archive artifacts
    _archive(iteration, update)

    # Build history snapshot (using Annotated[..., add] for auto-append)
    snapshot: IterationSnapshot = {
        "iteration": iteration,
        "pass_rate": update.get("pass_rate", 0.0),
        "total": update.get("total_tests", 0),
        "passed": update.get("passed_tests", 0),
        "failed": update.get("failed_tests", 0),
        "num_critical": len(update.get("critical_failures", [])),
        "patches_applied": 0,
        "analysis": "",
    }
    update["history"] = [snapshot]

    pr = update.get("pass_rate", 0)
    nf = len(update.get("failures", []))
    nc = len(update.get("critical_failures", []))
    print(f"  Result: {pr}% pass rate | {nf} failures | {nc} critical")

    return update


# ═════════════════════════════════════════════════════════════════════════
# NODE 2: ROUTER NODE (conditional edge logic)
# ═════════════════════════════════════════════════════════════════════════

def router_node(state: PipelineState) -> str:
    """Decide whether to continue fixing or stop.

    This is used as a conditional edge function in the graph.
    Returns: "fix" to go to fixer_node, or "done" to end.
    """
    # Error state → stop
    if state.get("status") == "error":
        return "done"

    # Convergence check
    rate_ok = state.get("pass_rate", 0) >= state.get("target_pass_rate", TARGET_PASS_RATE)
    critical_ok = (not TARGET_ZERO_CRITICAL) or len(state.get("critical_failures", [])) == 0

    if rate_ok and critical_ok:
        print(f"\n  [Router] CONVERGED: {state['pass_rate']}% >= {state['target_pass_rate']}%")
        return "done"

    # Max iterations check
    if state["iteration"] >= state["max_iterations"]:
        print(f"\n  [Router] MAX ITERATIONS reached ({state['max_iterations']})")
        return "done"

    # No failures to fix
    if not state.get("failures"):
        print(f"\n  [Router] No failures to fix. Stopping.")
        return "done"

    print(f"\n  [Router] Not converged ({state['pass_rate']}% < {state['target_pass_rate']}%). "
          f"Routing to fixer.")
    return "fix"


# ═════════════════════════════════════════════════════════════════════════
# NODE 3: FIXER NODE
# ═════════════════════════════════════════════════════════════════════════

FIXER_SYSTEM_PROMPT = """You are a senior financial software engineer. You receive QA test failures
from a Financial Analysis Agent and produce MINIMAL, TARGETED code patches to fix them.

## Rules
1. Only fix what the test failures explicitly describe. Do NOT refactor or add features.
2. Return patches as a JSON array of objects, each with:
   - "file": relative path from the Financial Agent root (e.g., "tools/macro_data.py")
   - "description": one-line description of the fix
   - "old_code": the EXACT code to replace (must be a unique substring of the file)
   - "new_code": the replacement code
3. If a failure is caused by external data (API down, stale CSV), return empty patches and explain.
4. Keep patches as small as possible. Prefer 1-5 line changes.
5. NEVER introduce new dependencies or change function signatures.

## Response format (JSON only):
{
  "analysis": "Brief analysis of failures and root causes",
  "patches": [{"file": "...", "description": "...", "old_code": "...", "new_code": "..."}],
  "skipped_failures": [{"check": "...", "reason": "..."}]
}
"""


def fixer_node(state: PipelineState) -> dict:
    """Generate and apply code patches based on test failures.

    Reads: failures, critical_failures, all_patches, iteration
    Writes: latest_patches, latest_analysis, all_patches, iteration (incremented),
            status (if no patches possible)
    """
    iteration = state["iteration"]
    failures = state.get("critical_failures", []) + [
        f for f in state.get("failures", [])
        if f not in state.get("critical_failures", [])
    ]

    print(f"\n{'━' * 60}")
    print(f"  [LangGraph] FIXER NODE — Iteration {iteration}")
    print(f"  Failures to fix: {len(failures)}")
    print(f"{'━' * 60}")

    # ── Call the LLM ─────────────────────────────────────────────────
    client, model = _get_llm_client()

    user_prompt = _build_fixer_prompt(failures, iteration, state.get("all_patches", []))

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=FIXER_TEMPERATURE,
            messages=[
                {"role": "system", "content": FIXER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=8192,
        )
        raw = response.choices[0].message.content.strip()
        json_str = _extract_json(raw)
        result = json.loads(json_str)
    except Exception as e:
        print(f"  ERROR: LLM call failed: {e}")
        return {
            "status": "stopped",
            "latest_analysis": f"LLM error: {e}",
            "latest_patches": [],
            "iteration": iteration + 1,
        }

    analysis = result.get("analysis", "")
    patches = result.get("patches", [])
    print(f"  Analysis: {analysis[:120]}")
    print(f"  Patches proposed: {len(patches)}")

    if not patches:
        return {
            "status": "stopped",
            "latest_analysis": analysis,
            "latest_patches": [],
            "iteration": iteration + 1,
        }

    # ── Apply patches ────────────────────────────────────────────────
    applied_patches: list[PatchRecord] = []
    for i, p in enumerate(patches):
        file_path = FINANCIAL_AGENT_ROOT / p.get("file", "")
        old_code = p.get("old_code", "")
        new_code = p.get("new_code", "")

        if not file_path.exists() or not old_code or not new_code:
            print(f"  [{i+1}] SKIP: invalid patch for {p.get('file', '?')}")
            continue

        content = file_path.read_text()
        if content.count(old_code) != 1:
            print(f"  [{i+1}] SKIP: old_code not uniquely found in {p['file']}")
            continue

        file_path.write_text(content.replace(old_code, new_code, 1))
        record: PatchRecord = {
            "file": p["file"],
            "description": p.get("description", ""),
            "old_code": old_code,
            "new_code": new_code,
            "applied": True,
            "iteration": iteration,
        }
        applied_patches.append(record)
        print(f"  [{i+1}] APPLIED: {p.get('description', '')} ({p['file']})")

    # Git commit
    if applied_patches:
        _git_commit(iteration, len(applied_patches))

    # Save patch artifacts
    iter_dir = ARTIFACTS_DIR / f"iteration_{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "patches.json").write_text(json.dumps({
        "analysis": analysis,
        "proposed": patches,
        "applied": [p for p in applied_patches],
    }, indent=2))

    if not applied_patches:
        return {
            "status": "stopped",
            "latest_analysis": analysis,
            "latest_patches": [],
            "iteration": iteration + 1,
        }

    return {
        "latest_patches": applied_patches,
        "latest_analysis": analysis,
        "all_patches": state.get("all_patches", []) + applied_patches,
        "iteration": iteration + 1,
        "status": "running",
    }


# ═════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════

def _get_llm_client() -> tuple[OpenAI, str]:
    """Build OpenAI client from Financial Agent config."""
    sys.path.insert(0, str(FINANCIAL_AGENT_ROOT))
    from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL

    fixer_key = os.environ.get("FIXER_API_KEY", "") or LLM_API_KEY
    fixer_url = os.environ.get("FIXER_BASE_URL", "") or LLM_BASE_URL
    fixer_model = os.environ.get("FIXER_MODEL", "") or LLM_MODEL

    return OpenAI(api_key=fixer_key, base_url=fixer_url), fixer_model


def _parse_report(update: dict, text: str):
    """Extract summary metrics from the markdown report."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| Total Tests"):
            v = line.split("|")[2].strip()
            update["total_tests"] = int(v) if v.isdigit() else 0
        elif line.startswith("| Passed"):
            v = line.split("|")[2].strip()
            update["passed_tests"] = int(v) if v.isdigit() else 0
        elif line.startswith("| Failed"):
            v = line.split("|")[2].strip()
            update["failed_tests"] = int(v) if v.isdigit() else 0
        elif line.startswith("| Errors"):
            v = line.split("|")[2].strip()
            update["error_tests"] = int(v) if v.isdigit() else 0
        elif line.startswith("| Pass Rate"):
            v = line.split("|")[2].strip().rstrip("%")
            try:
                update["pass_rate"] = float(v)
            except ValueError:
                pass


def _parse_json_failures(update: dict, rows: list):
    """Extract failures from qa_results_all.json rows."""
    failures: list[FailureRecord] = []
    critical: list[FailureRecord] = []
    for row in rows:
        if len(row) < 6:
            continue
        suite, command, check, status, notes, severity = row[:6]
        if status in ("FAIL", "ERROR"):
            rec: FailureRecord = {
                "suite": suite, "command": command, "check": check,
                "status": status, "notes": notes, "severity": severity,
            }
            failures.append(rec)
            if severity in ("critical", "high"):
                critical.append(rec)

    update["failures"] = failures
    update["critical_failures"] = critical

    # Recalculate if report parsing missed
    if not update.get("total_tests") and rows:
        update["total_tests"] = len(rows)
        update["passed_tests"] = sum(1 for r in rows if len(r) >= 4 and r[3] == "PASS")
        update["failed_tests"] = sum(1 for r in rows if len(r) >= 4 and r[3] == "FAIL")
        update["error_tests"] = sum(1 for r in rows if len(r) >= 4 and r[3] == "ERROR")
        t = update["total_tests"]
        if t > 0:
            update["pass_rate"] = round(update["passed_tests"] / t * 100, 1)


def _archive(iteration: int, update: dict):
    """Archive iteration artifacts."""
    iter_dir = ARTIFACTS_DIR / f"iteration_{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    rp = update.get("report_path", "")
    if rp and Path(rp).exists():
        (iter_dir / f"test_report.md").write_text(Path(rp).read_text())

    jp = update.get("raw_json_path", "")
    if jp and Path(jp).exists():
        (iter_dir / f"qa_results.json").write_text(Path(jp).read_text())

    summary = {
        "iteration": iteration,
        "pass_rate": update.get("pass_rate", 0),
        "total": update.get("total_tests", 0),
        "passed": update.get("passed_tests", 0),
        "failed": update.get("failed_tests", 0),
        "num_failures": len(update.get("failures", [])),
        "num_critical": len(update.get("critical_failures", [])),
    }
    (iter_dir / "summary.json").write_text(json.dumps(summary, indent=2))


def _build_fixer_prompt(
    failures: list[FailureRecord],
    iteration: int,
    previous_patches: list[PatchRecord],
) -> str:
    """Build the user prompt for the fixer LLM."""
    parts = [f"## Iteration {iteration}\n",
             f"The QA Testing Agent found {len(failures)} failures.\n"]

    if previous_patches:
        parts.append("## Previously Applied Patches (do NOT repeat these)")
        for p in previous_patches:
            parts.append(f"- {p.get('file', '?')}: {p.get('description', '?')}")
        parts.append("")

    parts.append("## Test Failures\n")
    for i, f in enumerate(failures[:30], 1):
        parts.append(
            f"{i}. [{f.get('severity', 'normal').upper()}] "
            f"Suite={f['suite']} | Cmd={f['command']} | Check: {f['check']}\n"
            f"   Notes: {f.get('notes', 'none')}"
        )
    parts.append("")

    # Attach relevant source
    relevant = _relevant_files(failures)
    parts.append("## Relevant Source Code\n")
    for rel_path in relevant[:5]:
        abs_path = FINANCIAL_AGENT_ROOT / rel_path
        if abs_path.exists():
            content = abs_path.read_text()
            if len(content) > 12000:
                content = content[:12000] + "\n... (truncated)"
            parts.append(f"### {rel_path}\n```python\n{content}\n```\n")

    return "\n".join(parts)


def _relevant_files(failures: list[FailureRecord]) -> list[str]:
    """Map suite names to source files."""
    mapping = {
        "macro": "tools/macro_data.py",
        "equity": "tools/equity_analysis.py",
        "fred": "tools/fred_data.py",
        "regime": "tools/macro_market_analysis.py",
        "ta": "tools/murphy_ta.py",
        "commodity": "tools/commodity_analysis.py",
        "valuation": "tools/graham_analysis.py",
        "protrader": "tools/protrader_frameworks.py",
        "btc": "tools/btc_analysis.py",
        "web": "tools/web_search.py",
        "synthesis": "tools/macro_synthesis.py",
        "consumer": "tools/consumer_housing_analysis.py",
    }
    files = set()
    for f in failures:
        s = f.get("suite", "").lower()
        for key, path in mapping.items():
            if key in s:
                files.add(path)
                break
    return sorted(files)


def _git_commit(iteration: int, num_patches: int):
    """Commit applied patches."""
    try:
        subprocess.run(["git", "add", "-A"],
                       cwd=str(FINANCIAL_AGENT_ROOT), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m",
             f"langgraph-orch: iter {iteration} — {num_patches} patches"],
            cwd=str(FINANCIAL_AGENT_ROOT), capture_output=True, check=True)
        print(f"  Git commit for iteration {iteration}")
    except subprocess.CalledProcessError:
        pass


def _extract_json(text: str) -> str:
    """Extract JSON from markdown-fenced response."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    return match.group(1).strip() if match else text
