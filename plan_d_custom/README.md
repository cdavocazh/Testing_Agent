# Plan D — Custom Python Orchestrator

A **lightweight, framework-free orchestration system** that automates the test → fix → retest cycle using pure Python with subprocess coordination and an LLM for patch generation. No external orchestration frameworks (no LangGraph, no CrewAI) — just Python, the OpenAI client, and subprocess calls.

---

## Architecture Overview

```
orchestrator.py (main loop)
│
├── test_runner.py
│   └── Subprocess: python testing_agent.py --direct --suite {suite}
│       ├── Produces: test_report_*.md
│       └── Produces: qa_results_all.json
│
├── Convergence check
│   └── pass_rate >= target AND zero critical failures?
│
├── financial_fixer.py
│   ├── generate_patches()
│   │   ├── Map failures → source files
│   │   ├── Read relevant source code
│   │   ├── Build LLM prompt with failures + code
│   │   ├── Call LLM → get JSON patches
│   │   └── Return: { analysis, patches[], skipped_failures[] }
│   │
│   └── apply_patches()
│       └── For each patch: validate uniqueness → find/replace → write
│
└── Git operations
    ├── Create branch: orchestrator/fix/{run_id}
    ├── Commit after each iteration
    └── Enables rollback
```

---

## How Orchestration Works

### Iteration Lifecycle

```
FOR each iteration (1..max_iterations):

  1. RUN TESTS
     └── test_runner.run_tests() → TestRunResult
         ├── pass_rate, total, passed, failed, errors
         ├── failures[] with severity
         └── critical_failures[] (critical/high only)

  2. CHECK CONVERGENCE
     └── pass_rate >= 98% AND zero critical? → STOP

  3. GENERATE PATCHES (if not converged, not dry-run)
     └── financial_fixer.generate_patches()
         ├── Build prompt with up to 30 failures + 5 source files
         ├── Call LLM (temperature 0.2)
         └── Parse JSON response → patches[]

  4. EARLY EXIT CHECK
     └── No patches proposed? → STOP (plateau detected)

  5. APPLY PATCHES
     └── financial_fixer.apply_patches()
         ├── Validate old_code is unique in file
         ├── Find/replace in source
         └── Return results (applied/failed per patch)

  6. EARLY EXIT CHECK
     └── No patches applied? → STOP

  7. GIT COMMIT
     └── Stage all → commit "orchestrator: iteration N — applied M patches"

  8. LOOP back to step 1
```

### Convergence & Early Exit

The cycle stops when **any** of these conditions are met:

| Condition | Meaning |
|-----------|---------|
| pass_rate >= target AND zero critical | **Converged** — quality goal reached |
| Max iterations reached | **Safety limit** — prevent infinite loops |
| No patches proposed by LLM | **Plateau** — LLM can't find more fixes |
| No patches applied successfully | **Stuck** — patches didn't match source code |
| Dry-run mode | **Diagnostic** — test only, no modifications |

---

## Files

### `orchestrator.py` — Main Control Loop

The entry point and control flow engine.

| Function | Purpose |
|----------|---------|
| `run_cycle()` | Master loop: git branch → iterate (test → fix → commit) → summary |
| `_is_converged()` | Returns True if pass_rate >= target AND zero critical failures |
| `_create_git_branch()` | Creates `orchestrator/fix/{run_id}` branch in Financial Agent repo |
| `_git_commit_patches()` | Stages all changes, commits with iteration message |
| `_save_run_summary()` | Writes `artifacts/run_{run_id}.json` with full history |
| `_print_final_report()` | Prints iteration table: pass_rate, failures, patches, time, status |

### `test_runner.py` — Test Execution & Parsing

Invokes the Testing Agent as a subprocess and parses outputs.

| Function | Purpose |
|----------|---------|
| `run_tests(iteration, suite)` | Spawns `testing_agent.py`, captures output, returns `TestRunResult` |
| `_parse_test_outputs()` | Finds most recent report + JSON, extracts metrics |
| `_extract_summary_from_report()` | Parses markdown table for total/passed/failed/errors/pass_rate |
| `_extract_failures_from_json()` | Reads qa_results_all.json for failure details with severity |
| `_archive_artifacts()` | Copies report + JSON + summary to `artifacts/iteration_N/` |

