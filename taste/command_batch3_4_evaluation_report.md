# Command-Level Taste Evaluation Report — Batches 3 & 4

**Date**: 2026-03-12
**Batch 3 Commands**: `/bbb`, `/fsmi`, `/vigilantes`, `/drawdown`, `/peers NVDA`, `/allocation NVDA`, `/balance NVDA`, `/riskpremium`, `/crossasset`, `/intermarket`, `/synthesize`
**Batch 4 Commands**: `/btc`, `/pmregime`, `/usdregime`, `/ta NVDA`, `/synthesis NVDA`, `/sl gold 3348 long`, `/grahamscreen`, `/netnet`, `/compare NVDA AAPL MSFT`

---

## Executive Summary

| Metric | Batch 3 | Batch 4 | Combined B3+B4 |
|--------|---------|---------|----------------|
| Commands | 11 | 9 | 20 |
| Total Checks | 48 | 40 | 88 |
| Passed | 36 (75.0%) | 33 (82.5%) | 69 (78.4%) |
| Failed | 12 | 7 | 19 |
| Critical Failures | 3 | 2 | 5 |
| LLM Judge Scores | 5.0, 5.95, 7.05 | 5.0, 5.0, 5.0 | Avg: 5.4/10 |

---

## LLM Judge Scores (All Groups)

| Group | Commands | Score |
|-------|----------|-------|
| Yardeni Suite | `/bbb`, `/vigilantes`, `/drawdown` | 5.0/10 |
| Equity Deep-Dive | `/peers`, `/allocation`, `/balance` | 5.95/10 |
| Pro-Trader Suite | `/riskpremium`, `/crossasset`, `/intermarket`, `/synthesize` | 7.05/10 |
| BTC/PM/USD | `/btc`, `/pmregime`, `/usdregime` | 5.0/10 |
| TA/Synthesis/SL | `/ta NVDA`, `/synthesis NVDA`, `/sl gold` | 5.0/10 |
| Screens/Compare | `/grahamscreen`, `/netnet`, `/compare` | 5.0/10 |

**Best**: Pro-Trader Suite (7.05/10) — signals, correlations, and multi-asset narrative are strong
**Worst**: Tied at 5.0/10 — Yardeni, BTC/PM/USD, TA/Synthesis, Screens all dragged down by data issues

---

## Results by Command (Both Batches)

| Command | Checks | Passed | Failed | Rate | Key Issue |
|---------|--------|--------|--------|------|-----------|
| `/btc` | 4 | 4 | 0 | 100% | — |
| `/drawdown` | 3 | 3 | 0 | 100% | — |
| `/riskpremium` | 3 | 3 | 0 | 100% | — |
| `/crossasset` | 2 | 2 | 0 | 100% | — |
| `/intermarket` | 2 | 2 | 0 | 100% | — |
| `/pmregime` | 3 | 3 | 0 | 100% | — |
| `/netnet` | 2 | 2 | 0 | 100% | — |
| `/grahamscreen` | 3 | 3 | 0 | 100% | — |
| `/ta NVDA` | 3 | 2 | 1 | 67% | 2 frameworks missing |
| `/synthesize` | 2 | 2 | 0 | 100% | Sparse recommendations |
| `/usdregime` | 4 | 2 | 2 | 50% | Death cross + "strength" |
| `/sl gold` | 3 | 1 | 2 | 33% | Missing ATR/swing stops |
| `/bbb` | 3 | 1 | 2 | 33% | BBB ratio = 0 bug |
| `/allocation NVDA` | 4 | 1 | 3 | 25% | Negative shares, wrong label |
| `/synthesis NVDA` | 2 | 0 | 2 | 0% | All fundamentals null |
| `/vigilantes` | 3 | 0 | 3 | 0% | All data missing |
| `/compare` | 2 | 1 | 1 | 50% | Stale 2019-2020 data |
| `/peers NVDA` | 2 | 1 | 1 | 50% | Stale 2019-2020 data |
| `/balance NVDA` | 2 | 1 | 1 | 50% | Latest summary = oldest quarter |
| `/fsmi` | 1 | 0 | 1 | 0% | Crashes on execution |

---

## Bugs Found

### BUG-B3-1: FSMI Crashes — Timestamp Float Conversion [CRITICAL]

**Check**: FSMI-01
**Command**: `/fsmi`
**Impact**: The Fundamental Stock Market Indicator command **crashes immediately** with `float() argument must be a string or a real number, not 'Timestamp'`. The entire command is unusable.

