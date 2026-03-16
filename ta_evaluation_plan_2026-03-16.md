# Plan: Technical Analysis (TA) Taste Evaluation Suite

## Context

The existing taste evaluation (Approaches #2-#6) tests the `/full_report` macro analysis pipeline. Now we need to evaluate the **technical analysis** tools — specifically the quality of support/resistance levels, entry/stop-loss points, indicator calculations, and signal coherence. The Financial Agent has a production-grade TA toolkit (`murphy_ta.py` with 13 frameworks, `protrader_sl.py` with stop-loss framework, `protrader_frameworks.py` with cross-asset analysis) that needs the same rigor of qualitative testing.

The evaluation runs against **3 test assets** to catch data-source-specific issues:
- **BTC** — Full 5min OHLCV, resampled. Most data.
- **Gold** — Close-only macro CSV, synthesized OHLC (tests degraded data handling).
- **AAPL** — yfinance daily OHLCV (tests stock/ETF path).

---

## Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `taste/collect_ta_data.py` | Data collection: calls all TA tools for 3 assets, saves raw price data + outputs | ~200 |
| `taste/approach_7_ta_coherence/ta_coherence_checker.py` | Cross-signal coherence checks within TA output | ~500 |
| `taste/approach_8_ta_accuracy/ta_accuracy_checker.py` | Mathematical verification (recompute indicators from raw data) | ~700 |
| `taste/approach_9_ta_grounding/ta_grounding_evaluator.py` | Label-to-value verification (do labels match indicator values?) | ~400 |
| `taste/approach_10_ta_benchmark/ta_benchmark.py` | LLM-as-Judge rubric evaluation for TA quality | ~500 |
| `taste/ta_evaluation_report.md` | Generated after running all approaches | — |

## Implementation Order

### Step 1: Data Collection Script (`collect_ta_data.py`)

Collects TA output for 3 assets. For each asset, calls:
1. `murphy_technical_analysis(asset, "1D")` — Full 13-framework TA
2. `find_support_resistance(asset, "1D", 100)` — Standalone S/R
3. `calculate_rsi(asset, 14, "1D", "7,9,21")` — Multi-period RSI
4. `analyze_breakout(asset, "1D")` — Breakout with confirmations
5. `quick_ta_snapshot(asset, "1D")` — Combined RSI+S/R+breakout
6. `protrader_stop_loss_framework(...)` — Stop-loss (inputs extracted from murphy output)

Also collects once: `protrader_risk_premium_analysis()`, `protrader_cross_asset_momentum()`.

**Critical**: Also stores `raw_price_data` (last 250 bars of close/high/low/open/volume) for each asset so Approach #8 can recompute indicators offline.

CLI: `python collect_ta_data.py [--output ta_data.json]`

Save format: `ta_output_v1.json` with structure `{assets: {btc: {murphy_full, support_resistance, rsi, breakout, quick_snapshot, stop_loss, raw_price_data}, ...}, cross_asset: {...}}`.

### Step 2: Approach #8 — TA Data Accuracy (Mathematical Verification)

**25 checks per asset** (75 total). Recomputes indicators from raw price data and compares to tool output.

| Category | Checks | What's Verified |
|----------|--------|-----------------|
| RSI Verification (4) | TA-01 to TA-04 | RSI(14), RSI(7), RSI(21) values and zone classification |
| MACD Verification (5) | TA-05 to TA-09 | MACD line, signal line, histogram value/sign, centerline |
| Bollinger Verification (5) | TA-10 to TA-14 | Upper/lower/middle bands, bandwidth%, %B |
| Fibonacci Verification (3) | TA-15 to TA-17 | Fib 38.2%, 61.8% levels and zone classification |
| Stochastic Verification (3) | TA-18 to TA-20 | %K, %D values and zone |
| Composite Signal (3) | TA-21 to TA-23 | Vote counts, score computation, signal classification |
| Stop-Loss Arithmetic (2) | TA-24 to TA-25 | Swing stop level, ATR stop level |

Tolerances: RSI ±0.5 points, MACD/BB ±0.1% of price, composite score ±0.02, zone labels exact match.

### Step 3: Approach #7 — TA Internal Coherence

**15 checks per asset** (45 total). Cross-checks signals within and across TA tool outputs.

| Category | Checks | What's Verified |
|----------|--------|-----------------|
| Signal Direction (5) | TC-01 to TC-05 | Composite vs. trend, MACD crossover vs. histogram, RSI vs. Stochastic, BB %B vs. RSI |
| S/R Consistency (3) | TC-06 to TC-08 | All supports < price < all resistances, murphy vs. standalone S/R match, level spacing (no duplicates) |
| Cross-Tool (4) | TC-09 to TC-12 | RSI murphy vs. standalone, breakout vs. trend direction, breakout level in S/R list, quick_snapshot vs. individual tools |
| Stop-Loss (3) | TC-13 to TC-15 | Stop below entry for longs, swing stop near S/R level, position sizing arithmetic |

### Step 4: Approach #9 — TA Grounding

**12 checks per asset** (36 total). Verifies labels match indicator values.

Threshold dictionary for TA labels:
```
RSI: oversold=(0,30), bearish_momentum=(30,50), bullish_momentum=(50,70), overbought=(70,100)
Stochastic: oversold=(0,20), neutral=(20,80), overbought=(80,100)
Bollinger %B: below_lower=(<0), near_lower=(0,20), within=(20,80), near_upper=(80,100), above_upper=(>100)
Composite: BEARISH=(<-0.3), NEUTRAL=(-0.3,0.3), BULLISH=(>0.3)
```

| Check ID | What's Verified |
|----------|-----------------|
| TG-01 | RSI zone label matches value |
| TG-02 | RSI divergence label correct |
| TG-03 | Stochastic zone label matches %K |
| TG-04 | Stochastic crossover label correct |
| TG-05 | Bollinger squeeze label matches bandwidth |
| TG-06 | Bollinger position label matches %B |
| TG-07 | MACD crossover label matches histogram sign change |
| TG-08 | Trend direction label matches swing structure |
| TG-09 | MA crossover label ("GOLDEN_CROSS"/"DEATH_CROSS") matches SMA values |
| TG-10 | Composite signal label matches score |
| TG-11 | Confidence label matches score magnitude |
| TG-12 | Breakout confidence matches confirmation count |

### Step 5: Approach #10 — TA Quality LLM Judge

**7 rubric dimensions**, scored per asset. Uses same LLM infrastructure as Approach #4.

| Dimension | Weight | What It Evaluates |
|-----------|--------|-------------------|
| S/R Quality | 20% | Meaningful pivot levels, proper spacing, key turning points |
| Entry/Exit Clarity | 20% | Actionable entry points, stop-loss placement, risk/reward |
| Indicator Interpretation | 15% | Beyond simple labels — divergences, context, multi-timeframe |
| Signal Synthesis | 15% | Composite logic, conflicting signal reconciliation |
| Risk Management | 15% | Position sizing, trailing stops, Fidenza framework value |
| Pattern Detection | 5% | Chart patterns correctly identified with targets |
| Professional Presentation | 10% | Organization, terminology, trader-useful output |

### Step 6: Run All Approaches + Write Report

1. Collect data: `python collect_ta_data.py`
2. Run 4 approaches against saved data
3. Write `ta_evaluation_report.md` with scorecard, per-asset breakdown, bug list, and recommendations

---

## Key Design Decisions

- **Raw price data stored with outputs**: Approach #8 needs to independently recompute indicators. Storing 250 bars of OHLCV eliminates the need to re-fetch data and ensures deterministic verification.
- **Gold's degraded data**: Gold has synthesized OHLC (open=high=low=close). Volume checks are skipped, Stochastic may be degenerate. Tests must handle this gracefully.
- **Stop-loss integration**: The collection script bridges `murphy_technical_analysis` output into `protrader_stop_loss_framework` inputs (extracts current_price, swing_low, swing_high, computes ATR from raw data).
- **Separate report from macro**: `ta_evaluation_report.md` is a companion to the existing `taste_evaluation_report.md`, not a replacement. Same numbering space (approaches 7-10 continue from 2-6).

## Critical Reference Files

- `/Users/kriszhang/Github/Financial_Agent/tools/murphy_ta.py` — Primary TA tool. RSI (lines 435-488), MACD (393-432), Bollinger (490-537), S/R (247-294), Stochastic (830-881), Fibonacci (540-584), Composite (888-1054)
- `/Users/kriszhang/Github/Financial_Agent/tools/protrader_sl.py` — Stop-loss framework (lines 186-430)
- `/Users/kriszhang/Github/Financial_Agent/tools/protrader_frameworks.py` — Cross-asset analysis
- `/Users/kriszhang/Github/Agents/Testing_Agent/taste/approach_2_coherence/coherence_checker.py` — Pattern template for Approach #7
- `/Users/kriszhang/Github/Agents/Testing_Agent/taste/approach_6_data_accuracy/data_accuracy_checker.py` — Pattern template for Approach #8
- `/Users/kriszhang/Github/Agents/Testing_Agent/taste/approach_3_grounding/grounding_evaluator.py` — Pattern template for Approach #9
- `/Users/kriszhang/Github/Agents/Testing_Agent/taste/approach_4_comparative/comparative_benchmark.py` — Pattern template for Approach #10

## Verification

After implementation:
1. Run `python collect_ta_data.py` — expect all 3 assets' TA data collected successfully
2. Run each approach with `--input ta_output_v1.json` — expect all produce results without errors
3. Validate that raw-data recomputation (Approach #8) produces values within tolerance of tool outputs
4. Verify that any bugs found are real by cross-referencing with the actual indicator source code in `murphy_ta.py`
5. Generate `ta_evaluation_report.md` summarizing findings across all 4 approaches and 3 assets
