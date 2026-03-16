# Command-Level Taste Evaluation Report — Batch 2

**Date**: 2026-03-12
**Commands Evaluated**: `/macro`, `/bonds`, `/stress`, `/latecycle`, `/consumer`, `/housing`, `/labor`, `/graham NVDA`, `/valuation`, `/vixanalysis`
**Evaluation Version**: batch2-v1

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total Checks | 52 |
| Passed | 38 (73.1%) |
| Failed | 14 |
| Critical Failures | 7 |
| LLM Judge (Macro Suite) | 6.7/10 |
| LLM Judge (Consumer/Housing/Labor) | 6.0/10 |
| LLM Judge (Valuation Suite) | 6.0/10 |

### Severity Breakdown

| Severity | Count | Failed |
|----------|-------|--------|
| Critical | 7 | 7 |
| High | 8 | 5 |
| Medium | ~20 | 2 |
| Low | ~5 | 0 |

---

## Results by Approach

| Approach | Total | Passed | Failed | Rate |
|----------|-------|--------|--------|------|
| Data Accuracy | 28 | 18 | 10 | 64% |
| Coherence | 13 | 11 | 2 | 85% |
| Grounding | 8 | 6 | 2 | 75% |
| LLM Judge | 3 | 3 | 0 | 100% |

## Results by Command

| Command | Total | Passed | Failed | Rate |
|---------|-------|--------|--------|------|
| `/bonds` | 7 | 7 | 0 | 100% |
| `/vixanalysis` | 3 | 3 | 0 | 100% |
| `/stress` | 5 | 4 | 1 | 80% |
| `/housing` | 3 | 2 | 1 | 67% |
| `/latecycle` | 3 | 2 | 1 | 67% |
| `/graham NVDA` | 5 | 3 | 2 | 60% |
| `/labor` | 4 | 2 | 2 | 50% |
| `/macro` | 5 | 2 | 3 | 40% |
| `/consumer` | 3 | 1 | 2 | 33% |
| `/valuation` | 2 | 0 | 2 | 0% |
| Cross-command | 9 | 9 | 0 | 100% |

---

## Bugs Found

### BUG-B2-1: Core CPI YoY = -8.22% (Index Misalignment) [CRITICAL]

**Check**: LB-03, CC-11
**Commands**: `/macro`, `/labor`
**Impact**: Core CPI YoY is reported as **-8.22%** — an 8% core deflation rate that has never occurred in modern US economic history. This impossible value cascades into inflation regime classification, making the entire macro analysis unreliable. The `/labor` command also consumes this value for real wage calculations.

**Root Cause**: `fred_data.py` line 755:
```python
year_ago = obs[12]["value"]  # Assumes obs[12] is exactly 12 months back
```
The code assumes `obs[12]` (13th element in a descending-sorted array) is exactly 12 months prior to `obs[0]`. However, **October 2025 is missing** from `core_cpi.csv`, which shifts `obs[12]` to 2024-12-01 (13 months back instead of 12). The YoY compares January 2026 against December 2024 instead of January 2025.

**Fix**: Use date-based lookup instead of index-based:
```python
latest_date = obs[0]["date"]
target_date = latest_date - timedelta(days=365)
year_ago = min(obs, key=lambda x: abs((x["date"] - target_date).days))
```

---

### BUG-B2-2: Core PCE YoY = 0.28% (Same Index Bug) [CRITICAL]

**Check**: CC-12
**Command**: `/macro`
**Impact**: Core PCE YoY is reported as **0.28%** — implausibly low given current economic conditions. Core PCE is the Fed's preferred inflation measure; a 0.28% reading would imply near-deflation, contradicting the Fed's own statements and the 2.56% 5Y breakeven inflation. This value is used as the primary inflation regime input (`regimes.inflation.value = 0.28`).

**Root Cause**: Same index-based YoY bug as BUG-B2-1. The `core_pce.csv` likely has a missing month, causing `obs[12]` to compare non-aligned months. The `core_pce` latest_value = 2.9969 (a price index level, not a percent), and the YoY = 0.28% is computed from misaligned comparison points.

**Fix**: Same date-based lookup fix as BUG-B2-1 — applies to all YoY calculations in `get_inflation_data()`.

---

