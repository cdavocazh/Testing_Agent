# Plan A — LangGraph Cyclic State Machine Orchestrator

A **LangGraph-based orchestration system** that models the test → fix → retest cycle as a **cyclic state machine**. Three nodes (Testing, Router, Fixer) form a graph with conditional edges, and LangGraph manages state transitions, history accumulation, and cycle control.

---

## Architecture Overview

```
                    ┌──────────────────┐
                    │   START          │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
              ┌────→│  testing_node    │
              │     │                  │
              │     │  Run QA tests    │
              │     │  Parse results   │
              │     │  Archive artifacts│
              │     └────────┬─────────┘
              │              │
              │              ▼
              │     ┌──────────────────┐
              │     │  router_node     │
              │     │                  │
              │     │  Check convergence│
              │     │  Decide: fix/done│
              │     └───┬──────────┬───┘
              │         │          │
              │    "fix" │          │ "done"
              │         ▼          ▼
              │  ┌──────────────┐  ┌───────┐
              │  │  fixer_node  │  │  END  │
              │  │              │  └───────┘
              │  │  LLM analysis│
              │  │  Generate    │
              │  │  patches     │
              │  │  Apply & git │
              │  └──────┬───────┘
              │         │
              └─────────┘  (cycle back to testing)
```

---

## How Orchestration Works

### The State Machine

LangGraph compiles the graph into an executable state machine:

```python
graph = StateGraph(PipelineState)
graph.add_node("testing_node", testing_node)
graph.add_node("fixer_node", fixer_node)
graph.set_entry_point("testing_node")
graph.add_conditional_edges("testing_node", router_node, {"fix": "fixer_node", "done": END})
graph.add_edge("fixer_node", "testing_node")
```

Each node is a **pure function** that:
1. Reads from state (immutable)
2. Performs its work
3. Returns a **partial dict** with only changed fields
4. LangGraph **merges** the dict back into the running state

### Node Details

#### `testing_node` — Run QA Tests