**Root Cause**: `yardeni_frameworks.py` — the `get_fsmi()` function passes a pandas Timestamp object to `float()` instead of the numeric value associated with that timestamp. Likely a column selection bug where a date column is accessed instead of a value column.

**Fix**: Use `.iloc[0]` or explicit value extraction before calling `float()`.

---

### BUG-B3-2: Bond Vigilantes — All Data Null [CRITICAL]

**Checks**: VIG-01, VIG-02, VIG-03
**Command**: `/vigilantes`
**Impact**: Both `yield_10y` and `nominal_gdp_yoy_pct` are null, resulting in `regime: "insufficient_data"`. The entire Bond Vigilantes Model is non-functional. This is notable because the 10Y yield IS available in other commands (`/bonds` shows 4.15%), meaning the data pipeline is broken specifically in the vigilantes function.

**Root Cause**: `yardeni_frameworks.py` — `analyze_bond_vigilantes()` likely fetches 10Y yield from a different source or key than the bond analysis tool, and that path returns null. GDP YoY requires BEA/FRED GDP data which may be stale or misconfigured.

**Fix**: Use the same yield data source as `analyze_bond_market()` for consistency. Add fallback for GDP data.

---

### BUG-B3-3: BBB Ratio = 0 Despite Copper = 5.88 [HIGH]

**Checks**: BBB-01, GR3-01
**Command**: `/bbb`
**Impact**: The Boom-Bust Barometer ratio is 0.0 when it should be approximately 0.0276 (5.88 / 213). The interpretation says "contraction_signal — recessionary dynamics" but this is based on a zero ratio (data bug), not actual economic contraction. False recession signal.

**Root Cause**: `yardeni_frameworks.py` — `get_boom_bust_barometer()` division may be using wrong units. If `initial_claims = 213000` (raw) and `copper_price = 5.88` (per pound), the ratio `5.88 / 213000 ≈ 0.0000276` rounds to 0.0 at 1 decimal. The code needs to divide by claims in thousands (213) not raw (213000).

**Fix**: `bbb_ratio = copper_price / (initial_claims / 1000)` to get the proper scale (~0.0276).

---

### BUG-B3-4: All Peer Data from 2019-2020 (SEC EDGAR Stale) [CRITICAL]

**Checks**: PEER-02, CC3-07
**Command**: `/peers NVDA`
**Impact**: All 9 peers (NVDA, ADI, AMAT, AMD, AVGO, FSLR, INTC, KLAC, LRCX) use data from 2019-Q3 to 2020-Q2. The semiconductor industry has transformed dramatically since then (AI boom, supply chain restructuring). Peer comparisons using 5-year-old data provide misleading relative valuations.

**Root Cause**: Same SEC EDGAR stale data pipeline affecting `/analyze`, `/graham`, `/compare`, `/balance`, `/allocation`. The entire SEC filing ingestion pipeline stopped updating around 2020.

---

### BUG-B3-5: Negative Diluted Shares in Allocation [HIGH]

**Check**: ALLOC-02
**Command**: `/allocation NVDA`
**Impact**: 5 out of 24 quarters show **negative** diluted share counts (e.g., 2026-Q1: -49,112,000,000). This is physically impossible — share counts cannot be negative. It likely represents a sign error in parsing the cash flow statement (share repurchases stored as negative, then used as share count).

**Root Cause**: `equity_analysis.py` — `analyze_capital_allocation()` appears to confuse the dollar amount of share repurchases (negative in cash flow) with the diluted share count field.

**Fix**: Source diluted shares from the income statement or balance sheet (weighted average diluted shares), not from the cash flow statement.

---

### BUG-B3-6: Buyback Strategy "Inactive" Despite $3.8B Repurchases [HIGH]

**Checks**: ALLOC-04, GR3-08
**Command**: `/allocation NVDA`
**Impact**: Latest quarter (2026-Q1) shows $3.815B in share repurchases, yet `latest_quarter_summary.buyback_strategy = "inactive"`. This contradicts the actual data — NVDA is actively buying back billions in shares.

**Root Cause**: `equity_analysis.py` — The `latest_quarter_summary` appears to reference the **first** quarter in the array (2020-Q2, which had no buybacks) rather than the **last** (2026-Q1). Same ordering bug as BUG-B3-7.

---

### BUG-B3-7: Balance Sheet Latest Summary = Oldest Quarter [HIGH]

