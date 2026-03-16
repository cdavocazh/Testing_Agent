"""
Plan D — Configuration for the Custom Python Orchestrator.

All tunable parameters for the testing → financial-fix → re-test cycle.
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

# Orchestrator output directory (per-run artifacts)
ARTIFACTS_DIR = TESTING_AGENT_ROOT / "plan_d_custom" / "artifacts"

# ── Cycle parameters ─────────────────────────────────────────────────
MAX_ITERATIONS = int(os.environ.get("ORCH_MAX_ITERATIONS", "5"))
TARGET_PASS_RATE = float(os.environ.get("ORCH_TARGET_PASS_RATE", "98.0"))
TARGET_ZERO_CRITICAL = True  # Stop only when zero critical/high failures

# ── Testing Agent invocation ─────────────────────────────────────────
TEST_SUITE = os.environ.get("ORCH_TEST_SUITE", "all")  # "all", "smoke", or specific suite
TEST_TIMEOUT_SECONDS = int(os.environ.get("ORCH_TEST_TIMEOUT", "600"))  # 10 min per full run

# ── LLM for the fixer agent ─────────────────────────────────────────
# By default, re-uses the Financial Agent's LLM config.
# Override with FIXER_* env vars if you want a different model.
FIXER_PROVIDER = os.environ.get("FIXER_PROVIDER", "")        # blank = auto-detect
FIXER_MODEL = os.environ.get("FIXER_MODEL", "")              # blank = auto-detect
FIXER_API_KEY = os.environ.get("FIXER_API_KEY", "")          # blank = auto-detect
FIXER_BASE_URL = os.environ.get("FIXER_BASE_URL", "")        # blank = auto-detect
FIXER_TEMPERATURE = float(os.environ.get("FIXER_TEMPERATURE", "0.2"))

# ── Git safety ───────────────────────────────────────────────────────
GIT_AUTO_BRANCH = True   # Create a new branch per orchestration run
GIT_BRANCH_PREFIX = "orchestrator/fix"
