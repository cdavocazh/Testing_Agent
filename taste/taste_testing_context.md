# TASTE Testing Context for the Financial Agent

This document explains how the TASTE (Testing Agent Systematic Testing & Evaluation) suite evaluates the Financial Agent. It is written for an agent that needs to understand the testing methodology, run the tests, interpret results, and fix failures.

---

## What Is Being Tested

The Financial Agent is a LangChain-powered macro/equity analysis system with 18+ tool modules in `Financial_Agent/tools/`. The TASTE suite evaluates the **quality, correctness, and consistency** of the agent's outputs — not just whether tools return data, but whether the data is right, the labels match the numbers, the tools agree with each other, and the analysis is useful.

There are two testing layers:

1. **`testing_agent.py`** — Functional QA (19 suites, 740+ checks): does the tool run, return valid JSON, have correct schema, handle edge cases?
2. **`taste/`** — Qualitative evaluation (7 approaches): is the analysis *correct*, *coherent*, *grounded*, *accurate*, and *useful*?

This document covers the TASTE layer only.

---

## Input Data

All TASTE approaches consume the same input: the JSON output of the Financial Agent's tools.

### Full Report Pipeline (Approaches #2–#6)

These 8 tools run together as `/full_report`:

| Tool Function | What It Returns |
|---|---|
| `scan_all_indicators` | 27 macro indicators with latest values, daily/weekly/monthly % moves, flags |
| `analyze_macro_regime` | Regime classifications (growth, inflation, employment, rates, credit, housing), composite outlook, signals |
| `analyze_financial_stress` | Composite stress score (0-10), 8 weighted components, stress level label, signals |
| `detect_late_cycle_signals` | Count of firing signals, confidence level, individual signal details |
| `analyze_equity_drivers` | Real yield impact, credit-equity link, DXY impact, rolling correlations |
| `analyze_bond_market` | Yield curve, real yields, breakevens, credit spreads, term premium |
| `analyze_consumer_health` | Composite score (0-10), 4 weighted components, consumer health level label |
| `analyze_housing_market` | Starts, permits, sales trend, affordability, cycle phase, signals |

### Command-Level Pipeline (Command Evaluators)

Individual commands tested separately:

**Batch 1**: `/analyze NVDA` (equity valuation), `/commodity crude_oil`, `/drivers` (equity drivers)
**Batch 2**: `/macro`, `/bonds`, `/stress`, `/latecycle`, `/consumer`, `/housing`, `/labor`, `/graham NVDA`, `/valuation`, `/vixanalysis`

### Running Against Live vs Saved Data

Every approach supports both modes:
```bash
# Live — calls the Financial Agent tools directly
python <approach>.py

# Saved — reads from a JSON file (reproducible, faster)
python <approach>.py --input full_report_output.json
```

---

## The 7 TASTE Approaches

### Approach #2: Internal Coherence & Contradiction Detection

**File**: `taste/approach_2_coherence/coherence_checker.py`
**Technique**: Pure Python rule-based cross-checking. No LLM.
**What it tests**: Whether different tools within the same report logically agree with each other.

It does NOT check if data is correct. It checks if Tool A's conclusion is compatible with Tool B's conclusion, given the same underlying data.

**How it works**:
1. Loads the full report JSON (all 8 tools)
2. Extracts key values and classifications from each tool
3. Applies 11 domain-logic rules that encode known financial relationships
4. Each rule produces a `CoherenceResult` with: `rule_id`, `left_claim`, `right_claim`, `passed/failed`, `severity`, and `explanation`

**The 11 rules**:

| Rule ID | What It Checks | Logic |
|---|---|---|
| C-01 | Macro regime vs stress level | Reflationary/goldilocks → stress < 6. Recessionary → stress > 4. |
| C-02 | Credit spread level vs interpretation | HY OAS > 250bps → narrative must NOT say "tight"/"supportive" |
| C-03 | Yield curve shape vs late-cycle count | Inverted curve → late-cycle >= 3. Normal → count <= 8. |
| C-04 | Housing distress vs consumer health | Housing "plunging"/"collapse" → consumer health NOT "healthy" |
| C-05 | VIX level vs stress classification | VIX > 25 → stress at least "moderate". VIX < 15 → not "high" |
| C-06 | Growth regime vs ISM signal | Regime "expansion" must not coexist with ISM_CONTRACTION |
| C-07 | Contradictory signal pairs | Scans ALL signals for mutually exclusive pairs (CREDIT_LOOSE + CREDIT_TIGHT, etc.) |
| C-08 | Bank stress vs consumer credit | BANK_SYSTEMIC_STRESS → consumer credit not "healthy" |
| C-09 | Real yield direction vs equity narrative | Real yields > 2% and rising → equity summary must mention headwind/pressure |
| C-10 | Rate regime vs Fed policy signals | Rate regime "easing" must not coexist with FED_TIGHTENING signal |
| C-11 | Scan flag rate vs stress level | > 70% indicators flagged → stress not "low" |