**Check**: BAL-01
**Command**: `/balance NVDA`
**Impact**: `latest_summary` references 2020-Q2 data (the oldest quarter in the 24-quarter range), not 2026-Q1 (the newest). The summary shows DSO=55.72, CCC=86.42, WC=$17.7B — all from 6 years ago. Current metrics are likely very different given NVDA's 10x revenue growth since 2020.

**Root Cause**: `equity_analysis.py` — `latest_summary = quarterly_data[0]` but the array is sorted oldest-first (ascending), so `[0]` is the oldest. Should use `[-1]` for latest.

**Fix**: `latest_summary = quarterly_data[-1]`

---

### BUG-B4-1: Synthesis NVDA — All Fundamental Metrics Null [CRITICAL]

**Check**: SYN-01
**Command**: `/synthesis NVDA`
**Impact**: All 6 fundamental metrics (PE ratio, revenue growth, EPS growth, ROE, gross margin, net margin) are null. The fundamental signal defaults to "NEUTRAL" and the synthesis provides "Mixed or neutral signals" with LOW conviction. The tool is designed to combine fundamentals + technicals, but with no fundamentals, it reduces to a weaker version of `/ta NVDA`.

**Root Cause**: Same SEC EDGAR stale data pipeline. The synthesis function queries the same SEC EDGAR data as `/analyze` and `/graham`, which returns 2020-Q2 data. The function may filter for "recent" quarters and reject 2020 data as too old, resulting in null.

---

### BUG-B4-2: Compare Uses Stale 2019-2020 Data [CRITICAL]

**Check**: CMP-02
**Command**: `/compare NVDA AAPL MSFT`
**Impact**: NVDA shows 2020-Q2, AAPL shows 2019-Q4, MSFT shows 2020-Q1. Revenue comparisons are meaningless: NVDA was at $3.08B/quarter (now $39B+), AAPL at $91.8B (now ~$120B+). The comparison tells you nothing about current competitive positioning.

**Root Cause**: Same SEC EDGAR pipeline. This is the same root cause as bugs in batches 1-3.

---

### BUG-B4-3: Stop-Loss Missing ATR and Swing Methods [HIGH]

**Check**: SL-02
**Command**: `/sl gold 3348 long`
**Impact**: Only `percent_based` stop is computed. The `atr_based` (ATR × multiplier) and `swing_based` (recent swing low) methods are missing. The Fidenza framework mentions both, and professional traders typically prefer ATR or swing-based stops over simple percentage stops. Missing these methods degrades the quality of risk management advice.

**Root Cause**: `protrader_sl.py` — The ATR and swing calculations likely require price history data that wasn't available for gold, or the asset mapping for commodities doesn't include the data source needed for these calculations.

**Fix**: Ensure gold price history is accessible for ATR and swing high/low calculations. Add fallback: if ATR unavailable, note "ATR data unavailable — using percent-based only."

---

### BUG-B4-4: USD Death Cross + "Cyclical Strength" Contradiction [MEDIUM]

**Checks**: CC4-04, GR4-03
**Command**: `/usdregime`
**Impact**: DXY shows `death_cross: true` (SMA50=98.07 < SMA200=98.39, bearish technical signal) alongside `classification: "cyclical_strength"`. A death cross is a bearish indicator, contradicting a "strength" classification.

**Root Cause**: `protrader_frameworks.py` — The regime classification logic likely prioritizes the current level vs. SMA position (DXY at 99.33 above both SMAs → "strength") without accounting for the SMA50/200 cross signal.

**Fix**: Add logic: `if death_cross and above_both_smas: classification = "recovering_but_cautious"` or include the death cross as a modifier to the classification.

---

### BUG-B4-5: Gold Price Inconsistency Between Commands [MEDIUM]

**Check**: CC4-02
**Command**: `/pmregime` vs `/sl gold`
**Impact**: `/pmregime` shows gold at $5,192.30, while `/sl gold` uses `current_price = $3,348.0` (the user-provided entry price). The stop-loss command should independently fetch the current gold price rather than defaulting to the entry price.

**Root Cause**: `protrader_sl.py` — When `entry_price` is provided, the function may set `current_price = entry_price` as a default. It should always fetch live price separately.

**Fix**: Always fetch current gold price independently from the entry price.

---

### BUG-B4-6: TA NVDA Missing 2 Murphy Frameworks [HIGH]