### BUG-B2-3: Inflation "cooling" but Trend "rising" (Classification Contradiction) [CRITICAL]

**Check**: GR-01
**Command**: `/macro`
**Impact**: The inflation regime shows `classification: "cooling"` alongside `trend: "rising"`. This is logically contradictory — if inflation is rising, it cannot be cooling. Users relying on the regime classification for portfolio positioning would receive conflicting signals.

**Root Cause**: `macro_market_analysis.py` lines 266-280:
```python
# Line 266-270: Classification based SOLELY on current value
inflation_regime = _classify_regime(..., {"cooling": ("<", 1.5), ...})

# Lines 279-280: Override only fires if BOTH rising AND > 2.5
if inflation_trend == "rising" and inflation_val > 2.5:
    inflation_regime["classification"] = "hot"
```
The override logic (line 279) only upgrades to "hot" if value > 2.5. When `inflation_val = 0.28` (from BUG-B2-2) and `trend = "rising"`, the classification stays "cooling" because the override condition isn't met. The code never checks for the contradiction case: rising trend + low-value classification.

**Fix**: Add contradiction handling:
```python
if inflation_trend == "rising":
    if inflation_val > 2.5:
        classification = "hot"
    elif inflation_val > 1.5:
        classification = "elevated"
    else:
        classification = "rising_from_low_base"  # Not "cooling"
```

**Note**: This bug is partially caused by BUG-B2-2 — if Core PCE YoY were correct (~2.8%), `inflation_val` would be above 1.5 and the classification would be "elevated" or "stable", not "cooling". Fixing BUG-B2-2 would prevent this specific manifestation but not the underlying logic gap.

---

### BUG-B2-4: CPI YoY Null → Yardeni Valuation Completely Broken [CRITICAL]

**Checks**: VA-01, VA-02
**Command**: `/valuation`
**Impact**: The Yardeni valuation tool returns `assessment: "insufficient_data"` because `cpi_yoy_pct = null`. This means the **Rule of 20** (fair P/E = 20 - inflation) and **Rule of 24** frameworks cannot compute, rendering the entire valuation command useless. The valuation command is the only tool that provides market-wide fair value estimates.

**Root Cause**: The `analyze_yardeni_valuation()` function requires CPI YoY as an input. CPI YoY is fetched from `get_inflation_data()`, but returns null when the data pipeline fails. The CPI YoY bug (BUG-B2-1 variant) may cause the function to reject the value as invalid, or the CPI data may simply be missing from the expected location.

**Fix**:
1. Fix the CPI YoY computation (BUG-B2-1)
2. Add fallback: use Core PCE or headline PCE if CPI unavailable
3. Add explicit warning message when insufficient data, explaining which input is missing

---

### BUG-B2-5: Graham Number Stale Data (2020-Q2) [CRITICAL]

**Check**: GA-04
**Command**: `/graham NVDA`
**Impact**: Same bug as BUG-CMD-1 from Batch 1. The SEC EDGAR data pipeline returns NVIDIA financials from **2020-Q2** — before the AI boom that took revenue from $3.08B/quarter to $22B+/quarter. Graham Number computed from 2020 EPS/BVPS is meaningless for current valuation decisions.

**Root Cause**: `NVDA_quarterly.csv` in the SEC EDGAR pipeline has not been updated since 2020. The data ingestion job stopped fetching new 10-Q/10-K filings.

**Fix**: Update SEC EDGAR data pipeline (same fix as BUG-CMD-1).

---

### BUG-B2-6: Graham Margin of Safety Formula Error [HIGH]

**Check**: GA-02
**Command**: `/graham NVDA`
**Impact**: Margin of Safety (MoS) is reported as **-549.77%** instead of the correct **-84.61%**. This makes the MoS look catastrophically worse than reality. While NVDA is indeed significantly overvalued relative to Graham Number (28.63 vs. price 186.24), -549% overstates the downside by ~6.5x.

**Root Cause**: `graham_analysis.py` line 321:
```python
margin = round((graham_num - price) / graham_num * 100, 2)  # BUG: divides by graham_num
```
Should divide by `price`:
```python
margin = round((graham_num - price) / price * 100, 2)  # CORRECT: divides by price
```