**Run**:
```bash
python taste/approach_2_coherence/coherence_checker.py --input full_report_output.json
```

**Output**: JSON + markdown in `taste/approach_2_coherence/records/`

---

### Approach #3: Narrative-vs-Data Grounding (Hallucination Detection)

**File**: `taste/approach_3_grounding/grounding_evaluator.py`
**Technique**: Rule-based claim extraction + financial threshold dictionary. No LLM in current version.
**What it tests**: Whether qualitative labels in narrative fields ("tight", "stressed", "cooling") are supported by the actual numbers.

**How it works**:
1. Defines a `THRESHOLDS` dictionary mapping metric names to labeled ranges:
   - `hy_oas_bps`: tight=(0,150), normal=(150,300), wide=(300,500), stressed=(500,800)
   - `vix`: complacent=(0,12), calm=(12,16), normal=(16,20), elevated=(20,25), fearful=(25,35)
   - `stress_score`: low=(0,2.5), moderate=(2.5,5), elevated=(5,7), high=(7,9)
   - `consumer_health_score`: critical=(0,3), stressed=(3,5), stable=(5,7), healthy=(7,10)
   - Plus: `cpi_yoy_pct`, `real_yield_10y_pct`, `late_cycle_count`
2. Extracts narrative text from summary/interpretation/assessment fields
3. Scans each narrative for label words ("tight", "wide", "supportive", "stressed", etc.)
4. Looks up the actual metric value and classifies it using the threshold dictionary
5. Compares: Does the narrative label match the threshold-derived classification?

**7 claim categories checked**:
1. Credit spread interpretation vs HY OAS level
2. Stress level label vs composite score
3. VIX characterization vs actual VIX value
4. Inflation characterization vs CPI YoY
5. Late-cycle confidence vs late_cycle_count
6. Real yield characterization vs actual 10Y real yield
7. Consumer health level vs composite score

**Run**:
```bash
python taste/approach_3_grounding/grounding_evaluator.py --input full_report_output.json
```

**Key distinction from Approach #6**: Approach #3 asks "does the label 'tight' match 313bps?" (answer: no, 313bps is 'wide'). Approach #6 asks "does 313bps - 84bps = 229bps?" (answer: yes, the arithmetic is correct). Different layers of correctness.

---

### Approach #4: Comparative Benchmarking (LLM-as-Judge)

**File**: `taste/approach_4_comparative/comparative_benchmark.py`
**Technique**: Sends the agent's output to an LLM judge for scoring on a 7-dimension rubric.
**What it tests**: Overall quality of the analysis as a financial research product — depth, coherence, actionability, professionalism.

**The 7 rubric dimensions** (adapted from CFA Research Challenge + FinDeepResearch HisRubric):

| Dimension | Weight | What It Evaluates |
|---|---|---|
| Data Accuracy & Traceability | 15% | Figures cited with sources? FRED/BLS references? |
| Analytical Depth | 20% | Explains *why*, not just *what*? Cause-effect chains? |
| Internal Coherence | 15% | Sections agree? Contradictions reconciled? |
| Actionability | 20% | Sector tilts? Duration calls? Risk management? |
| Completeness & Risk Assessment | 10% | Alternative scenarios? Base/bull/bear cases? |
| Professional Quality | 10% | Terminology, caveats, structure? |
| Signal Specificity & Originality | 10% | Cross-dimensional insights? Or generic enums? |

**Scoring**: 1-2 = missing/wrong, 3-4 = superficial, 5-6 = adequate, 7-8 = good analytical thinking, 9-10 = professional-grade.

**Modes**:
- Solo mode (`--solo`): Evaluates standalone, no reference. Used for baseline.
- Pairwise mode (`--ref <path>`): Compares agent vs a professional analyst report.

