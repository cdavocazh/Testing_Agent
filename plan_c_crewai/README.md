# Plan C — CrewAI Role-Based Team Orchestrator

A **CrewAI-based orchestration system** that uses three specialized AI agents — a QA Orchestrator, a Testing Specialist, and a Financial Engineer — to autonomously drive a test → diagnose → fix → retest cycle for the Financial Agent.

---

## Architecture Overview

```
orchestrator.py (Python control loop)
│
└── FOR each iteration (1..N):
    │
    ├── PHASE 1: Run Tests ──────────────────────────────────────┐
    │   Crew: [Testing Specialist]                               │
    │   Task: create_run_tests_task()                            │
    │   Tool: RunTestsTool (run_qa_tests)                        │
    │   Output: JSON → pass_rate, failures[], critical_failures[]│
    │                                                            │
    ├── CONVERGENCE CHECK ───────────────────────────────────────┤
    │   pass_rate >= 98% AND zero critical? → STOP               │
    │   dry_run? → STOP                                          │
    │                                                            │
    ├── PHASE 2: Fix Failures ───────────────────────────────────┤
    │   Crew: [Financial Engineer]                               │
    │   Task: create_fix_failures_task()                         │
    │   Tools: ListFilesTool, ReadSourceTool,                    │
    │          ApplyPatchTool, GitCommitTool                     │
    │   Output: JSON → patches_applied, files_modified, skipped  │
    │                                                            │
    └── PHASE 3: Evaluate Progress ──────────────────────────────┤
        Crew: [QA Orchestrator]                                  │
        Task: create_evaluate_progress_task()                    │
        Output: JSON → { continue: true/false }                  │
```

---

## The Three Agents

### Agent 1: QA Orchestrator (Manager)

- **Role:** Drives the overall test-fix cycle
- **Goal:** Reach target pass rate by coordinating iterative cycles
- **Backstory:** 15-year veteran QA engineer from Bloomberg/Goldman Sachs
- **Capabilities:** Delegation, memory, reasoning about convergence
- **Decides:** Whether to continue iterating or stop based on progress analysis

### Agent 2: Testing Specialist

- **Role:** Executes QA tests and interprets results
- **Goal:** Run test suites and produce structured failure reports
- **Backstory:** Financial data systems QA specialist
- **Tools:** `run_qa_tests` only
- **Cannot delegate** — focused execution role
- **Output:** Structured JSON with pass rates, failure lists grouped by severity, pattern detection

### Agent 3: Financial Engineer

- **Role:** Diagnoses root causes and applies targeted code fixes
- **Goal:** Read source code, identify bugs, apply minimal patches
- **Backstory:** Senior quant engineer with financial software expertise
- **Tools:** `read_financial_agent_source`, `apply_code_patch`, `list_financial_agent_files`, `git_commit_changes`
- **Output:** JSON report of patches applied, failures skipped (with reasons), and git commits

---

## How Orchestration Works

### Phase 1: Run Tests

The Testing Specialist executes the QA test suite via the `run_qa_tests` tool, which:
1. Spawns `python testing_agent.py --direct --suite {suite}` as a subprocess
2. Parses the markdown report and JSON results
3. Returns structured data: pass_rate, total/passed/failed/errors, failures array with severity

### Phase 2: Fix Failures

The Financial Engineer receives the failure list and autonomously:
1. Uses `list_financial_agent_files` to find relevant source files
2. Uses `read_financial_agent_source` to read each problematic file (capped at 15,000 chars)
3. Diagnoses root causes based on failure details and source code
4. Uses `apply_code_patch` to apply targeted find/replace patches
   - Requires `old_code` to be **unique** in the file (safety: no ambiguous edits)
5. Uses `git_commit_changes` to commit all patches

### Phase 3: Evaluate Progress

The QA Orchestrator reviews test results and patches, then makes a binary decision:
- `continue: true` — More progress is possible, keep iterating
- `continue: false` — Converged, plateaued, or diminishing returns

### Convergence Criteria

The Python outer loop stops when:
- **Pass rate** >= `TARGET_PASS_RATE` (default: 98%)
- **OR** the QA Orchestrator decides `continue: false`
- **OR** `MAX_ITERATIONS` (default: 5) is reached

---

## Files

### `orchestrator.py` — Main Execution Engine

CLI entry point and control loop.