Computation:
- **Buggy**: (28.63 - 186.24) / 28.63 × 100 = **-549.77%**
- **Correct**: (28.63 - 186.24) / 186.24 × 100 = **-84.61%**

Same bug appears on line 618 in `graham_screen()`.

**Fix**: Change denominator from `graham_num` to `price` on lines 321 and 618.

---

### BUG-B2-7: Initial Claims "213000K" Unit Error [HIGH]

**Check**: SA-04
**Command**: `/stress`
**Impact**: The interpretation string reads "Initial claims at 213000K" — which would mean 213 million claims (213,000 × 1,000). The actual value is 213,000 claims, which should display as "213K".

**Root Cause**: `market_regime_enhanced.py` line 237:
```python
"interpretation": f"Initial claims at {claims_val:.0f}K",
```
`claims_val` is already in units (213000), and the code appends "K" without dividing by 1000. Either the value is already in thousands from FRED (meaning `claims_val = 213` and no K needed), or the raw value needs `/1000` before the K suffix.

**Fix**: `f"Initial claims at {claims_val/1000:.0f}K"` or remove the "K" suffix if value is already scaled.

---

### BUG-B2-8: Consumer Composite Score Miscalculation [MEDIUM]

**Check**: CON-01
**Command**: `/consumer`
**Impact**: Composite score is 6.87 but manual weighted average of available components gives 3.13. The discrepancy (~2.2x) distorts the overall consumer health assessment.

**Root Cause**: `consumer_housing_analysis.py` lines 207-209:
```python
total_weight = sum(w for s, w in weighted_scores if s > 0)
composite = sum(s * w for s, w in weighted_scores if s > 0) / total_weight
```
Two issues:
1. The filter `if s > 0` excludes components with score=0 (including unavailable components) from **both** numerator and denominator, inflating the average
2. There appears to be a `10.0 - composite` inversion (line ~219), converting stress-style scoring to health-style scoring, which further changes the expected result

**Note**: This may be an intentional design choice (renormalize to available data, then invert), but the result (6.87) diverges significantly from the naive expectation (3.13) and should be documented in the output.

**Fix**: Either change to include 0-score components in the denominator, or add a note explaining the scoring methodology.

---

### BUG-B2-9: Multiple Data Availability Failures [HIGH]

**Checks**: CON-02, HA-02, LB-02
**Commands**: `/consumer`, `/housing`, `/labor`
**Impact**: Three key economic metrics are unavailable:
- **Credit Growth Velocity** (consumer): Missing → incomplete consumer health picture
- **Price Dynamics / Case-Shiller** (housing): `data_unavailable` → no home price data
- **Productivity & ULC** (labor): Both null → can't assess wage-price spiral risk

These gaps mean 3 of 10 commands have degraded analytical coverage.

**Root Cause**: FRED API data pipeline issues — either expired API keys, incorrect series IDs, rate limits, or the series have been discontinued/renamed. Specific series to check:
- Consumer credit: G.19 / TOTALSL
- Case-Shiller: CSUSHPINSA
- Productivity: PRS85006092 / OPHNFB
- ULC: ULCNFB

**Fix**: Verify FRED API key validity and series IDs for all affected metrics. Add fallback data sources or explicit "data unavailable since [date]" warnings.

---

### BUG-B2-10: Late-Cycle "late-early warning" Label [MEDIUM]

**Check**: GR-03
**Command**: `/latecycle`
**Impact**: With 3/13 signals firing, the confidence label is "late-early warning" — which is ambiguous. "Late-early" could mean "late stage of early cycle" or "early warning of late cycle." Users need unambiguous signal interpretations.

**Root Cause**: The label generation logic concatenates cycle stage and confidence level in a confusing way.

**Fix**: Use clearer labels: "early warning (3/13 signals)" or "low confidence late-cycle" instead of "late-early warning".

---

## Potential False Positive

### CON-01: Consumer Composite Score

**Resolution**: Partially a false positive. The consumer health tool uses stress-inverted scoring with dynamic weight renormalization. The formula `10.0 - weighted_avg(available)` is an intentional design pattern to convert "stress scores" (higher = worse) into "health scores" (higher = better). However, the output doesn't document this methodology, making the composite_score appear mathematically wrong to external consumers of the API. Recommend adding `scoring_method` field to the output.