**Run**:
```bash
python taste/approach_4_comparative/comparative_benchmark.py --solo --input full_report_output.json
```

**Known limitation**: LLM judge scores have ~1-2 point variance per dimension across runs. The weighted score won't improve until narrative quality is actually enhanced (causal reasoning, actionable recommendations).

---

### Approach #5: Forward-Looking Signal Backtesting

**File**: `taste/approach_5_backtesting/signal_tracker.py`
**Technique**: Snapshot-then-verify longitudinal tracking.
**What it tests**: Whether the agent's directional signals actually predict reality.

**How it works** (3 phases):

1. **SNAPSHOT** (`python signal_tracker.py snapshot`):
   - Extracts all `signals` arrays from every tool in the full report
   - Matches each signal to `SIGNAL_DEFINITIONS` containing: category, predicted direction, verification metric, FRED series, and horizon (1w/4w/12w)
   - Saves snapshot with timestamp and 19 reference metric values

2. **VERIFY** (`python signal_tracker.py verify`):
   - Loads old snapshots that have matured past their verification horizon
   - Pulls current data for the verification metrics
   - Compares: did the metric move in the predicted direction?

3. **REPORT** (`python signal_tracker.py report`):
   - Aggregates into per-signal precision/recall/F1
   - Compares against a naive "no change" baseline

**Example signal definitions**:

| Signal | Direction | Verification Metric | Horizon |
|---|---|---|---|
| INFLATION_COOLING | down | CPI YoY decrease | 4w, 12w |
| ISM_CONTRACTION | down | ISM PMI stays < 50 | 4w |
| CREDIT_TIGHT | up | HY OAS widens or stays elevated | 4w |
| FED_EASING | down | Fed funds rate decreases | 4w, 12w |

**Run**:
```bash
python taste/approach_5_backtesting/signal_tracker.py snapshot  # Capture current signals
python taste/approach_5_backtesting/signal_tracker.py verify    # Check matured snapshots
python taste/approach_5_backtesting/signal_tracker.py report    # Aggregate accuracy
```

**Status**: Requires multiple snapshots over weeks to produce verification results. This is a long-running evaluation — no instant pass/fail.

---

### Approach #6: Data Accuracy Verification

**File**: `taste/approach_6_data_accuracy/data_accuracy_checker.py`
**Technique**: Pure Python arithmetic verification, cross-tool comparison, domain-rule checking. No LLM.
**What it tests**: Whether the numbers themselves are mathematically correct.

**7 check categories** (~64-70 checks total):

#### Category 1: Arithmetic Consistency (10 checks)
Verifies mathematical identities that must hold:

| Check ID | Formula | Tolerance |
|---|---|---|
| A-01 | 2s10s spread = 10Y - 2Y | +/-2bp |
| A-02 | Term premium = nominal_10Y - real_10Y - breakeven_10Y | +/-10bp |
| A-03 | HY-IG differential = HY_OAS - IG_OAS | +/-2bp |
| A-04 | OAS_pct × 100 = OAS_bps (for HY, IG, BBB) | +/-1bp |
| A-05 | Permits/starts ratio = permits / starts | +/-2% |
| A-06 | Monthly payment ≈ median_price × mortgage_rate / 12 | +/-5% |
| A-07 | 10Y breakeven ≈ nominal_10Y - real_10Y | +/-15bp |

#### Category 2: Cross-Tool Consistency (8 checks)
Same metric must agree across tools:

| Check ID | Metric | Tools Compared |
|---|---|---|
| X-01 | VIX | stress vs equity_drivers |
| X-02 | HY OAS | bond_market vs equity_drivers |
| X-03 | Real yield 10Y | equity_drivers vs bond_market |
| X-04 | Fed funds rate | macro_regime vs bond_market |
| X-05 | Nominal 10Y | yield_curve vs term_premium |
| X-06 | Credit spread direction | bond signals vs equity signals |
| X-07 | Mortgage rate | macro_regime vs housing_market |
| X-08 | Credit classification | consistent label across all tools |

#### Category 3: Composite Score Decomposition (4 checks)
Composite scores must equal the weighted average of their components:
- S-01: Financial stress score
- S-02: Consumer health score
- S-03: Late-cycle count
- S-04: Scan flagged_count

#### Category 4: Flag Alignment (~19 checks)
- F-01: Threshold flags match actual values (e.g., OIL_ELEVATED only fires if crude > threshold)
- F-02: 52-week proximity flags match current prices
- F-03: No implausible percentage moves (daily > +/-50%, monthly > +/-100%)

