"""
Plan A — Configuration for the LangGraph Cyclic State Machine.
"""

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
TESTING_AGENT_ROOT = Path(__file__).resolve().parent.parent
FINANCIAL_AGENT_ROOT = Path(os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    TESTING_AGENT_ROOT.parent.parent / "Financial_Agent",
))
TOOLS_DIR = FINANCIAL_AGENT_ROOT / "tools"
ARTIFACTS_DIR = TESTING_AGENT_ROOT / "plan_a_langgraph" / "artifacts"

# ── Cycle parameters ─────────────────────────────────────────────────
MAX_ITERATIONS = int(os.environ.get("ORCH_MAX_ITERATIONS", "5"))
TARGET_PASS_RATE = float(os.environ.get("ORCH_TARGET_PASS_RATE", "98.0"))
TARGET_ZERO_CRITICAL = True

# ── Testing ──────────────────────────────────────────────────────────
TEST_SUITE = os.environ.get("ORCH_TEST_SUITE", "all")
TEST_TIMEOUT_SECONDS = int(os.environ.get("ORCH_TEST_TIMEOUT", "600"))

# ── Fixer LLM ───────────────────────────────────────────────────────
FIXER_TEMPERATURE = float(os.environ.get("FIXER_TEMPERATURE", "0.2"))

# ── Git safety ───────────────────────────────────────────────────────
GIT_AUTO_BRANCH = True
GIT_BRANCH_PREFIX = "langgraph-orch/fix"
