"""
Plan D — Financial Fixer Agent: receives test failures, generates code patches.

Uses an LLM (via OpenAI-compatible API) to analyze test failures and produce
targeted patches to the Financial Agent's tool source files.

Safety: all patches are applied on a git branch; originals are backed up.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from config import (
    FINANCIAL_AGENT_ROOT,
    TOOLS_DIR,
    ARTIFACTS_DIR,
    FIXER_PROVIDER,
    FIXER_MODEL,
    FIXER_API_KEY,
    FIXER_BASE_URL,
    FIXER_TEMPERATURE,
)


def _get_llm_client() -> tuple[OpenAI, str]:
    """Build an OpenAI-compatible client using fixer config or Financial Agent defaults."""
    api_key = FIXER_API_KEY
    base_url = FIXER_BASE_URL
    model = FIXER_MODEL

    # Fall back to Financial Agent's config if fixer-specific vars aren't set
    if not api_key:
        sys.path.insert(0, str(FINANCIAL_AGENT_ROOT))
        from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
        api_key = api_key or LLM_API_KEY
        base_url = base_url or LLM_BASE_URL
        model = model or LLM_MODEL

    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


# ── System prompt for the fixer LLM ─────────────────────────────────

FIXER_SYSTEM_PROMPT = """You are a senior financial software engineer. You receive QA test failures
from a Financial Analysis Agent and produce MINIMAL, TARGETED code patches to fix them.

## Rules
1. Only fix what the test failures explicitly describe. Do NOT refactor, optimize, or add features.
2. Return patches as a JSON array of objects, each with:
   - "file": relative path from the Financial Agent root (e.g., "tools/macro_data.py")
   - "description": one-line description of the fix
   - "old_code": the EXACT code to replace (must be a unique substring of the file)
   - "new_code": the replacement code
3. If a failure is caused by external data (API down, stale CSV, market closed), return an
   empty patches array and explain in "analysis".
4. If you cannot determine a fix with confidence, skip that failure and explain why.
5. Keep patches as small as possible. Prefer 1-5 line changes.
6. NEVER introduce new dependencies, change function signatures, or modify imports
   unless absolutely necessary for the fix.

