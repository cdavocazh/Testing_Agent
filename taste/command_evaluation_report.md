# Command-Level Taste Evaluation Report

**Date**: 2026-03-12
**Commands Evaluated**: `/analyze NVDA`, `/commodity crude_oil`, `/drivers`
**Evaluation Version**: v1 (baseline)

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Checks | 58 |
| Passed | 49 (84.5%) |
| Failed | 9 |
| Critical Failures | 6 |
| LLM Judge (Equity) | 5.2/10 |
| LLM Judge (Commodity) | 4.0/10 |
| LLM Judge (Drivers) | 6.1/10 |

### Severity Breakdown

| Severity | Count | Failed |
|----------|-------|--------|
| Critical | 6 | 6 |
| High | 7 | 3 |
| Medium | ~30 | 0 |
| Low | ~15 | 0 |

---

## Results by Approach

| Approach | Total | Passed | Failed | Rate |
|----------|-------|--------|--------|------|
| Data Accuracy | 32 | 28 | 4 | 88% |
| Coherence | 14 | 12 | 2 | 86% |
| Grounding | 9 | 7 | 2 | 78% |
| LLM Judge | 3 | 2 | 1 | 67% |

## Results by Command

| Command | Total | Passed | Failed | Rate |
|---------|-------|--------|--------|------|
| `/analyze NVDA` (equity) | 27 | 24 | 3 | 89% |
| `/commodity crude_oil` | 12 | 9 | 3 | 75% |
| `/drivers` | 18 | 15 | 3 | 83% |
| Cross-command | 1 | 1 | 0 | 100% |

---

## Bugs Found

### BUG-CMD-1: NVDA Data Extremely Stale (2020-Q2) [CRITICAL]

**Check**: EA-14
**Command**: `/analyze NVDA`
**Impact**: The equity valuation tool returns data from **2020-Q2** — over 5 years old. This is NVIDIA's pre-AI-boom era. Revenue was $3.08B/quarter; by 2024 NVIDIA was doing $22B+/quarter. Any valuation analysis based on this data is completely useless for investment decisions.

**Root Cause**: The SEC EDGAR data pipeline (`/macro_2/historical_data/equity_financials/sec_edgar/NVDA_quarterly.csv`) has not been updated. The data ingestion likely stopped fetching new filings.

**Fix**: Update the SEC EDGAR data pipeline to fetch recent quarterly filings (10-Q/10-K). Alternatively, add a staleness warning flag when latest_quarter is > 2 quarters old.

---

### BUG-CMD-2: Cash Flow "Weak" Interpretation at OCF/NI = 0.99 [CRITICAL]

**Check**: EC-03, GE-01
**Command**: `/analyze NVDA`
**Impact**: `ocf_to_net_income = 0.99` means 99 cents of operating cash flow for every dollar of net income — excellent cash conversion. But the tool labels this "Weak — earnings may not be backed by cash."

**Root Cause**: `equity_analysis.py` line 423:
```python
cfq["interpretation"] = "Strong" if ocf_ni > 1.0 else "Weak — earnings may not be backed by cash"
```
Threshold is `> 1.0` (strict greater-than). A 0.99 ratio misses by 0.01 and gets incorrectly labeled "Weak." Industry standard considers `>= 0.7` as strong cash conversion.

**Fix**: Change threshold to `>= 0.8` for "Strong" and add intermediate tiers:
```python
if ocf_ni >= 0.8: "Strong — cash flow well supports earnings"
elif ocf_ni >= 0.5: "Adequate — moderate cash conversion"
else: "Weak — earnings may not be backed by cash"
```

---

### BUG-CMD-3: All Oil S/R Levels Below Current Price [CRITICAL]

**Check**: CA-02, CA-08
**Command**: `/commodity crude_oil`
**Impact**: Oil is at **$94.80** (52-week high), but ALL support levels (55.99, 59.27, 62.23) and ALL resistance levels (58.32, 62.02, 65.06) are far below the current price. The nearest level is 34% below price. These S/R levels are completely useless — they were computed from the price range 55-65, not from current trading levels.