#### Category 5: Range Plausibility (16 checks)
All metrics within historically possible bounds:
```
vix: (8, 90), fed_funds_rate: (0, 7), cpi_yoy_pct: (-3, 15),
hy_oas_bps: (200, 2500), stress_score: (0, 10), ism_pmi: (30, 70), ...
```

#### Category 6: Internal Contradictions (5-7 checks)
Logically impossible combinations within a single tool:

| Check ID | What's Contradictory |
|---|---|
| I-01 | BREAKEVEN_RISING + BREAKEVEN_FALLING simultaneously |
| I-02 | CREDIT_LOOSE signal + credit regime "tight" |
| I-03 | CREDIT_TAILWIND signal + HY OAS > 300bps |
| I-04 | SALES_PLUNGING + leading indicator NO_WARNING |
| I-05 | Consumer health label vs numeric score mismatch |
| I-06 | Stress level label vs numeric score mismatch |
| I-07 | Housing phase "mixed" + multiple distress signals |

#### Category 7: Temporal Consistency (2 checks)
- T-01: All tools report same date/timestamp
- T-02: Fewer than 3 "data_unavailable" or null fields

**Run**:
```bash
python taste/approach_6_data_accuracy/data_accuracy_checker.py --input full_report_output.json
```

---

### Approach #7: Technical Analysis Tool Evaluation

**File**: `taste/approach_7_ta_evaluation/ta_evaluator.py`
**Technique**: Rule-based consistency checking across 6 TA tools per asset.
**What it tests**: Whether TA tool outputs are internally and cross-tool consistent for a given asset.

**What it checks**:
- RSI zone matches RSI numeric value (e.g., RSI 75 should be "overbought")
- Breakout confidence matches number of confirmations
- `quick_ta_snapshot` embeds RSI/S-R/breakout data that should agree with individual TA tool outputs
- `fundamental_ta_synthesis` embeds equity + TA data that should agree
- Signal plausibility: price near support shouldn't be AT_RESISTANCE; overbought RSI shouldn't pair with BULLISH_BREAKOUT

**Run**:
```bash
python taste/approach_7_ta_evaluation/ta_evaluator.py                     # Default assets: SPY, AAPL, gold, btc
python taste/approach_7_ta_evaluation/ta_evaluator.py --assets NVDA,TSLA  # Custom assets
```

---

## Command-Level Evaluators