1. Spawns `testing_agent.py --direct --suite {suite}` as a subprocess
2. Parses the markdown report for summary metrics (total, passed, failed, errors, pass_rate)
3. Reads `qa_results_all.json` for detailed failure records with severity
4. Archives all artifacts to `artifacts/iteration_N/`
5. Appends an `IterationSnapshot` to history (using LangGraph's `Annotated[list, add]`)
6. Returns updated state fields: pass_rate, failures, critical_failures, counts

#### `router_node` — Conditional Edge (Decide Next Step)

A pure decision function that returns `"fix"` or `"done"`:

| Condition | Result |
|-----------|--------|
| Error state | `"done"` |
| pass_rate >= target AND (no critical or zero-critical disabled) | `"done"` |
| iteration >= max_iterations | `"done"` |
| No failures to fix | `"done"` |
| Otherwise | `"fix"` |

#### `fixer_node` — LLM-Powered Code Patching

1. Builds a detailed prompt with failure list + relevant source code
2. Maps failures to source files via hardcoded suite→file mapping (12 suites)
3. Calls LLM (OpenAI-compatible, temperature 0.2) with system prompt:
   - "You are a senior financial software engineer"
   - "Return JSON with analysis, patches[], skipped_failures[]"
   - "Only fix test failures — no refactoring, no new features"
4. Parses JSON response, extracts patches
5. For each patch:
   - Verifies file exists
   - Validates `old_code` appears exactly once (safety)
   - Applies find/replace
   - Records as `PatchRecord`
6. Git commits all applied patches
7. Archives patches to `artifacts/iteration_N/patches.json`
8. Increments iteration counter, returns updated state

### State Schema (`PipelineState`)

The central TypedDict passed through all nodes:

**Control fields:**
- `iteration`, `max_iterations`, `target_pass_rate`, `suite`, `run_id`, `status`

**Test results (latest):**
- `pass_rate`, `total_tests`, `passed_tests`, `failed_tests`, `error_tests`
- `failures` — list of `FailureRecord` (suite, command, check, status, notes, severity)
- `critical_failures` — filtered subset (critical/high severity only)

**Patch tracking:**
- `all_patches` — cumulative across all iterations
- `latest_patches` — from current iteration only
- `latest_analysis` — LLM's root cause analysis text

**History (append-only):**
- `history: Annotated[list[IterationSnapshot], add]` — LangGraph auto-appends each snapshot

**Status values:** `"running"` → `"converged"` | `"stopped"` | `"error"`

---

## Files

### `orchestrator.py` — Graph Builder & CLI

| Function | Purpose |
|----------|---------|
| `build_graph()` | Constructs the LangGraph StateGraph with nodes and edges |
| `create_initial_state()` | Initializes all PipelineState fields |
| `run()` | Main execution: creates git branch, compiles graph, invokes, saves summary |
| CLI args | `--suite`, `--max-iter`, `--target`, `--dry-run`, `--visualize` |

### `nodes.py` — Node Implementations

| Function | Purpose |
|----------|---------|
| `testing_node(state)` | Runs tests, parses results, archives artifacts |
| `router_node(state)` | Decides `"fix"` or `"done"` based on convergence |
| `fixer_node(state)` | LLM patch generation + application + git commit |
| `_parse_report()` | Extracts metrics from markdown summary table |
| `_parse_json_failures()` | Extracts FailureRecords from qa_results JSON |
| `_build_fixer_prompt()` | Constructs LLM input with failures + source code |
| `_relevant_files()` | Maps failure suites to Financial Agent source files |
| `_git_commit()` | Commits applied patches on isolated branch |
| `_get_llm_client()` | Builds OpenAI client from config or Financial Agent settings |

### `state.py` — State Schema

Defines the `PipelineState` TypedDict and supporting dataclasses:
- `FailureRecord` — Individual test failure (suite, command, check, status, notes, severity)
- `PatchRecord` — Applied patch (file, description, old_code, new_code, applied, error)
- `IterationSnapshot` — Per-iteration summary (iteration, pass_rate, failures, patches, status)

### `config.py` — Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ITERATIONS` | 5 | Maximum fix cycles |
| `TARGET_PASS_RATE` | 98.0 | Pass rate threshold (%) |
| `TARGET_ZERO_CRITICAL` | True | Require zero critical failures |
| `FIXER_TEMPERATURE` | 0.2 | LLM temperature for patch generation |
| `TEST_TIMEOUT_SECONDS` | 600 | Test execution timeout |
| `GIT_AUTO_BRANCH` | True | Create `langgraph-orch/fix/{runid}` branch |
| `TEST_SUITE` | "all" | Which test suite to run |

### `requirements.txt` — Dependencies

- `langgraph>=0.3` — State machine framework
- `langchain>=0.3`, `langchain-core>=0.3` — LangGraph foundation
- `openai>=1.0` — LLM API client
- `python-dotenv>=1.0` — Environment variable management

---

## How to Run

### Prerequisites

1. Install dependencies: `pip install -r requirements.txt`
2. Set LLM configuration (environment variables or Financial Agent config)
3. Financial Agent repo must be accessible (or set `FINANCIAL_AGENT_ROOT`)

### Commands

```bash
python orchestrator.py                      # Full cycle (max 5 iterations, target 98%)
python orchestrator.py --suite smoke        # Run smoke tests only
python orchestrator.py --max-iter 3         # Limit to 3 iterations
python orchestrator.py --target 99.0        # Set pass rate target to 99%
python orchestrator.py --dry-run            # Test once, no fixes (sets max_iter=1)
python orchestrator.py --visualize          # Export graph as PNG image
```

---

## Artifacts

| Path | Contents |
|------|----------|
| `artifacts/iteration_N/test_report.md` | Markdown test report |
| `artifacts/iteration_N/qa_results.json` | Detailed failure records |
| `artifacts/iteration_N/summary.json` | Pass rate, counts, metrics |
| `artifacts/iteration_N/patches.json` | Proposed and applied patches |
| `artifacts/run_{run_id}.json` | Final run summary with full history |

---

## Key Design Principles

1. **State machine pattern** — LangGraph enforces deterministic flow; no spaghetti control logic
2. **Conditional routing** — Router node decides next step based on convergence criteria
3. **Cyclic topology** — Fixer → Testing loop until convergence or max iterations
4. **Stateless nodes** — Nodes are pure functions; LangGraph manages all state persistence
5. **Append-only history** — Each iteration snapshot is auto-accumulated via `Annotated[list, add]`
6. **Low LLM temperature** (0.2) — Deterministic, predictable patch generation
7. **Git safety branching** — All patches on isolated branch for easy rollback
8. **Full audit trail** — Every iteration's state, decisions, and patches recorded

## Why LangGraph?

LangGraph provides three things that a plain Python loop doesn't:

1. **Typed state management** — The `PipelineState` schema is enforced; nodes can only return valid partial updates
2. **Built-in cycle support** — Conditional edges + cycle detection; the framework handles the loop topology
3. **Visualization** — `--visualize` exports the graph as a PNG, making the orchestration flow inspectable
