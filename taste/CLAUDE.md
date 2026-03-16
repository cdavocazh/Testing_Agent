# Taste Evaluation Suite — Agent Guide

This directory contains a qualitative ("taste") evaluation framework for the Financial Agent. If you are working in this directory, read this file first.

## What This Is

The taste suite evaluates Financial Agent output quality across 10 approaches, split into two groups:

- **Macro/Full Report approaches (#2–#6):** Test the `/full_report` pipeline and individual commands for coherence, grounding, accuracy, analytical depth, and signal reliability.
- **Technical Analysis approaches (#7–#10):** Test TA tool outputs for consistency, mathematical accuracy, label correctness, and professional quality.

There is no Approach #1 — it was an earlier manual approach that was superseded.

## Architecture

Each approach lives in its own subdirectory (`approach_N_name/`) with:
- A main evaluator Python script
- A `records/` directory for timestamped JSON + markdown results

Command-level evaluators (`command_taste_evaluator.py`, `command_batch2_evaluator.py`, etc.) sit at the root of this directory and test individual commands using the same approach techniques. Their results go to `command_eval_records/`.

Re-evaluation scripts (`reeval_evaluator.py`, `reeval_round2_evaluator.py`, `reeval_round3_evaluator.py`) re-test commands after bug fixes.

## How the Approaches Work

### Rule-Based (No LLM Required)

These approaches use pure Python with financial domain logic. They are deterministic, fast, and free to run:

- **#2 Coherence** (`approach_2_coherence/coherence_checker.py`): 11 rules checking for logical contradictions between tools. Example: macro regime says "expansion" but stress level says "high" → contradiction.
- **#3 Grounding** (`approach_3_grounding/grounding_evaluator.py`): Checks whether qualitative labels (e.g., "tight credit", "elevated VIX") match numeric values using a threshold dictionary. Catches hallucinated assessments.
- **#6 Data Accuracy** (`approach_6_data_accuracy/data_accuracy_checker.py`): ~64 arithmetic checks — spread calculations, composite score decomposition, flag alignment, range plausibility, cross-tool number consistency.
- **#7 TA Coherence** (`approach_7_ta_evaluation/ta_evaluator.py`): Checks that RSI zones match RSI values, breakout confidence matches confirmations, and `quick_ta_snapshot` agrees with individual TA tools.
- **#8 TA Accuracy** (`approach_8_ta_accuracy/ta_accuracy_checker.py`): Recomputes RSI, MACD, Bollinger, Fibonacci, Stochastic from raw price data and compares to tool output. 25 checks per asset.
- **#9 TA Grounding** (`approach_9_ta_grounding/ta_grounding_evaluator.py`): Verifies TA labels (RSI zones, stochastic zones, Bollinger %B positions, composite signal) match their numeric values.

### LLM-as-Judge (Requires API Access)

These approaches send agent output to an LLM for qualitative scoring:

- **#4 Comparative Benchmark** (`approach_4_comparative/comparative_benchmark.py`): 7-dimension rubric (data accuracy, analytical depth, coherence, actionability, completeness, professional quality, signal specificity). Uses Claude or MiniMax. Can compare against reference reports in `approach_4_comparative/reference_reports/`.
- **#10 TA Benchmark** (`approach_10_ta_benchmark/ta_benchmark.py`): 7-dimension rubric for TA quality (S/R quality, entry/exit clarity, indicator interpretation, signal synthesis, risk management, pattern detection, presentation). Uses MiniMax-M2.5.

### Long-Running (Requires Waiting)

- **#5 Backtesting** (`approach_5_backtesting/signal_tracker.py`): Captures forward-looking signals, then verifies them against actual market data after 1/4/12 weeks. Three-phase lifecycle: SNAPSHOT → VERIFY → REPORT.

## Running Evaluators

All evaluators follow the same pattern:

```bash
# Run from the taste directory
python approach_2_coherence/coherence_checker.py
python approach_6_data_accuracy/data_accuracy_checker.py
python command_taste_evaluator.py
# etc.
```

Most evaluators call the Financial Agent's tools directly (via the agent's Python API) and save results as timestamped JSON + markdown to their respective `records/` directories.

For TA approaches (#7–#10), run `collect_ta_data.py` first to populate `ta_output_v1.json` if it doesn't exist.

## Key Files to Know

| File | Purpose |
|------|---------|
| `taste_testing_context.md` | Master context doc — full details on all 10 approaches, how to run, how to interpret |
| `coverage_tracker.py` | Shows which approaches cover which output fields — useful for gap analysis |
| `reeval_comparison_report.md` | Before/after analysis of all bugs found and fixed — the most complete record of issues discovered |

## When Adding or Modifying Approaches

- Each approach should have its own subdirectory with a `records/` folder
- Evaluators should output both JSON (machine-readable) and markdown (human-readable)
- Use the existing threshold dictionaries in approaches #3 and #9 as the canonical label-to-range mappings
- Rule-based approaches are preferred over LLM-based when feasible (deterministic, free, faster)
- Update `coverage_tracker.py` if your approach covers new fields/signals
- Update `README.md` with the new approach details

## Known Issues and Context

- Approach #4 (LLM Judge) scores are low (3.4/10) primarily due to weak actionability and analytical depth in the agent's output — this is an agent quality issue, not an evaluator issue
- Approach #8 (TA Accuracy) shows 85.3% pass rate, but 11 failures are traced to test artifacts (data window mismatches between collection time and evaluation time), not actual tool bugs
- Approach #5 (Backtesting) has snapshots captured but signals have not yet matured for verification — this is expected and by design
- The command batch evaluators collectively cover all agent commands across 4 batches