In addition to the full-report approaches (#2–#7), there are two command-level evaluators that test individual commands with the same 4-approach methodology (accuracy, coherence, grounding, LLM judge):

### Batch 1 Command Evaluator

**File**: `taste/command_taste_evaluator.py`
**Commands**: `/analyze NVDA`, `/commodity crude_oil`, `/drivers`
**Checks**: 58 total (32 accuracy, 14 coherence, 9 grounding, 3 LLM judge)

```bash
python taste/command_taste_evaluator.py --input command_output_v1.json
```

### Batch 2 Command Evaluator

**File**: `taste/command_batch2_evaluator.py`
**Commands**: `/macro`, `/bonds`, `/stress`, `/latecycle`, `/consumer`, `/housing`, `/labor`, `/graham NVDA`, `/valuation`, `/vixanalysis`

```bash
python taste/command_batch2_evaluator.py --input command_output_batch2_v1.json
```

Both produce JSON + markdown reports in `taste/command_eval_records/`.

---

## Coverage Tracker

**File**: `taste/coverage_tracker.py`

Enumerates all /full_report tools, their output fields, and signals, then checks which fields are covered by which evaluation approach. Useful for identifying testing gaps.

```bash
python taste/coverage_tracker.py --input full_report_output.json
```

---

## Financial Agent Functions Under Test

These are the Financial Agent tool functions that the TASTE suite exercises. All are in `Financial_Agent/tools/`:

| File | Key Functions | Tested By |
|---|---|---|
| `macro_data.py` | `scan_all_indicators()`, `get_indicator_detail()` | #2, #5, #6, Batch 2 |
| `macro_market_analysis.py` | `analyze_macro_regime()` | #2, #3, #5, #6, Batch 2 |
| `market_regime_enhanced.py` | `analyze_financial_stress()` | #2, #3, #5, #6, Batch 2 |
| `macro_synthesis.py` | `detect_late_cycle_signals()` | #2, #3, #5, #6, Batch 2 |
| `equity_analysis.py` | `analyze_equity_valuation()`, `analyze_equity_drivers()` | #2, #3, #6, Batch 1 |
| `graham_analysis.py` | `graham_number_analysis()` | Batch 2 |
| `yardeni_frameworks.py` | `yardeni_valuation_analysis()` | Batch 2 |
| `commodity_analysis.py` | `analyze_commodity_outlook()` | Batch 1 |
| `consumer_housing_analysis.py` | `analyze_consumer_health()`, `analyze_housing_market()` | #2, #3, #6, Batch 2 |
| `murphy_ta.py` | `murphy_rsi_analysis()`, `murphy_support_resistance()`, `murphy_breakout_detection()`, `quick_ta_snapshot()` | #7 |
| `protrader_frameworks.py` | `fundamental_ta_synthesis()` | #7 |
| `fred_data.py` | Various FRED series fetchers | #5 (verification data) |
| `web_search.py` | `search_web()`, `search_news()` | Batch 2 |
| `btc_analysis.py` | `btc_trend_analysis()` | Batch 2 |

---

## How to Run the Full TASTE Suite

```bash
cd Testing_Agent/taste

# Step 1: Generate fresh Financial Agent output (or use saved JSON)
# The evaluators will call the Financial Agent tools directly if no --input is given.

# Step 2: Run each approach
python approach_2_coherence/coherence_checker.py --input full_report_output.json
python approach_3_grounding/grounding_evaluator.py --input full_report_output.json
python approach_4_comparative/comparative_benchmark.py --solo --input full_report_output.json
python approach_5_backtesting/signal_tracker.py snapshot
python approach_6_data_accuracy/data_accuracy_checker.py --input full_report_output.json
python approach_7_ta_evaluation/ta_evaluator.py

# Step 3: Run command-level evaluators
python command_taste_evaluator.py --input command_output_v1.json
python command_batch2_evaluator.py --input command_output_batch2_v1.json

# Step 4: Check coverage
python coverage_tracker.py --input full_report_output.json
```

Each approach saves results to its own `records/` directory as both JSON (machine-readable) and markdown (human-readable).

---

## Interpreting Results

| Approach | Pass Criteria | Current (v3) |
|---|---|---|
| #2 Coherence | 11/11 rules pass (100%) | 10/11 (90.9%) |
| #3 Grounding | > 80% claims grounded | 4/6 (66.7%) |
| #4 LLM Judge | Weighted score > 5.0/10 | 3.4/10 |
| #5 Backtesting | Signal accuracy > naive baseline | Snapshots taken, awaiting maturation |
| #6 Data Accuracy | > 95% checks pass, 0 critical | 59/64 (92.2%) |
| #7 TA Evaluation | All consistency checks pass | Baseline established |
| Command Batch 1 | > 90% checks pass, 0 critical | 49/58 (84.5%) |

---

## File Structure

```
taste/
├── taste_evaluation_report.md          # Main report with findings across v1-v3
├── taste_testing_context.md            # THIS FILE — methodology explainer
├── command_taste_evaluator.py          # Batch 1 command evaluator
├── command_batch2_evaluator.py         # Batch 2 command evaluator
├── coverage_tracker.py                 # Field/signal coverage analysis
├── command_evaluation_report.md        # Batch 1 command results
├── command_batch2_evaluation_report.md # Batch 2 command results
├── approach_2_coherence/
│   ├── coherence_checker.py            # 11 cross-tool logic rules
│   └── records/                        # Timestamped JSON + MD results
├── approach_3_grounding/
│   ├── grounding_evaluator.py          # 7 claim categories, threshold dictionary
│   └── records/
├── approach_4_comparative/
│   ├── comparative_benchmark.py        # LLM-as-Judge, 7-dimension rubric
│   ├── reference_reports/              # Professional analyst reports for pairwise mode
│   └── records/
├── approach_5_backtesting/
│   ├── signal_tracker.py               # Snapshot → verify → report lifecycle
│   └── records/snapshots/              # Timestamped signal snapshots
├── approach_6_data_accuracy/
│   ├── data_accuracy_checker.py        # 7 categories, ~64-70 checks
│   └── records/
├── approach_7_ta_evaluation/
│   ├── ta_evaluator.py                 # TA cross-tool consistency
│   └── records/
└── command_eval_records/               # Command-level evaluation results
```