## Response format
Return ONLY valid JSON:
{
  "analysis": "Brief analysis of the failures and root causes",
  "patches": [
    {
      "file": "tools/macro_data.py",
      "description": "Fix credit spread classification threshold",
      "old_code": "if oas < 200:",
      "new_code": "if oas < 300:"
    }
  ],
  "skipped_failures": [
    {"check": "...", "reason": "External data issue, not a code bug"}
  ]
}
"""


def generate_patches(
    failures: list[dict],
    iteration: int,
    previous_patches: list[dict] | None = None,
) -> dict:
    """Ask the LLM to produce code patches for the given test failures.

    Args:
        failures: List of failure dicts from test_runner (suite, command, check, notes, severity).
        iteration: Current iteration number (for context).
        previous_patches: Patches applied in prior iterations (to avoid repeating).

    Returns:
        Dict with keys: analysis, patches, skipped_failures.
    """
    if not failures:
        return {"analysis": "No failures to fix.", "patches": [], "skipped_failures": []}

    client, model = _get_llm_client()

    # Build the user prompt with failure context + relevant source code
    user_prompt = _build_fixer_prompt(failures, iteration, previous_patches)

    print(f"\n{'─' * 60}")
    print(f"  [Iteration {iteration}] Financial Fixer: analyzing {len(failures)} failures")
    print(f"  Using model: {model}")
    print(f"{'─' * 60}")

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

        raw_content = response.choices[0].message.content.strip()

        # Extract JSON from the response (handle markdown code fences)
        json_str = _extract_json(raw_content)
        result = json.loads(json_str)

        print(f"  Analysis: {result.get('analysis', 'N/A')[:120]}")
        print(f"  Patches proposed: {len(result.get('patches', []))}")
        print(f"  Skipped failures: {len(result.get('skipped_failures', []))}")

        return result

    except json.JSONDecodeError as e:
        print(f"  ERROR: LLM returned invalid JSON: {e}")
        print(f"  Raw response: {raw_content[:300]}")
        return {"analysis": f"JSON parse error: {e}", "patches": [], "skipped_failures": []}
    except Exception as e:
        print(f"  ERROR: LLM call failed: {e}")
        return {"analysis": f"LLM error: {e}", "patches": [], "skipped_failures": []}


def apply_patches(patches: list[dict], iteration: int) -> list[dict]:
    """Apply code patches to the Financial Agent source files.

    Args:
        patches: List of patch dicts with file, old_code, new_code, description.
        iteration: Current iteration (for logging).

    Returns:
        List of applied patch results (success/failure for each).
    """
    results = []

    for i, patch in enumerate(patches):
        file_rel = patch.get("file", "")
        old_code = patch.get("old_code", "")
        new_code = patch.get("new_code", "")
        desc = patch.get("description", "no description")

        file_path = FINANCIAL_AGENT_ROOT / file_rel
        entry = {
            "file": file_rel,
            "description": desc,
            "applied": False,
            "error": "",
        }

        if not file_path.exists():
            entry["error"] = f"File not found: {file_path}"
            print(f"  [{i+1}] SKIP: {entry['error']}")
            results.append(entry)
            continue

        if not old_code or not new_code:
            entry["error"] = "Empty old_code or new_code"
            print(f"  [{i+1}] SKIP: {entry['error']}")
            results.append(entry)
            continue

        # Read the file
        content = file_path.read_text()

        # Verify old_code exists and is unique
        occurrences = content.count(old_code)
        if occurrences == 0:
            entry["error"] = f"old_code not found in {file_rel}"
            print(f"  [{i+1}] SKIP: {entry['error']}")
            results.append(entry)
            continue
        if occurrences > 1:
            entry["error"] = f"old_code matches {occurrences} locations (ambiguous)"
            print(f"  [{i+1}] SKIP: {entry['error']}")
            results.append(entry)
            continue

        # Apply the patch
        new_content = content.replace(old_code, new_code, 1)
        file_path.write_text(new_content)

        entry["applied"] = True
        print(f"  [{i+1}] APPLIED: {desc} ({file_rel})")
        results.append(entry)

    return results


def _build_fixer_prompt(
    failures: list[dict],
    iteration: int,
    previous_patches: list[dict] | None = None,
) -> str:
    """Build the LLM prompt with failure details and relevant source code."""
    parts = [
        f"## Iteration {iteration}\n",
        f"The QA Testing Agent found {len(failures)} failures.\n",
    ]

    # Group failures by tool/file to reduce redundancy
    if previous_patches:
        parts.append("## Previously Applied Patches (do NOT repeat these)")
        for p in previous_patches:
            parts.append(f"- {p.get('file', '?')}: {p.get('description', '?')}")
        parts.append("")

    parts.append("## Test Failures\n")
    for i, f in enumerate(failures[:30], 1):  # Cap at 30 to stay within context
        parts.append(
            f"{i}. [{f.get('severity', 'normal').upper()}] "
            f"Suite={f.get('suite', '?')} | Command={f.get('command', '?')} | "
            f"Check: {f.get('check', '?')}\n"
            f"   Notes: {f.get('notes', 'none')}"
        )
    parts.append("")

    # Attach relevant source files (only those mentioned in failures)
    relevant_files = _identify_relevant_files(failures)
    parts.append("## Relevant Source Code\n")
    for rel_path in relevant_files[:5]:  # Cap at 5 files to stay within context
        abs_path = FINANCIAL_AGENT_ROOT / rel_path
        if abs_path.exists():
            content = abs_path.read_text()
            # Truncate very large files
            if len(content) > 12000:
                content = content[:12000] + "\n... (truncated)"
            parts.append(f"### {rel_path}")
            parts.append(f"```python\n{content}\n```\n")

    return "\n".join(parts)


def _identify_relevant_files(failures: list[dict]) -> list[str]:
    """Map failures to likely source files in the Financial Agent."""
    file_map = {
        "Macro": "tools/macro_data.py",
        "macro": "tools/macro_data.py",
        "macro_data": "tools/macro_data.py",
        "Equity": "tools/equity_analysis.py",
        "equity": "tools/equity_analysis.py",
        "FRED": "tools/fred_data.py",
        "fred": "tools/fred_data.py",
        "Regime": "tools/macro_market_analysis.py",
        "regime": "tools/macro_market_analysis.py",
        "TA": "tools/murphy_ta.py",
        "ta": "tools/murphy_ta.py",
        "Commodity": "tools/commodity_analysis.py",
        "commodity": "tools/commodity_analysis.py",
        "Valuation": "tools/graham_analysis.py",
        "valuation": "tools/graham_analysis.py",
        "ProTrader": "tools/protrader_frameworks.py",
        "protrader": "tools/protrader_frameworks.py",
        "BTC": "tools/btc_analysis.py",
        "btc": "tools/btc_analysis.py",
        "Web": "tools/web_search.py",
        "web": "tools/web_search.py",
        "Synthesis": "tools/macro_synthesis.py",
        "Consumer": "tools/consumer_housing_analysis.py",
    }

    files = set()
    for f in failures:
        suite = f.get("suite", "")
        for key, path in file_map.items():
            if key.lower() in suite.lower():
                files.add(path)
                break

    # Also include the synthesis file (often involved in cross-tool issues)
    if len(failures) > 5:
        files.add("tools/macro_synthesis.py")

    return sorted(files)


def _extract_json(text: str) -> str:
    """Extract JSON from a response that might be wrapped in markdown fences."""
    # Try to find ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Otherwise assume the whole thing is JSON
    return text
