# Taste Evaluation Suite

A qualitative ("taste") testing framework for the Financial Agent. It evaluates agent output across **10 distinct approaches**, each targeting a different quality dimension — from logical coherence and data accuracy to narrative grounding and professional-grade analytical depth.

The suite supports both the `/full_report` pipeline (approaches #2–#6) and individual commands like `/analyze`, `/commodity`, `/ta`, etc. (command batch evaluators).

---

## Evaluation Approaches

### Approach #2: Internal Coherence & Contradiction Detection

**File:** `approach_2_coherence/coherence_checker.py`

Detects logical contradictions *between* tools within a single report. Uses pure Python rule-based checking (no LLM).

**What it tests:** Whether the agent's tools agree with each other. For example, if one tool says the economy is in a low-stress environment but another flags high credit spreads, that's a contradiction.

**11 rules checked:**

| Rule | What it catches |
|------|----------------|
| C-01 | Macro regime vs stress level mismatch |
| C-02 | Credit spread level vs narrative interpretation |
| C-03 | Yield curve shape vs late-cycle count |
| C-04 | Housing distress vs consumer health |
| C-05 | VIX level vs stress classification |
| C-06 | Growth regime vs ISM signal |
| C-07 | Contradictory signal pairs (mutually exclusive signals) |
| C-08 | Bank stress vs consumer credit |
| C-09 | Real yield direction vs equity narrative |
| C-10 | Rate regime vs Fed policy signals |
| C-11 | Scan flag rate vs stress level |

**Output:** JSON + markdown in `approach_2_coherence/records/` listing contradictions with severity and explanations.

---

### Approach #3: Narrative-vs-Data Grounding (Hallucination Detection)

**File:** `approach_3_grounding/grounding_evaluator.py`

Verifies that qualitative labels in narrative fields are actually supported by the underlying numeric data. Catches "hallucinated" assessments where the agent says one thing but the numbers say another.

**What it tests:** Whether labels like "tight credit", "elevated stress", or "strong consumer" are justified by the actual values. Uses a financial threshold dictionary that maps metrics to labeled ranges:

- `hy_oas_bps`: tight / normal / wide / stressed / distressed
- `vix`: complacent / calm / normal / elevated / fearful / panic
- `stress_score`: low / moderate / elevated / high / extreme
- `cpi_yoy_pct`: deflationary / low / moderate / warm / hot / very_hot
- `unemployment_pct`: very_tight / tight / normal / soft / weak
- `late_cycle_count`: early_cycle / mid_cycle / late_cycle / pre_recession
- And more (RSI, real yields, etc.)

**7 claim categories checked:** Credit spreads, stress level, VIX, inflation, late-cycle, real yields, consumer health.

**Output:** JSON + markdown in `approach_3_grounding/records/` showing grounded vs ungrounded claims with actual vs asserted labels.

---

### Approach #4: Comparative Benchmarking (LLM-as-Judge)

**File:** `approach_4_comparative/comparative_benchmark.py`

Evaluates overall output quality using an LLM judge that scores the agent on a 7-dimension rubric. Can run in solo mode (baseline quality) or pairwise mode (compared against professional analyst reports stored in `approach_4_comparative/reference_reports/`).

**What it tests:** Whether the agent's analysis meets professional standards for depth, actionability, and rigor.

**7 rubric dimensions (with weights):**

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Data Accuracy & Traceability | 15% | Are figures cited with sources? |
| Analytical Depth | 20% | Does it explain *why*, not just *what*? |
| Internal Coherence | 15% | Do sections logically agree? |
| Actionability | 20% | Sector tilts, duration calls, risk management? |
| Completeness & Risk Assessment | 10% | Alternative scenarios considered? |
| Professional Quality | 10% | Terminology, caveats, structure? |
| Signal Specificity & Originality | 10% | Cross-dimensional insights? |

**Scoring scale:** 1–2 = missing/wrong, 3–4 = superficial, 5–6 = adequate, 7–8 = good, 9–10 = professional-grade.

**Output:** JSON + markdown in `approach_4_comparative/records/` with per-dimension scores, weighted aggregate, and written critiques.

---

### Approach #5: Forward-Looking Signal Backtesting

**File:** `approach_5_backtesting/signal_tracker.py`

Tracks directional signals emitted by the agent and verifies them against actual market data after time elapses. This is the only approach that requires *waiting* — it operates on a snapshot → verify → report lifecycle.

**What it tests:** Whether the agent's forward-looking signals (e.g., "inflation cooling", "credit tightening") actually come true.

**3-phase lifecycle:**

1. **SNAPSHOT** — Captures all signals from `/full_report` with timestamps and reference metrics
2. **VERIFY** — After 1, 4, or 12 weeks, pulls actual market data and compares predicted vs actual direction
3. **REPORT** — Aggregates per-signal precision/recall/F1 vs a baseline

**Signal types tracked:** INFLATION_HOT, INFLATION_COOLING, GROWTH_EXPANSION, ISM_CONTRACTION, LABOR_TIGHT, CREDIT_TIGHT, FED_EASING, and more.

**Output:** JSON snapshots in `approach_5_backtesting/records/snapshots/`, verification results in `records/verifications/`.

---

### Approach #6: Data Accuracy Verification

**File:** `approach_6_data_accuracy/data_accuracy_checker.py`

Verifies mathematical correctness of numbers — not labels, but the actual arithmetic. Pure Python, no LLM.

**What it tests:** Whether the agent's calculations are correct: spread differentials, composite score decompositions, threshold flags, range plausibility, and temporal consistency.

**7 check categories (~64–70 checks total):**

| Category | # Checks | Examples |
|----------|----------|---------|
| Arithmetic Consistency | 10 | 2s10s spread, HY-IG differential, OAS ratios, breakeven equations |
| Cross-Tool Consistency | 8 | VIX, HY OAS, real yield, Fed funds match across tools |
| Composite Score Decomposition | 4 | Stress score, consumer health, late-cycle count equal weighted averages |
| Flag Alignment | ~19 | Threshold flags match actual values; no implausible daily (>50%) or monthly (>100%) moves |
| Range Plausibility | 16 | All metrics within historically possible bounds (VIX 8–90, Fed funds 0–7, etc.) |
| Internal Contradictions | 5–7 | No logically impossible combinations (e.g., BREAKEVEN_RISING + FALLING) |
| Temporal Consistency | 2 | Same date/timestamp across tools; < 3 null fields |

**Output:** JSON + markdown in `approach_6_data_accuracy/records/` with all failures, expected vs actual values, and explanations.

---

### Approach #7: Technical Analysis Coherence

**File:** `approach_7_ta_evaluation/ta_evaluator.py` + `ta_coherence_checker.py`

Verifies that TA tool outputs are internally consistent and agree with each other across the 6 TA tools per asset.

**What it tests:** Cross-tool consistency for technical analysis. For example, RSI zone labels must match RSI values, breakout confidence must match confirmation count, and `quick_ta_snapshot` data must align with individual TA tool outputs.

**Default assets tested:** SPY, AAPL, gold, BTC.

**Checks include:**
- RSI zone matches RSI numeric value (e.g., RSI 75 = "overbought")
- Breakout confidence matches number of confirmations
- `quick_ta_snapshot` RSI/S-R/breakout data matches individual TA tools
- `fundamental_ta_synthesis` equity + TA data agreement
- Signal plausibility (price near support shouldn't pair with AT_RESISTANCE)

**Output:** JSON + markdown in `approach_7_ta_evaluation/records/`.

---

### Approach #8: TA Data Accuracy (Mathematical Verification)

**File:** `approach_8_ta_accuracy/ta_accuracy_checker.py`

Recomputes technical indicators from raw price data and compares them to tool output. The definitive test of whether the TA tools calculate indicators correctly.

**What it tests:** Mathematical correctness of 25 indicator calculations per asset (75 total for 3 assets: BTC, gold, AAPL).

**25 checks per asset:**

| Check IDs | Indicator | What's verified |
|-----------|-----------|-----------------|
| TA-01..04 | RSI | Value, zone label, period |
| TA-05..09 | MACD | Line, signal, histogram, crossover |
| TA-10..14 | Bollinger Bands | Upper/lower/middle band, %B, bandwidth |
| TA-15..17 | Fibonacci | Key levels, retracement accuracy |
| TA-18..20 | Stochastic | %K, %D, zone label |
| TA-21..23 | Composite | Weighted signal score, direction label |
| TA-24..25 | Stop-loss | Entry/exit arithmetic |

**Tolerances:** RSI +-0.5 points, MACD/BB +-0.1% of price, composite +-0.02, zones must match exactly.

**Output:** JSON + markdown in `approach_8_ta_accuracy/records/` with recomputed vs tool values.

---

### Approach #9: TA Grounding (Label-to-Value Verification)

**File:** `approach_9_ta_grounding/ta_grounding_evaluator.py`

Verifies that textual labels and zone classifications match their underlying indicator values — the TA-specific equivalent of Approach #3.

**What it tests:** Whether TA labels are honest. 12 checks per asset (36 total for 3 assets).

**Threshold definitions:**

| Indicator | Zones |
|-----------|-------|
| RSI | oversold (0–30), bearish_momentum (30–50), bullish_momentum (50–70), overbought (70–100) |
| Stochastic | oversold (0–20), neutral (20–80), overbought (80–100) |
| Bollinger %B | below_lower (<0), near_lower (0–20), within (20–80), near_upper (80–100), above_upper (>100) |
| Composite | BEARISH (<-0.3), NEUTRAL (-0.3 to 0.3), BULLISH (>0.3) |

**Output:** JSON + markdown in `approach_9_ta_grounding/records/`.

---

### Approach #10: TA Quality LLM Judge

**File:** `approach_10_ta_benchmark/ta_benchmark.py`

Scores TA output quality using an LLM judge (MiniMax-M2.5) on a 7-dimension rubric — the TA-specific equivalent of Approach #4.

**What it tests:** Whether the TA analysis is actionable, well-synthesized, and professionally presented.

**7 dimensions (with weights):**

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| S/R Quality | 20% | Meaningful pivot levels, proper spacing, multi-timeframe |
| Entry/Exit Clarity | 20% | Actionable levels, stop-loss placement, risk/reward |
| Indicator Interpretation | 15% | Beyond simple labels; contextual analysis |
| Signal Synthesis | 15% | How conflicts between indicators are reconciled |
| Risk Management | 15% | Stop-loss sizing, position risk management |
| Pattern Detection | 5% | Chart patterns, technical setups |
| Professional Presentation | 10% | Terminology, structure, clarity |

**Scoring:** 10 = excellent, 8 = good, 6 = adequate, 4 = vague, 2 = minimal, 0 = missing.

**Output:** JSON + markdown in `approach_10_ta_benchmark/records/`.

---

## Command-Level Evaluators

Four batch evaluators test individual agent commands (not the full report) using the same approach techniques:

| Evaluator | Commands Tested |
|-----------|----------------|
| `command_taste_evaluator.py` (Batch 1) | `/analyze NVDA`, `/commodity crude_oil`, `/drivers` |
| `command_batch2_evaluator.py` (Batch 2) | `/macro`, `/bonds`, `/stress`, `/latecycle`, `/consumer`, `/housing`, `/labor`, `/graham NVDA`, `/valuation`, `/vixanalysis` |
| `command_batch3_evaluator.py` (Batch 3) | `/bbb`, `/fsmi`, `/vigilantes`, `/drawdown`, `/peers NVDA`, `/allocation NVDA`, `/balance NVDA`, `/riskpremium`, `/crossasset`, `/intermarket`, `/synthesize` |
| `command_batch4_evaluator.py` (Batch 4) | `/btc`, `/pmregime`, `/usdregime`, `/ta NVDA`, `/synthesis NVDA`, `/sl gold`, `/grahamscreen`, `/netnet`, `/compare` |

Each produces JSON + markdown reports in `command_eval_records/`.

## Re-Evaluation Scripts

Three scripts re-test commands after bug fixes to verify improvements and catch regressions:

| Script | Scope |
|--------|-------|
| `reeval_evaluator.py` | 6 commands with highest failure counts |
| `reeval_round2_evaluator.py` | 10 additional commands |
| `reeval_round3_evaluator.py` | 17 remaining commands |

Results and a detailed before/after comparison are in `reeval_comparison_report.md`.

## Support Scripts

| Script | Purpose |
|--------|---------|
| `coverage_tracker.py` | Maps which evaluation approaches cover which output fields/signals |
| `collect_ta_data.py` | Collects TA tool outputs + raw OHLCV data for BTC, gold, AAPL; saves to `ta_output_v1.json` |

## Reports

| Report | Contents |
|--------|----------|
| `taste_evaluation_report.md` | Full v1-v3 results for approaches #2–#6 on `/full_report` |
| `ta_evaluation_report.md` | Approaches #7–#10 results on TA assets |
| `command_evaluation_report.md` | Batch 1 results |
| `command_batch2_evaluation_report.md` | Batch 2 results |
| `command_batch3_4_evaluation_report.md` | Batches 3 & 4 combined results |
| `reeval_comparison_report.md` | Before/after analysis of all bug fixes |
| `taste_testing_context.md` | Master context doc explaining all 10 approaches and how to run them |

## Results Summary

| Approach | Checks | Pass Rate | Technique |
|----------|--------|-----------|-----------|
| #2 Coherence | 11 rules | 90.9% | Rule-based (no LLM) |
| #3 Grounding | 6–10 claims | 66.7% | Rule-based + threshold dict |
| #4 LLM Judge | 7 dimensions | 3.4/10 | LLM-as-judge (Claude/MiniMax) |
| #5 Backtesting | 19 signals | Pending | Snapshot-verify lifecycle |
| #6 Data Accuracy | 64 checks | 92.2% | Arithmetic verification |
| #7 TA Coherence | 45 checks | 100% | Rule-based cross-tool |
| #8 TA Accuracy | 75 checks | 85.3% | Indicator recomputation |
| #9 TA Grounding | 36 checks | 100% | Threshold dictionary |
| #10 TA LLM Judge | 7 dimensions | 6.15/10 | LLM-as-judge (MiniMax) |