**Check**: TA-01
**Command**: `/ta NVDA`
**Impact**: Only 9 of 11 expected frameworks present (missing likely `8_fibonacci` or `10_patterns` or `9_stochastic`). The full Murphy TA promises 13 frameworks — at minimum the major 11 should be present. Missing frameworks reduce the composite signal quality.

**Root Cause**: `murphy_ta.py` — Some frameworks may fail silently for individual stocks (e.g., pattern recognition may require more data, or Fibonacci levels may fail to compute).

---

## Cross-Batch Analysis (All 4 Batches)

| Metric | Batch 1 | Batch 2 | Batch 3 | Batch 4 | Total |
|--------|---------|---------|---------|---------|-------|
| Commands | 3 | 10 | 11 | 9 | 33 |
| Total Checks | 58 | 52 | 48 | 40 | 198 |
| Passed | 49 (84.5%) | 38 (73.1%) | 36 (75.0%) | 33 (82.5%) | 156 (78.8%) |
| Failed | 9 | 14 | 12 | 7 | 42 |
| Critical | 6 | 7 | 3 | 2 | 18 |
| Unique Bugs | 7 | 10 | 7 | 6 | ~25 (some shared) |

### LLM Judge Scores Across All Batches

| Group | Score |
|-------|-------|
| /analyze NVDA (B1) | 5.2/10 |
| /commodity crude_oil (B1) | 4.0/10 |
| /drivers (B1) | 6.1/10 |
| Macro Suite: /macro, /bonds, /stress, /latecycle (B2) | 6.7/10 |
| Consumer Suite: /consumer, /housing, /labor (B2) | 6.0/10 |
| Valuation Suite: /graham, /valuation, /vixanalysis (B2) | 6.0/10 |
| Yardeni Suite: /bbb, /vigilantes, /drawdown (B3) | 5.0/10 |
| Equity Deep-Dive: /peers, /allocation, /balance (B3) | 5.95/10 |
| Pro-Trader Suite: /riskpremium, /crossasset, /intermarket, /synthesize (B3) | 7.05/10 |
| BTC/PM/USD (B4) | 5.0/10 |
| TA/Synthesis/SL (B4) | 5.0/10 |
| Screens/Compare (B4) | 5.0/10 |

**Overall LLM Judge Average: 5.5/10**
**Best command group**: Pro-Trader Suite (7.05/10)
**Worst command group**: Commodity (4.0/10)

---

## Systemic Bug Categories (All Batches)

| Category | Bug Count | Affected Commands | Root Cause |
|----------|-----------|-------------------|------------|
| **SEC EDGAR stale data** | 6 | `/analyze`, `/graham`, `/peers`, `/allocation`, `/balance`, `/compare`, `/synthesis`, `/netnet`, `/grahamscreen` | Pipeline stopped ~2020 |
| **FRED data pipeline** | 6 | `/macro`, `/consumer`, `/housing`, `/labor`, `/vigilantes`, `/fsmi` | Missing months, expired series |
| **YoY index misalignment** | 3 | `/macro`, `/labor`, `/valuation` | `obs[12]` not date-aligned |
| **Label-value contradictions** | 4 | `/macro`, `/usdregime`, `/commodity`, `/allocation` | Classification logic gaps |
| **Formula errors** | 3 | `/graham` MoS, `/grahamscreen` MoS, `/bbb` ratio | Wrong denominator/units |
| **Data availability failures** | 4 | `/consumer`, `/housing`, `/labor`, `/sl gold` | Missing API data |
| **Command crashes** | 1 | `/fsmi` | Timestamp → float() |

---

## Priority Recommendations (Across All Batches)

### P0 — Must Fix (System-wide impact)
1. **SEC EDGAR pipeline**: Update the entire SEC filing ingestion system. This single fix would improve **9+ commands** across all 4 batches. This is the #1 systemic issue.
2. **YoY date-based lookup** (`fred_data.py:755`): Replace `obs[12]` with date-anchored lookup. Fixes Core CPI (-8.22%), Core PCE (0.28%), Yardeni valuation (null CPI), and inflation regime classification.
3. **FSMI Timestamp crash** (`yardeni_frameworks.py`): Fix float() conversion to make `/fsmi` functional.

### P1 — Should Fix (Individual command quality)
4. **Bond Vigilantes data pipeline**: Use same yield source as `/bonds` for 10Y yield
5. **BBB ratio units**: Divide claims by 1000 before ratio computation
6. **Graham MoS denominator**: Change to `price` in `graham_analysis.py` (lines 321, 618)
7. **Allocation diluted_shares**: Source from income statement, not cash flow
8. **Balance latest_summary ordering**: Use `[-1]` not `[0]`
9. **Stop-loss ATR/swing**: Add gold price history for ATR calculation

