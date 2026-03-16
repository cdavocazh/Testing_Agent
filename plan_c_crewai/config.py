"""
Plan C — Configuration for the CrewAI Role-Based Team.
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
ARTIFACTS_DIR = TESTING_AGENT_ROOT / "plan_c_crewai" / "artifacts"

# ── Cycle parameters ─────────────────────────────────────────────────
MAX_ITERATIONS = int(os.environ.get("ORCH_MAX_ITERATIONS", "5"))
TARGET_PASS_RATE = float(os.environ.get("ORCH_TARGET_PASS_RATE", "98.0"))

# ── Testing ──────────────────────────────────────────────────────────
TEST_SUITE = os.environ.get("ORCH_TEST_SUITE", "all")
TEST_TIMEOUT_SECONDS = int(os.environ.get("ORCH_TEST_TIMEOUT", "600"))

# ── LLM ──────────────────────────────────────────────────────────────
# CrewAI uses its own LLM config. Override via env vars if needed.
CREWAI_LLM_MODEL = os.environ.get("CREWAI_LLM_MODEL", "")  # blank = auto-detect
CREWAI_LLM_API_KEY = os.environ.get("CREWAI_LLM_API_KEY", "")
CREWAI_LLM_BASE_URL = os.environ.get("CREWAI_LLM_BASE_URL", "")

# ── Git safety ───────────────────────────────────────────────────────
GIT_AUTO_BRANCH = True
GIT_BRANCH_PREFIX = "crewai-orch/fix"