| Function | Purpose |
|----------|---------|
| `run_cycle()` | Master loop: creates git branch, runs 3-phase iterations |
| `_extract_pass_rate()` | Parses pass rate from crew output (tries JSON, then regex fallback) |
| `_should_continue()` | Extracts the QA Orchestrator's continue/stop decision |
| `_save_iteration_artifacts()` | Saves Phase 1/2/3 outputs to disk |
| `_print_final_report()` | Prints iteration summary table |

### `agents.py` — Agent Definitions

Three factory functions that create CrewAI Agent instances:
- `create_qa_orchestrator()` — Manager agent with delegation capability
- `create_testing_specialist()` — Test runner with RunTestsTool
- `create_financial_engineer()` — Code fixer with read/patch/list/commit tools
- `_get_llm()` — Builds LLM from environment or falls back to Financial Agent's config
- Temperature: 0.15 (low = deterministic, focused reasoning)

### `tasks.py` — Task Definitions

Three factory functions defining work units for each phase:
- `create_run_tests_task()` — Execute QA test suite, report structured findings
- `create_fix_failures_task()` — Diagnose and patch failures, commit changes
- `create_evaluate_progress_task()` — Review progress, decide continue/stop

### `tools.py` — CrewAI Tool Implementations

Five tools available to the agents:

| Tool | Name | Used By | What It Does |
|------|------|---------|--------------|
| `RunTestsTool` | `run_qa_tests` | Testing Specialist | Runs `testing_agent.py` via subprocess, parses results |
| `ReadSourceTool` | `read_financial_agent_source` | Financial Engineer | Reads a Python file from Financial Agent (max 15K chars) |
| `ApplyPatchTool` | `apply_code_patch` | Financial Engineer | Find/replace with uniqueness validation |
| `ListFilesTool` | `list_financial_agent_files` | Financial Engineer | Lists Python files in a directory with sizes |
| `GitCommitTool` | `git_commit_changes` | Financial Engineer | Stages all changes and commits |

### `config.py` — Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `CREWAI_MODEL` | env or Financial Agent config | LLM model identifier |
| `CREWAI_API_KEY` | env or Financial Agent config | LLM API key |
| `CREWAI_BASE_URL` | env or Financial Agent config | LLM base URL |
| `MAX_ITERATIONS` | 5 | Maximum fix cycles |
| `TARGET_PASS_RATE` | 98.0 | Pass rate threshold (%) |
| `TEST_TIMEOUT_SECONDS` | 600 | Test execution timeout |
| `GIT_AUTO_BRANCH` | True | Create isolated branch per run |

### `requirements.txt` — Dependencies

- `crewai>=0.100.0` — Core CrewAI framework
- `crewai-tools>=0.17.0` — Built-in CrewAI tools
- `openai>=1.0` — OpenAI client for LLM calls
- `python-dotenv>=1.0` — .env file support

---

## How to Run

### Prerequisites

1. Install dependencies: `pip install -r requirements.txt`
2. Set LLM configuration (one of):
   - Environment variables: `CREWAI_MODEL`, `CREWAI_API_KEY`, `CREWAI_BASE_URL`
   - Or let it fall back to Financial Agent's LLM config
3. Financial Agent repo must be accessible (or set `FINANCIAL_AGENT_ROOT`)

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

All iteration outputs are saved to `artifacts/`:

| Path | Contents |
|------|----------|
| `artifacts/iteration_N/phase1_test.txt` | Testing Specialist's raw output |
| `artifacts/iteration_N/phase2_fix.txt` | Financial Engineer's raw output |
| `artifacts/iteration_N/phase3_eval.txt` | QA Orchestrator's evaluation |
| `artifacts/run_{run_id}.json` | Final run summary with full iteration history |

---

## Key Design Principles

1. **Separation of concerns** — Each agent has a single responsibility (test, fix, evaluate)
2. **Minimal patch philosophy** — Only fix what's broken; no refactoring, no feature creep
3. **Deterministic control** — Python loop decides iterations, not LLM indirection
4. **Safety first** — Git branching, timeout protection, exact-match patch validation
5. **Structured data flow** — JSON-based communication between phases
6. **Severity prioritization** — Critical/high failures are fixed first
7. **Autonomous reasoning** — Within each phase, agents reason independently about how to accomplish their task