**TestRunResult dataclass:**
- `pass_rate`, `total`, `passed`, `failed`, `errors`
- `failures[]` — all failures with suite, command, check, status, notes, severity
- `critical_failures[]` — filtered to critical/high only
- `report_path`, `json_path`

### `financial_fixer.py` — LLM-Powered Code Fixer

Analyzes failures and generates/applies targeted code patches.

| Function | Purpose |
|----------|---------|
| `generate_patches()` | Calls LLM with failures + source code, returns JSON patches |
| `apply_patches()` | Executes find/replace on source files with uniqueness validation |
| `_build_fixer_prompt()` | Constructs LLM input: failures (max 30) + source files (max 5) + previous patches |
| `_get_llm_client()` | Builds OpenAI client from config or Financial Agent settings |
| `_identify_relevant_files()` | Maps failure keywords → source file paths |
| `_extract_json()` | Strips markdown fences from LLM response |

**LLM System Prompt Strategy:**
- Return minimal, targeted patches only (1-5 lines preferred)
- Format: `{"file": "...", "description": "...", "old_code": "...", "new_code": "..."}`
- No refactoring, no new features, no dependency changes
- Skip external data issues (API down, stale CSV, market closed)

**Patch Safety:**
- `old_code` must match exactly once in the file (no ambiguous edits)
- All changes on git branch (easy rollback)
- Previous patches included in prompt to avoid re-attempting failed fixes

### `config.py` — Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ITERATIONS` | 5 | Maximum fix cycles |
| `TARGET_PASS_RATE` | 98.0 | Pass rate threshold (%) |
| `TARGET_ZERO_CRITICAL` | True | Require zero critical failures |
| `FIXER_TEMPERATURE` | 0.2 | LLM temperature for patch generation |
| `TEST_TIMEOUT_SECONDS` | 600 | Test execution timeout |
| `TEST_SUITE` | "all" | Which test suite to run |
| `GIT_AUTO_BRANCH` | True | Create isolated branch per run |
| `GIT_BRANCH_PREFIX` | `"orchestrator/fix/"` | Branch naming scheme |
| `FIXER_PROVIDER` / `FIXER_MODEL` / etc. | env vars | Override LLM config (falls back to Financial Agent) |

### `requirements.txt` — Dependencies

- `openai>=1.0` — LLM API client (the only external dependency beyond Testing/Financial Agent)
- `python-dotenv>=1.0` — Environment variable management

---

## How to Run

### Prerequisites

1. Install dependencies: `pip install -r requirements.txt`
2. Set LLM configuration (one of):
   - Environment variables: `FIXER_MODEL`, `FIXER_API_KEY`, `FIXER_BASE_URL`
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

| Path | Contents |
|------|----------|
| `artifacts/iteration_N/test_report.md` | Markdown test report from Testing Agent |
| `artifacts/iteration_N/qa_results.json` | Detailed failure records |
| `artifacts/iteration_N/summary.json` | Pass rate, counts, metrics |
| `artifacts/run_{run_id}.json` | Final run summary with full iteration history |

Git commits on the `orchestrator/fix/{run_id}` branch serve as an additional audit trail.

---

## Key Design Principles

| Principle | Implementation |
|-----------|----------------|
| **No frameworks** | Pure Python — no LangGraph, no CrewAI, no orchestration dependencies |
| **Minimal dependencies** | Only `openai` + `python-dotenv` |
| **Transparent control flow** | Every line readable; no framework abstractions to navigate |
| **Subprocess isolation** | Testing runs in its own process; crashes don't kill the orchestrator |
| **Patch safety** | Unique-match validation prevents accidental multi-location edits |
| **Git isolation** | All patches on dedicated branch; main branch untouched |
| **Plateau detection** | Stops early if LLM can't propose patches or patches don't apply |
| **Context management** | Caps at 30 failures + 5 source files to stay within LLM limits |
| **Low LLM temperature** | 0.2 for deterministic, predictable code generation |

## Why Custom (No Framework)?

Plan D trades framework features for simplicity:

- **Readable** — The entire orchestration logic is ~400 lines of straightforward Python
- **Debuggable** — No framework internals to step through; print statements work everywhere
- **Modifiable** — Adding a new step means adding a function call in the loop
- **Portable** — Runs anywhere with Python 3.9+ and an OpenAI-compatible API
- **No version lock** — Not tied to LangGraph or CrewAI release cycles
