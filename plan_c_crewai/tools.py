"""
Plan C — CrewAI Custom Tools.

Wraps the Testing Agent invocation and Financial Agent code patching
as CrewAI-compatible tools that agents can call.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import (
    TESTING_AGENT_ROOT,
    FINANCIAL_AGENT_ROOT,
    TOOLS_DIR,
    ARTIFACTS_DIR,
    TEST_TIMEOUT_SECONDS,
)


# ═════════════════════════════════════════════════════════════════════════
# TOOL 1: RUN TESTS
# ═════════════════════════════════════════════════════════════════════════

class RunTestsInput(BaseModel):
    suite: str = Field(default="all", description="Test suite name: all, smoke, macro, equity, etc.")


class RunTestsTool(BaseTool):
    name: str = "run_qa_tests"
    description: str = (
        "Executes the QA Testing Agent against the Financial Agent in --direct mode. "
        "Returns a JSON object with pass_rate, total, passed, failed, errors, "
        "and a list of failure details (suite, command, check, notes, severity). "
        "Use suite='smoke' for a quick test or suite='all' for full coverage."
    )
    args_schema: type[BaseModel] = RunTestsInput

    def _run(self, suite: str = "all") -> str:
        cmd = [
            sys.executable,
            str(TESTING_AGENT_ROOT / "testing_agent.py"),
            "--direct",
            "--suite", suite,
        ]

        try:
            proc = subprocess.run(
                cmd, cwd=str(TESTING_AGENT_ROOT),
                capture_output=True, text=True,
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Testing Agent timed out after {TEST_TIMEOUT_SECONDS}s"})

        result = {
            "pass_rate": 0.0,
            "total": 0, "passed": 0, "failed": 0, "errors": 0,
            "failures": [], "critical_failures": [],
        }

        # Parse markdown report
        reports = sorted(
            TESTING_AGENT_ROOT.glob("test_report_*.md"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if reports:
            for line in reports[0].read_text().splitlines():
                line = line.strip()
                if line.startswith("| Total Tests"):
                    v = line.split("|")[2].strip()
                    result["total"] = int(v) if v.isdigit() else 0
                elif line.startswith("| Passed"):
                    v = line.split("|")[2].strip()
                    result["passed"] = int(v) if v.isdigit() else 0
                elif line.startswith("| Failed"):
                    v = line.split("|")[2].strip()
                    result["failed"] = int(v) if v.isdigit() else 0
                elif line.startswith("| Errors"):
                    v = line.split("|")[2].strip()
                    result["errors"] = int(v) if v.isdigit() else 0
                elif line.startswith("| Pass Rate"):
                    v = line.split("|")[2].strip().rstrip("%")
                    try:
                        result["pass_rate"] = float(v)
                    except ValueError:
                        pass

        # Parse JSON failures
        qa_json = TESTING_AGENT_ROOT / "qa_results_all.json"
        if qa_json.exists():
            rows = json.loads(qa_json.read_text())
            for row in rows:
                if len(row) >= 6 and row[3] in ("FAIL", "ERROR"):
                    entry = {
                        "suite": row[0], "command": row[1], "check": row[2],
                        "status": row[3], "notes": row[4], "severity": row[5],
                    }
                    result["failures"].append(entry)
                    if row[5] in ("critical", "high"):
                        result["critical_failures"].append(entry)

            # Recalculate if needed
            if result["total"] == 0 and rows:
                result["total"] = len(rows)
                result["passed"] = sum(1 for r in rows if len(r) >= 4 and r[3] == "PASS")
                result["failed"] = sum(1 for r in rows if len(r) >= 4 and r[3] == "FAIL")
                result["errors"] = sum(1 for r in rows if len(r) >= 4 and r[3] == "ERROR")
                if result["total"] > 0:
                    result["pass_rate"] = round(result["passed"] / result["total"] * 100, 1)

        return json.dumps(result, indent=2)


# ═════════════════════════════════════════════════════════════════════════
# TOOL 2: READ SOURCE FILE
# ═════════════════════════════════════════════════════════════════════════

class ReadSourceInput(BaseModel):
    file_path: str = Field(
        description="Relative path from Financial Agent root (e.g., 'tools/macro_data.py')"
    )


class ReadSourceTool(BaseTool):
    name: str = "read_financial_agent_source"
    description: str = (
        "Reads a source file from the Financial Agent codebase. "
        "Provide the relative path from the Financial Agent root "
        "(e.g., 'tools/macro_data.py'). Returns the file content."
    )
    args_schema: type[BaseModel] = ReadSourceInput

    def _run(self, file_path: str) -> str:
        abs_path = FINANCIAL_AGENT_ROOT / file_path
        if not abs_path.exists():
            return json.dumps({"error": f"File not found: {file_path}"})
        content = abs_path.read_text()
        if len(content) > 15000:
            content = content[:15000] + "\n... (truncated at 15000 chars)"
        return content


# ═════════════════════════════════════════════════════════════════════════
# TOOL 3: APPLY CODE PATCH
# ═════════════════════════════════════════════════════════════════════════

class ApplyPatchInput(BaseModel):
    file_path: str = Field(
        description="Relative path from Financial Agent root (e.g., 'tools/macro_data.py')"
    )
    old_code: str = Field(
        description="Exact code string to find and replace (must be unique in the file)"
    )
    new_code: str = Field(
        description="Replacement code string"
    )
    description: str = Field(
        default="", description="One-line description of the patch"
    )


class ApplyPatchTool(BaseTool):
    name: str = "apply_code_patch"
    description: str = (
        "Applies a targeted code patch to a Financial Agent source file. "
        "Provide the relative file path, the EXACT old_code to find (must be unique), "
        "and the new_code to replace it with. Returns success/failure status."
    )
    args_schema: type[BaseModel] = ApplyPatchInput

    def _run(self, file_path: str, old_code: str, new_code: str,
             description: str = "") -> str:
        abs_path = FINANCIAL_AGENT_ROOT / file_path
        if not abs_path.exists():
            return json.dumps({"applied": False, "error": f"File not found: {file_path}"})

        content = abs_path.read_text()
        occurrences = content.count(old_code)

        if occurrences == 0:
            return json.dumps({
                "applied": False,
                "error": "old_code not found in file"
            })
        if occurrences > 1:
            return json.dumps({
                "applied": False,
                "error": f"old_code matches {occurrences} locations (ambiguous)"
            })

        new_content = content.replace(old_code, new_code, 1)
        abs_path.write_text(new_content)

        return json.dumps({
            "applied": True,
            "file": file_path,
            "description": description,
        })


# ═════════════════════════════════════════════════════════════════════════
# TOOL 4: LIST FINANCIAL AGENT FILES
# ═════════════════════════════════════════════════════════════════════════

class ListFilesInput(BaseModel):
    directory: str = Field(
        default="tools",
        description="Subdirectory to list (default: 'tools')"
    )


class ListFilesTool(BaseTool):
    name: str = "list_financial_agent_files"
    description: str = (
        "Lists Python files in a Financial Agent subdirectory. "
        "Default: 'tools'. Returns file names and sizes."
    )
    args_schema: type[BaseModel] = ListFilesInput

    def _run(self, directory: str = "tools") -> str:
        dir_path = FINANCIAL_AGENT_ROOT / directory
        if not dir_path.exists():
            return json.dumps({"error": f"Directory not found: {directory}"})

        files = []
        for f in sorted(dir_path.iterdir()):
            if f.suffix == ".py" and not f.name.startswith("__"):
                files.append({
                    "name": f.name,
                    "path": f"{directory}/{f.name}",
                    "size_bytes": f.stat().st_size,
                })
        return json.dumps(files, indent=2)


# ═════════════════════════════════════════════════════════════════════════
# TOOL 5: GIT COMMIT
# ═════════════════════════════════════════════════════════════════════════

class GitCommitInput(BaseModel):
    message: str = Field(description="Commit message")


class GitCommitTool(BaseTool):
    name: str = "git_commit_changes"
    description: str = (
        "Stages all changes in the Financial Agent repo and commits them. "
        "Use after applying patches to create a checkpoint."
    )
    args_schema: type[BaseModel] = GitCommitInput

    def _run(self, message: str) -> str:
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(FINANCIAL_AGENT_ROOT),
                capture_output=True, check=True,
            )
            proc = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(FINANCIAL_AGENT_ROOT),
                capture_output=True, text=True, check=True,
            )
            return json.dumps({"committed": True, "message": message})
        except subprocess.CalledProcessError as e:
            return json.dumps({"committed": False, "error": e.stderr.strip()})