---

## LLM Judge Results

### Macro Suite (`/macro`, `/bonds`, `/stress`, `/latecycle`) — 6.7/10

| Dimension | Weight | Score |
|-----------|--------|-------|
| Regime Classification Quality | 20% | 6 |
| Data Completeness | 15% | 5 |
| Signal Coherence | 20% | 8 |
| Quantitative Accuracy | 15% | 8 |
| Analytical Depth | 15% | 7 |
| Actionability | 15% | 6 |

**Key critique**: Strong cross-tool signal alignment and correct arithmetic on spread calculations. Weakened by data gaps in stress components and the Core PCE value (0.28%) feeding into regime classification. The ISM decomposition and labor breadth analysis add genuine analytical depth. Bonds command scored perfectly — yield curve analysis is well-executed.

### Consumer/Housing/Labor Suite — 6.0/10

| Dimension | Weight | Score |
|-----------|--------|-------|
| Component Coverage | 20% | 7 |
| Data Availability | 15% | 5 |
| Composite Score Logic | 20% | 3 |
| Leading Indicator Value | 20% | 8 |
| Cross-Domain Integration | 15% | 6 |
| Professional Quality | 10% | 8 |

**Key critique**: Critical calculation error in consumer composite scoring identified. Seven null/unavailable fields out of ~19 total (37% null rate) severely undermines analytical coverage. Strong forward-looking signal generation (CONSUMER_STABLE, SAVINGS_RATE_LOW, HOUSING_DISTRESSED) partially compensates. Professional presentation quality is high with consistent timestamps, proper economic terminology.

### Valuation Suite (`/graham`, `/valuation`, `/vixanalysis`) — 6.0/10

| Dimension | Weight | Score |
|-----------|--------|-------|
| Valuation Framework Quality | 25% | 7 |
| Data Freshness | 20% | 3 |
| Risk Assessment | 20% | 8 |
| Actionability | 20% | 5 |
| Internal Consistency | 10% | 8 |
| Completeness | 5% | 5 |

**Key critique**: VIX analysis is well-executed (88.4th percentile with meaningful elevated-fear tier classification). Graham Number calculation is mathematically correct (28.63) but based on 2020-Q2 data, rendering it useless for current decisions. Yardeni valuation completely broken (insufficient_data). Margin of Safety formula uses wrong denominator.

---

## Cross-Approach Convergence

Several bugs are independently detected by multiple approaches:

| Bug | Accuracy | Coherence | Grounding | LLM Judge |
|-----|----------|-----------|-----------|-----------|
| BUG-B2-1 (Core CPI -8.22%) | LB-03 | CC-11 | — | "6/10 classification" |
| BUG-B2-2 (Core PCE 0.28%) | — | CC-12 | — | "5/10 completeness" |
| BUG-B2-3 (Inflation contradiction) | — | — | GR-01 | "6/10 classification" |
| BUG-B2-4 (Valuation broken) | VA-01, VA-02 | — | — | "5/10 completeness" |
| BUG-B2-5 (Graham stale) | GA-04 | — | — | "3/10 freshness" |
| BUG-B2-6 (MoS formula) | GA-02 | — | — | "8/10 consistency" |
| BUG-B2-9 (Data gaps) | CON-02, HA-02, LB-02 | — | — | "5/10 availability" |

---

## Cross-Batch Analysis (Batch 1 + Batch 2)

| Metric | Batch 1 | Batch 2 | Combined |
|--------|---------|---------|----------|
| Commands | 3 | 10 | 13 |
| Total Checks | 58 | 52 | 110 |
| Passed | 49 (84.5%) | 38 (73.1%) | 87 (79.1%) |
| Failed | 9 | 14 | 23 |
| Critical | 6 | 7 | 13 |
| Unique Bugs | 7 | 10 | 15 (2 shared) |

### Shared Bugs Across Batches

1. **SEC EDGAR Stale Data** — BUG-CMD-1 (Batch 1) = BUG-B2-5 (Batch 2). Same root cause, `/analyze NVDA` and `/graham NVDA` both affected.
2. **YoY Index Misalignment** — BUG-B2-1/B2-2 are a new class of bug not seen in Batch 1, likely because Batch 1 didn't exercise the inflation data path as directly.

