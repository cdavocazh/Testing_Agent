# Plan S — Superset.sh Hybrid Orchestrator

A hybrid agent orchestration framework that combines **Superset.sh** (a desktop application providing Git worktree isolation, OAuth authentication, and workspace management) with an **external Python orchestration loop** that implements the cyclic test → fix → retest workflow.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR.PY                         │
│             (Python loop — controls the cycle)              │
└──────────┬──────────────────────────┬───────────────────────┘
           │                          │
           ▼                          ▼
 ┌──────────────────┐      ┌──────────────────────┐
 │    CONFIG.PY     │      │  SUPERSET_CLIENT.PY  │
 │  Paths, settings │      │  HTTP/MCP API wrapper │
 │  Env variables   │      │  Workspace & session  │
 └──────────────────┘      └──────────┬────────────┘
                                      │
                      ┌───────────────┼───────────────┐
                      ▼               ▼               ▼
                  ┌─────────────────────────────────────┐
                  │     SUPERSET.SH (Desktop App)       │
                  │                                     │
                  │  ┌───────────────────────────────┐  │
                  │  │   Git Worktree (Workspace)    │  │
                  │  │                               │  │
                  │  │  Testing Agent Session        │  │
                  │  │  → runs testing_agent.py      │  │
                  │  │  → writes test_results.json   │  │
                  │  │                               │  │
                  │  │  Fixer Agent Session           │  │
                  │  │  → reads failure list          │  │
                  │  │  → modifies source files       │  │
                  │  │  → writes fix_summary.json     │  │
                  │  └───────────────────────────────┘  │
                  └─────────────────────────────────────┘
```

## How Orchestration Works

The orchestrator drives a **cyclic test → fix → retest loop** where both agents operate in the **same Superset workspace** (an isolated Git worktree). The fixer's changes persist for the next testing run.

### Iteration Lifecycle

```
FOR each iteration (1..max_iterations):

  PHASE 1 — TEST
  ├── Orchestrator calls Superset API to launch a Claude Code session
  ├── Session runs: python testing_agent.py --suite {suite}
  ├── Testing agent writes results to artifacts/iteration_N/test_results.json
  ├── Orchestrator polls wait_for_session() until completion
  └── Orchestrator reads and parses test results from workspace

  CONVERGENCE CHECK
  ├── pass_rate >= 98% AND zero critical failures → STOP (converged)
  └── Otherwise → continue to Phase 2

  PHASE 2 — FIX (if not converged)
  ├── Orchestrator builds fix prompt with up to 30 prioritized failures
  ├── Launches another Claude Code session with fix instructions
  ├── Fixer agent reads source code, diagnoses, applies patches
  ├── Fixer writes summary to artifacts/iteration_N/fix_summary.json
  └── Orchestrator polls until completion, then loops back to Phase 1
```

### Convergence Criteria

The cycle stops when:
- **Pass rate** >= `TARGET_PASS_RATE` (default: 98%) **AND**
- **Zero critical failures** (if `TARGET_ZERO_CRITICAL` is enabled)
- Or `MAX_ITERATIONS` (default: 5) is reached

---

## Files

### `orchestrator.py` — Main Controller

The orchestration engine that coordinates the entire cycle.

| Function | Purpose |
|----------|---------|
| `run_cycle()` | Main loop: creates workspace, manages iterations, launches testing/fixing sessions |
| `_build_test_prompt()` | Generates instruction prompt for the testing agent session |
| `_build_fix_prompt()` | Generates instruction prompt for the fixer agent session with prioritized failure list |
| `_read_test_results()` | Parses test results from workspace artifacts (JSON primary, qa_results fallback) |
| `_is_converged()` | Returns True if pass_rate >= target AND zero critical failures |
| `_save_run_summary()` | Archives final run metadata to `artifacts/run_{run_id}.json` |
| `_print_final_report()` | Pretty-prints iteration summary table |

### `superset_client.py` — Superset MCP API Wrapper

HTTP client for Superset.sh's Model Context Protocol API.

**Workspace management:**
- `create_workspace(name)` — Creates isolated Git worktree in Superset
- `get_workspace(workspace_id)` — Retrieves workspace details
- `list_workspaces()` — Lists all workspaces in project
- `delete_workspace(workspace_id)` — Deletes workspace and worktree

**Agent session management:**
- `launch_agent_session(workspace_id, agent_type, task_prompt)` — Creates Claude Code session with injected prompt
- `get_session_status(session_id)` — Returns: running / completed / failed / waiting_for_input
- `wait_for_session(session_id)` — Polls status every `POLL_INTERVAL_SECONDS` until done or timeout

**MCP Protocol:**
- Wraps tool calls as JSON-RPC 2.0
- POST to `SUPERSET_MCP_URL` with Bearer token authentication
- Format: `{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "<tool>", "arguments": {...}}}`

### `config.py` — Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `SUPERSET_MCP_URL` | `https://api.superset.sh/api/agent/mcp` | MCP endpoint |
| `SUPERSET_API_KEY` | env var | API authentication (sk_live_... format) |
| `SUPERSET_PROJECT_ID` | env var | Project identifier |
| `MAX_ITERATIONS` | 5 | Maximum fix cycles |
| `TARGET_PASS_RATE` | 98.0 | Pass rate threshold (%) |
| `TARGET_ZERO_CRITICAL` | True | Require zero critical failures |
| `POLL_INTERVAL_SECONDS` | 15 | How often to check session status |
| `AGENT_TIMEOUT_SECONDS` | 900 | Session timeout (15 minutes) |
| `TEST_SUITE` | "all" | Which test suite to run |

### `requirements.txt` — Dependencies

- `requests>=2.31` — HTTP library for MCP API calls
- `python-dotenv>=1.0` — Load .env files for configuration

---

## How to Run

### Prerequisites

1. **Superset.sh** desktop app must be running locally
2. Set environment variables:
   ```bash
   export SUPERSET_API_KEY="sk_live_..."       # From Superset UI
   export SUPERSET_PROJECT_ID="your-project"   # Project identifier
   export FINANCIAL_AGENT_ROOT="/path/to/Financial_Agent"  # Optional
   ```
3. Claude Code must be authenticated inside Superset

### Commands

```bash
python orchestrator.py                      # Full cycle (max 5 iterations, target 98%)
python orchestrator.py --suite smoke        # Run smoke tests only
python orchestrator.py --max-iter 3         # Limit to 3 iterations
python orchestrator.py --target 99.0        # Set pass rate target to 99%
python orchestrator.py --dry-run            # Test once, no fixes
```

---

## Artifacts

| Path | Contents |
|------|----------|
| `artifacts/iteration_N/test_results.json` | Test results from testing agent |
| `artifacts/iteration_N/fix_summary.json` | Fixes applied by fixer agent |
| `artifacts/run_{run_id}.json` | Final run summary with full iteration history |

All changes are also visible in Superset's diff viewer via the workspace's Git worktree branch.

---

## Key Design Principles

1. **Workspace isolation** — Git worktrees ensure nothing touches the main branch
2. **OAuth delegation** — Superset.sh handles Claude Code authentication
3. **External loop logic** — Python orchestrator provides the cyclic workflow that Superset lacks natively
4. **Pluggable agents** — The `agent_type` parameter allows swapping Claude for other coding agents
5. **Deterministic results** — Both agents save structured JSON to known paths
6. **Audit trail** — Every iteration archived; full run summary saved