### P2 — Nice to Fix (Polish)
10. **USD regime**: Account for death cross in classification logic
11. **Allocation buyback label**: Reference latest quarter, not oldest
12. **TA missing frameworks**: Add error handling for missing Murphy frameworks
13. **Claims "213000K"** unit error in stress interpretation
14. **"late-early warning"** ambiguous label

---

## Test Infrastructure Summary

| Asset | Location |
|-------|----------|
| Batch 3 evaluator | `taste/command_batch3_evaluator.py` |
| Batch 3 data | `command_output_batch3_v1.json` (35,739 bytes) |
| Batch 3 records | `taste/command_eval_records/batch3_eval_20260312_161038.{json,md}` |
| Batch 4 evaluator | `taste/command_batch4_evaluator.py` |
| Batch 4 data | `command_output_batch4_v1.json` (27,272 bytes) |
| Batch 4 records | `taste/command_eval_records/batch4_eval_20260312_161919.{json,md}` |

---

## Full Test Coverage Achieved

| # | Command | Batch | Status |
|---|---------|-------|--------|
| 1 | `/analyze NVDA` | 1 | ✅ Evaluated |
| 2 | `/commodity crude_oil` | 1 | ✅ Evaluated |
| 3 | `/drivers` | 1 | ✅ Evaluated |
| 4 | `/macro` | 2 | ✅ Evaluated |
| 5 | `/bonds` | 2 | ✅ Evaluated |
| 6 | `/stress` | 2 | ✅ Evaluated |
| 7 | `/latecycle` | 2 | ✅ Evaluated |
| 8 | `/consumer` | 2 | ✅ Evaluated |
| 9 | `/housing` | 2 | ✅ Evaluated |
| 10 | `/labor` | 2 | ✅ Evaluated |
| 11 | `/graham NVDA` | 2 | ✅ Evaluated |
| 12 | `/valuation` | 2 | ✅ Evaluated |
| 13 | `/vixanalysis` | 2 | ✅ Evaluated |
| 14 | `/bbb` | 3 | ✅ Evaluated |
| 15 | `/fsmi` | 3 | ✅ Evaluated (crashes) |
| 16 | `/vigilantes` | 3 | ✅ Evaluated (no data) |
| 17 | `/drawdown` | 3 | ✅ Evaluated |
| 18 | `/peers NVDA` | 3 | ✅ Evaluated |
| 19 | `/allocation NVDA` | 3 | ✅ Evaluated |
| 20 | `/balance NVDA` | 3 | ✅ Evaluated |
| 21 | `/riskpremium` | 3 | ✅ Evaluated |
| 22 | `/crossasset` | 3 | ✅ Evaluated |
| 23 | `/intermarket` | 3 | ✅ Evaluated |
| 24 | `/synthesize` | 3 | ✅ Evaluated |
| 25 | `/btc` | 4 | ✅ Evaluated |
| 26 | `/pmregime` | 4 | ✅ Evaluated |
| 27 | `/usdregime` | 4 | ✅ Evaluated |
| 28 | `/ta NVDA` | 4 | ✅ Evaluated |
| 29 | `/synthesis NVDA` | 4 | ✅ Evaluated |
| 30 | `/sl gold 3348 long` | 4 | ✅ Evaluated |
| 31 | `/grahamscreen` | 4 | ✅ Evaluated |
| 32 | `/netnet` | 4 | ✅ Evaluated |
| 33 | `/compare NVDA AAPL MSFT` | 4 | ✅ Evaluated |
| — | `/full_report` | Macro Taste | ✅ Evaluated (v1→v3) |

**Not evaluated** (external services / agent-orchestrated):
- `/search`, `/twitter`, `/refresh` (Twitter/web search — external APIs)
- `/termpremium` (no standalone function — agent-orchestrated)
- `/oil` (alias for `/commodity crude_oil` — already tested)
- `/btctrend`, `/btcposition` (subsets of `/btc`)
- `/tatrend`, `/tamomentum` (subsets of `/ta`)
- `/quickta`, `/rsi`, `/sr`, `/breakout` (individual TA components)
- `/full_report` in slash form (already tested as macro taste v1-v3)

**Total coverage**: 34 command evaluations across 4 batches + macro taste test