### Systemic Patterns

| Pattern | Occurrences | Affected Commands |
|---------|-------------|-------------------|
| FRED data pipeline failures | 5 bugs | `/macro`, `/consumer`, `/housing`, `/labor`, `/commodity` |
| SEC EDGAR stale data | 2 bugs | `/analyze`, `/graham` |
| Label-value contradictions | 3 bugs | `/macro`, `/commodity` (Batch 1), `/drivers` (Batch 1) |
| Formula errors | 2 bugs | `/graham` (MoS), `/analyze` (OCF/NI from Batch 1) |

---

## Priority Recommendations

### P0 — Must Fix (Critical, blocks usability)
1. **BUG-B2-1/B2-2**: Fix YoY computation to use date-based lookup instead of index-based (`fred_data.py` line 755). This one fix resolves 3 bugs (Core CPI, Core PCE, and partially BUG-B2-3).
2. **BUG-B2-4**: Fix CPI YoY availability for Yardeni valuation (blocked by BUG-B2-1 fix)
3. **BUG-B2-5**: Update SEC EDGAR data pipeline (same as Batch 1 BUG-CMD-1)

### P1 — Should Fix (High severity, causes incorrect analysis)
4. **BUG-B2-6**: Change MoS denominator from `graham_num` to `price` (lines 321, 618 in `graham_analysis.py`)
5. **BUG-B2-7**: Fix claims unit display in stress interpretation (`market_regime_enhanced.py` line 237)
6. **BUG-B2-9**: Investigate and restore FRED API connectivity for credit, housing, and productivity data
7. **BUG-B2-3**: Add contradiction handling for inflation classification vs. trend direction

### P2 — Nice to Fix (Improves quality)
8. **BUG-B2-8**: Document consumer composite scoring methodology or fix weight renormalization
9. **BUG-B2-10**: Clarify "late-early warning" label to something unambiguous
10. Add `scoring_method` documentation field to composite scores across all commands

---

## Test Infrastructure

- **Evaluator script**: `taste/command_batch2_evaluator.py`
- **Data file**: `command_output_batch2_v1.json`
- **Records**: `taste/command_eval_records/batch2_eval_20260312_152433.{json,md}`
- **LLM Judge**: MiniMax-M2.5 via OpenAI-compatible API
- **Approaches applied**: Data Accuracy (28 checks), Coherence (13 checks), Grounding (8 checks), LLM Judge (3 scores)

---

## All Checks Detail

