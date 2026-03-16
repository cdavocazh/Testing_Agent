"""
Plan S — Configuration for the Superset.sh Hybrid Orchestrator.

Uses Superset's MCP API for workspace/agent management and Claude Code
OAuth, while implementing the cyclic workflow logic externally.

Architecture:
    External Python loop (this orchestrator)
        ├── Superset MCP API → create workspace → launch Claude Code session
        ├── Testing Agent runs inside Superset workspace terminal
        ├── Parse results from workspace file system
        ├── Launch Financial Fixer session in same workspace
        └── Loop until convergence

Requires:
    - Superset.sh desktop app running locally
    - Superset MCP API key (sk_live_...) or OAuth token
    - Claude Code authenticated inside Superset
"""

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
TESTING_AGENT_ROOT = Path(__file__).resolve().parent.parent
FINANCIAL_AGENT_ROOT = Path(os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    TESTING_AGENT_ROOT.parent.parent / "Financial_Agent",
))
ARTIFACTS_DIR = TESTING_AGENT_ROOT / "plan_s_superset" / "artifacts"

# ── Superset MCP API ─────────────────────────────────────────────────
SUPERSET_MCP_URL = os.environ.get(
    "SUPERSET_MCP_URL",
    "https://api.superset.sh/api/agent/mcp",
)
# API key (sk_live_...) for headless/CI, or OAuth token for interactive
SUPERSET_API_KEY = os.environ.get("SUPERSET_API_KEY", "")

# Project ID in Superset (find via Superset UI or MCP list_projects)
SUPERSET_PROJECT_ID = os.environ.get("SUPERSET_PROJECT_ID", "")

# ── Cycle parameters ─────────────────────────────────────────────────
MAX_ITERATIONS = int(os.environ.get("ORCH_MAX_ITERATIONS", "5"))
TARGET_PASS_RATE = float(os.environ.get("ORCH_TARGET_PASS_RATE", "98.0"))
TARGET_ZERO_CRITICAL = True

# ── Testing ──────────────────────────────────────────────────────────
TEST_SUITE = os.environ.get("ORCH_TEST_SUITE", "all")

# ── Polling ──────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL", "15"))
AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT", "900"))  # 15 min