**Root Cause**: The S/R computation (`_compute_support_resistance` in `commodity_analysis.py`) uses the full CSV history. If oil recently spiked from ~60 to ~95, the pivot-based algorithm finds historical pivots in the 55-65 range but none near 95 (because there's insufficient data at that level).

**Fix**:
1. Use a lookback window that includes recent price action (e.g., last 60 bars, not full history)
2. Add validation: if ALL supports/resistances are > 30% from current price, flag as unreliable
3. Add round-number levels (80, 85, 90, 95, 100) as synthetic S/R when historical levels are irrelevant

---

### BUG-CMD-4: DXY Interpretation Contradicts Direction [CRITICAL]

**Check**: DC-01
**Command**: `/drivers`
**Impact**: DXY at 99.5, WoW change +0.74% (strengthening). Interpretation says **"Weak dollar — tailwind for multinationals, EM"**. The dollar is actually getting stronger this week, not weaker — the "tailwind" characterization is misleading.

**Root Cause**: `macro_market_analysis.py` line 689:
```python
elif latest_dxy < 100:
    dxy_impact["interpretation"] = "Weak dollar — tailwind for multinationals, EM"
```
The interpretation is based **solely on level** (DXY < 100 = "weak"), ignoring direction. A rising DXY from 98.8 to 99.5 is dollar strength, not weakness. The signal logic (line 691) correctly checks direction before emitting `DOLLAR_TAILWIND`, but the interpretation text doesn't.

**Fix**: Incorporate direction into interpretation:
```python
elif latest_dxy < 100:
    if wow_chg > 0.3:
        interp = f"DXY at {latest_dxy} (rising) — dollar strengthening from low base"
    elif wow_chg < -0.3:
        interp = "Weak dollar — tailwind for multinationals, EM"
    else:
        interp = f"DXY at {latest_dxy} — weak range, stable"
```

---

### BUG-CMD-5: Equity Risk Premium Unavailable [CRITICAL]

**Check**: DA-05
**Command**: `/drivers`
**Impact**: ERP is returned as `{"status": "data_unavailable"}`. This is the **single most important equity valuation metric** — it tells you whether stocks are cheap or expensive relative to bonds. Without ERP, the `/drivers` command is missing its core value proposition.

**Root Cause**: The ERP calculation requires S&P 500 P/E ratio from `sp500_fundamentals.csv` and 10Y real yield. If the P/E data is missing or stale, ERP can't be computed.

**Fix**:
1. Investigate why `sp500_fundamentals.csv` is missing or has no P/E data
2. Add fallback: compute P/E from earnings estimates or use a proxy (e.g., Shiller CAPE)
3. If truly unavailable, surface an explicit warning rather than silent `data_unavailable`

---

### BUG-CMD-6: Crude Oil Inventory Data Failed [HIGH]

**Check**: LLM-COM dimension critique
**Command**: `/commodity crude_oil`
**Impact**: Crude inventories, gasoline stocks, and distillate stocks all show `"error": "Failed to fetch crude inventory data"`. For an oil analysis tool, inventory data is fundamental — it's the primary supply-demand indicator.

**Root Cause**: The FRED API calls for inventory data are failing, likely due to API rate limits, incorrect series IDs, or expired API key.

**Fix**: Verify FRED API key validity and series IDs for crude inventory (WCESTUS1), gasoline stocks (WGTSTUS1), and distillate stocks (WDISTUS1).

---

### BUG-CMD-7: Insufficient Seasonal History (70 days) [MEDIUM]

**Check**: LLM-COM
**Command**: `/commodity crude_oil`
**Impact**: `"seasonal_pattern": {"status": "insufficient_history", "days_available": 70}`. With only 70 days of data, seasonal patterns can't be computed (needs 180+ days). This means a major analytical component is missing.

**Root Cause**: The `crude_oil.csv` file only contains ~70 rows of historical data. Seasonal analysis requires at least 1 year.

**Fix**: Extend crude oil price history. FRED series DCOILWTICO provides WTI daily prices going back decades.

---

## Potential False Positive

### GD-05: Credit Stress Level Mismatch

**Check**: GD-05
**Command**: `/drivers`
**Detail**: HY OAS at 313bps classified as "elevated" vs. my threshold dict expecting "normal" (250-350bps).

**Resolution**: NOT a bug. The tool uses **percentile-based classification** (313bps at 73rd percentile → "elevated" per 60-80th range), not fixed BPS thresholds. My grounding check's threshold dictionary was using absolute BPS ranges, which doesn't match the tool's regime-aware classification. The tool's approach is actually **better** — it auto-calibrates to the current regime.

---

## LLM Judge Results

### `/analyze NVDA` — 5.2/10

| Dimension | Weight | Score |
|-----------|--------|-------|
| Data Freshness & Coverage | 20% | 3 |
| Analytical Depth | 20% | 7 |
| Internal Consistency | 15% | 4 |
| Actionability | 20% | 5 |
| Completeness | 15% | 6 |
| Professional Quality | 10% | 7 |

**Key critique**: Severely outdated data (2020-Q2) undermines the entire analysis despite good structural coverage. Internal consistency issues with cash flow interpretation and chronologically inverted YoY comparison.

### `/commodity crude_oil` — 4.0/10

| Dimension | Weight | Score |
|-----------|--------|-------|
| Price Context & Technicals | 20% | 5 |
| Fundamental Drivers | 20% | 2 |
| Cross-Asset Integration | 15% | 6 |
| Signal Quality | 20% | 4 |
| Risk Assessment | 15% | 4 |
| Data Completeness | 10% | 3 |

**Key critique**: Multiple data failures (inventories, seasonal patterns) plus useless S/R levels (all below current price) make this the weakest of the three commands. Signals are observational flags, not actionable trading recommendations.

### `/drivers` — 6.1/10

| Dimension | Weight | Score |
|-----------|--------|-------|
| Factor Coverage | 15% | 8 |
| Quantitative Rigor | 20% | 6 |
| Signal Generation | 20% | 5 |
| Cross-Factor Synthesis | 20% | 6 |
| Correlation Analysis | 15% | 6 |
| Actionability & Clarity | 10% | 6 |

**Key critique**: Best structured of the three. Good factor coverage and correlation analysis. Weakened by missing ERP, empty signals array, DXY interpretation contradiction, and lack of explicit portfolio implications.

---

## Cross-Approach Convergence

Several bugs are independently detected by multiple approaches:

| Bug | Accuracy | Coherence | Grounding | LLM Judge |
|-----|----------|-----------|-----------|-----------|
| BUG-CMD-1 (Stale NVDA data) | EA-14 | — | — | "3/10 freshness" |
| BUG-CMD-2 (OCF/NI label) | — | EC-03 | GE-01 | "4/10 consistency" |
| BUG-CMD-3 (Oil S/R levels) | CA-02, CA-08 | — | — | "5/10 technicals" |
| BUG-CMD-4 (DXY contradiction) | — | DC-01 | — | — |
| BUG-CMD-5 (ERP unavailable) | DA-05 | — | — | "flagged unavailable" |
| BUG-CMD-6 (Inventory failures) | — | — | — | "2/10 fundamentals" |

---

## Priority Recommendations

### P0 — Must Fix (Critical, blocks usability)
1. **BUG-CMD-1**: Update SEC EDGAR data pipeline for NVDA (and likely all tickers)
2. **BUG-CMD-5**: Investigate and restore ERP data availability
3. **BUG-CMD-3**: Fix S/R computation to handle price spikes (use recent lookback window)

### P1 — Should Fix (High severity, causes incorrect analysis)
4. **BUG-CMD-2**: Change OCF/NI "Strong" threshold from `> 1.0` to `>= 0.8`
5. **BUG-CMD-4**: Incorporate direction into DXY interpretation (not just level)
6. **BUG-CMD-6**: Fix FRED API calls for crude inventory data

### P2 — Nice to Fix (Improves quality)
7. **BUG-CMD-7**: Extend crude oil price history for seasonal analysis
8. Add staleness warnings when data is > 2 quarters old
9. Add empty-signal explanation when no signals fire (explain why conditions weren't met)

---

## Test Infrastructure

- **Evaluator script**: `taste/command_taste_evaluator.py`
- **Data file**: `command_output_v1.json`
- **Records**: `taste/command_eval_records/command_eval_20260312_111129.{json,md}`
- **LLM Judge**: MiniMax-M2.5 via OpenAI-compatible API
- **Approaches applied**: Data Accuracy (32 checks), Coherence (14 checks), Grounding (9 checks), LLM Judge (3 scores)

---

## Sample Fix-and-Retest Prompt

After fixing the bugs above, re-run:
```bash
# Collect fresh data
FINANCIAL_AGENT_ROOT=/path/to/Financial_Agent python3 taste/command_taste_evaluator.py

# Or test against saved output
python3 taste/command_taste_evaluator.py --input command_output_v2.json
```

Expected improvements in v2:
- EA-14 passes if NVDA data updated to recent quarters
- EC-03/GE-01 pass if OCF/NI threshold changed
- CA-02/CA-08 pass if S/R computation uses recent lookback
- DA-05 passes if ERP data restored
- DC-01 passes if DXY interpretation considers direction
- LLM scores should improve significantly (especially commodity from 4.0 and equity from 5.2)