| ID | Category | Command | Check | Status | Severity |
|----|----------|---------|-------|--------|----------|
| MA-01 | accuracy | bonds | 2s10s spread = 10Y - 2Y | PASS | high |
| MA-02 | accuracy | bonds | Term premium = nominal - real - breakeven | PASS | high |
| MA-03 | accuracy | bonds | HY OAS bps = pct × 100 | PASS | medium |
| MA-04 | accuracy | bonds | IG OAS bps = pct × 100 | PASS | medium |
| MA-05 | accuracy | bonds | HY-IG differential = HY bps - IG bps | PASS | medium |
| SA-01 | accuracy | stress | Composite = weighted sum | PASS | high |
| SA-02 | accuracy | stress | All scores in [0, 10] | PASS | medium |
| SA-03 | accuracy | stress | Weights sum to ~1.0 | PASS | medium |
| SA-04 | accuracy | stress | Claims units correct | **FAIL** | high |
| LA-01 | accuracy | latecycle | Count matches firing signals | PASS | high |
| LA-02 | accuracy | latecycle | Total matches list length | PASS | medium |
| CON-01 | accuracy | consumer | Composite = weighted avg | **FAIL** | medium |
| CON-02 | accuracy | consumer | Credit growth available | **FAIL** | high |
| HA-01 | accuracy | housing | Permits/starts ratio | PASS | medium |
| HA-02 | accuracy | housing | Price dynamics available | **FAIL** | high |
| LB-01 | accuracy | labor | Hires/layoffs ratio | PASS | medium |
| LB-02 | accuracy | labor | Productivity data available | **FAIL** | high |
| LB-03 | accuracy | labor | Core CPI YoY plausible | **FAIL** | critical |
| GA-01 | accuracy | graham | Graham Number formula | PASS | high |
| GA-02 | accuracy | graham | Margin of Safety formula | **FAIL** | high |
| GA-03 | accuracy | graham | P/E × P/B product | PASS | medium |
| GA-04 | accuracy | graham | Data freshness | **FAIL** | critical |
| GA-05 | accuracy | graham | Price/NCAV formula | PASS | medium |
| VA-01 | accuracy | valuation | Produces results | **FAIL** | critical |
| VA-02 | accuracy | valuation | CPI YoY available | **FAIL** | critical |
| VX-01 | accuracy | vixanalysis | VIX tier matches value | PASS | high |
| VX-02 | accuracy | vixanalysis | MOVE/VIX ratio | PASS | medium |
| VX-03 | accuracy | vixanalysis | VIX percentile in [0,100] | PASS | low |
| CC-01 | coherence | macro | Growth ↔ ISM value | PASS | high |
| CC-02 | coherence | cross-cmd | Macro credit ↔ Stress HY OAS | PASS | high |
| CC-03 | coherence | cross-cmd | Bond curve ↔ Macro curve | PASS | high |
| CC-04 | coherence | cross-cmd | Recession ↔ stress ≥ 4 | PASS | medium |
| CC-05 | coherence | cross-cmd | Housing signals consistent | PASS | medium |
| CC-06 | coherence | cross-cmd | Consumer ↔ stress credit | PASS | low |
| CC-07 | coherence | cross-cmd | Late-cycle ISM ↔ macro ISM | PASS | high |
| CC-08 | coherence | cross-cmd | VIX consistent across tools | PASS | high |
| CC-09 | coherence | cross-cmd | HY OAS consistent across tools | PASS | high |
| CC-10 | coherence | cross-cmd | Labor ↔ employment | PASS | low |
| CC-11 | coherence | macro | Core CPI YoY plausible | **FAIL** | critical |
| CC-12 | coherence | macro | Core PCE plausible | **FAIL** | critical |
| CC-13 | coherence | macro | CREDIT_TIGHT ↔ classification | PASS | medium |
| GR-01 | grounding | macro | Inflation cooling ↔ trend | **FAIL** | critical |
| GR-02 | grounding | stress | Stress label ↔ score | PASS | high |
| GR-03 | grounding | latecycle | Confidence label clarity | **FAIL** | medium |
| GR-04 | grounding | consumer | Health label ↔ score | PASS | medium |
| GR-05 | grounding | housing | Distressed ↔ signals | PASS | medium |
| GR-06 | grounding | bonds | Duration risk ↔ real yield | PASS | medium |
| GR-07 | grounding | bonds | Fed stance ↔ funds rate | PASS | medium |
| GR-08 | grounding | labor | Power label ↔ quits rate | PASS | low |
| LLM-MACRO | llm_judge | macro suite | Macro/Bonds/Stress/LateCycle | PASS (6.7) | high |
| LLM-CONS | llm_judge | consumer suite | Consumer/Housing/Labor | PASS (6.0) | high |
| LLM-VAL | llm_judge | valuation suite | Graham/Valuation/VIX | PASS (6.0) | high |

---

## Sample Fix-and-Retest Prompt

After fixing the bugs above, re-run:
```bash
# Collect fresh data from all 10 commands
FINANCIAL_AGENT_ROOT=/path/to/Financial_Agent python3 taste/command_batch2_evaluator.py

# Or test against saved output
python3 taste/command_batch2_evaluator.py --input command_output_batch2_v2.json
```

Expected improvements in v2:
- LB-03/CC-11 pass if YoY uses date-based lookup (BUG-B2-1 fix)
- CC-12 passes if Core PCE YoY corrected (BUG-B2-2 fix)
- GR-01 passes if inflation contradiction resolved (BUG-B2-3, partially via B2-1/B2-2 fix)
- VA-01/VA-02 pass if CPI YoY restored (BUG-B2-4, via B2-1 fix)
- GA-02 passes if MoS denominator fixed (BUG-B2-6 fix)
- GA-04 passes if SEC EDGAR data updated (BUG-B2-5 fix)
- SA-04 passes if claims units fixed (BUG-B2-7 fix)
- LLM scores should improve across all suites, especially Valuation from 6.0 → 7.5+
