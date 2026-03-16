# Comprehensive Testing Framework for Financial Analysis AI Agents
## Research-Backed Best Practices (2024-2026)

*Research compiled March 2026*

---

## Table of Contents
1. [Testing Financial Calculation Accuracy](#1-testing-financial-calculation-accuracy)
2. [Testing Market Regime Classification](#2-testing-market-regime-classification)
3. [Validating Financial Ratios](#3-validating-financial-ratios)
4. [Edge Cases Specific to Financial Data](#4-edge-cases-specific-to-financial-data)
5. [Backtesting Signal Accuracy](#5-backtesting-signal-accuracy)
6. [Testing for Look-Ahead Bias](#6-testing-for-look-ahead-bias)
7. [Stress Testing with Extreme Market Scenarios](#7-stress-testing-with-extreme-market-scenarios)
8. [Testing Data Staleness and Freshness](#8-testing-data-staleness-and-freshness)
9. [Numerical Precision and Rounding](#9-numerical-precision-and-rounding)
10. [Testing Cross-Asset Correlation Calculations](#10-testing-cross-asset-correlation-calculations)
11. [Best Practices for Testing LLM-Based Financial Agents](#11-best-practices-for-testing-llm-based-financial-agents)
12. [Regulatory Considerations](#12-regulatory-considerations)
13. [Testing for Survivorship Bias](#13-testing-for-survivorship-bias)
14. [Domain-Specific Test Cases: VIX, Commodities, BTC, Valuation Models](#14-domain-specific-test-cases)
15. [Concrete Test Case Catalog](#15-concrete-test-case-catalog)

---

## 1. Testing Financial Calculation Accuracy

### RSI (Relative Strength Index)

**Formula to verify:**
RSI = 100 - (100 / (1 + RS)), where RS = Average Gain / Average Loss over N periods (default N=14).

**Concrete test cases:**

| Test ID | Description | Input | Expected Behavior |
|---------|-------------|-------|-------------------|
| RSI-001 | Standard 14-period RSI on known data | 15 daily closes with known gains/losses | RSI matches hand-calculated value within 0.01 |
| RSI-002 | RSI at exact boundary (70.00) | Craft input where RSI = exactly 70.0 | Agent correctly classifies as overbought threshold |
| RSI-003 | RSI with all gains (no losses) | 14 consecutive up days | RSI = 100.0 (division by zero handling in RS) |
| RSI-004 | RSI with all losses (no gains) | 14 consecutive down days | RSI = 0.0 |
| RSI-005 | RSI with flat prices | 14 identical closes | RSI = 50.0 or handled gracefully (0/0 case) |
| RSI-006 | Wilder smoothing vs SMA | Same data, both methods | Verify agent uses Wilder exponential smoothing, not simple average |
| RSI-007 | Insufficient data points | Only 5 data points for 14-period RSI | Agent returns error or N/A, not a garbage value |

**Verification strategy:** Cross-reference against TradingView, TA-Lib, or pandas_ta using the same input data. Discrepancies > 0.1 indicate a formula error; discrepancies of 0.01-0.1 may indicate smoothing method differences.

### MACD (Moving Average Convergence Divergence)

**Formula to verify:**
- MACD Line = 12-period EMA - 26-period EMA
- Signal Line = 9-period EMA of MACD Line
- Histogram = MACD Line - Signal Line

**Concrete test cases:**

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| MACD-001 | Standard 12/26/9 on 50+ data points | MACD line, signal, histogram match TA-Lib within 0.001 |
| MACD-002 | MACD crossover detection | Bullish crossover (MACD crosses above signal) correctly identified |
| MACD-003 | Zero-line crossover | MACD crossing from negative to positive correctly flagged |
| MACD-004 | Divergence detection (price makes new high, MACD does not) | Bearish divergence correctly identified |
| MACD-005 | Insufficient data (< 26 points) | Graceful error, not partial calculation |
| MACD-006 | EMA seed value method | Verify whether first EMA is seeded with SMA or first price |

### Moving Averages

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| MA-001 | SMA(20) on exactly 20 data points | Correct arithmetic mean |
| MA-002 | EMA(20) multiplier verification | Multiplier = 2/(20+1) = 0.0952... |
| MA-003 | Death cross detection (50 SMA crosses below 200 SMA) | Correctly detected with exact date |
| MA-004 | Golden cross detection | Correctly detected with exact date |
| MA-005 | Moving average with gaps (weekends, holidays) | Gaps handled correctly, not interpolated as zero |

### Support/Resistance Detection

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| SR-001 | Clear horizontal support (3+ touches) | Level identified within 0.5% of actual |
| SR-002 | Breakout confirmation | Price closing above resistance flagged as breakout |
| SR-003 | False breakout (wick above, close below) | Not classified as confirmed breakout |
| SR-004 | Support becoming resistance (polarity change) | Role reversal correctly identified |

---

## 2. Testing Market Regime Classification

### Approaches from Recent Research

State Street Global Advisors (2024) uses Quantile-Conditional Density (QCD) to evaluate regime-based performance reliability. The BIS (2025) constructs Market Condition Indicators (MCIs) using market microstructure dislocations. Academic research (2025) combines Hidden Markov Models with ensemble ML methods (Random Forest, Gradient Boosting) using walk-forward validation.

### Concrete Test Cases

| Test ID | Description | Input Scenario | Expected Classification |
|---------|-------------|----------------|------------------------|
| REG-001 | Clear bull market | SPX up 20%+, VIX < 15, positive breadth | "Bull" or "Risk-On" regime |
| REG-002 | Clear bear market | SPX down 20%+, VIX > 30, negative breadth | "Bear" or "Risk-Off" regime |
| REG-003 | High-volatility sideways | SPX flat over 6 months, VIX 25-35 | "Choppy/High-Vol" regime, NOT "bull" |
| REG-004 | Late-cycle detection | Inverted yield curve, low unemployment, rising wages, tightening credit | "Late Cycle" classification |
| REG-005 | Flash crash (intraday spike) | VIX spike from 15 to 65 in one day | "Stress/Crisis" regime |
| REG-006 | Post-crisis recovery | VIX declining from 50 to 20 over 3 months, SPX rising | "Recovery" or transitional regime |
| REG-007 | Regime transition boundary | Data that is ambiguous between two regimes | Agent expresses uncertainty, not false confidence |
| REG-008 | Stress score boundary testing | Inputs at exact threshold values | Correct classification at boundaries |

### Validation Methodology

1. **Walk-forward validation:** Train on 2010-2015, test on 2015-2020, retrain on 2010-2020, test on 2020-2025 (as per the ensemble-HMM voting framework research).
2. **Known historical regimes as ground truth:** Use NBER recession dates, known crisis periods (GFC 2008, COVID March 2020, SVB March 2023) as labeled test data.
3. **Covariate shift analysis:** Verify that statistical properties of important predictors did not change qualitatively over the holdout period (per the 2025 arXiv research on market troughs).
4. **Explainability checks:** Use SHAP values to verify which features drive regime classification -- the top features should be economically intuitive (VIX, yield curve slope, credit spreads).

---

## 3. Validating Financial Ratios

### P/E Ratio Edge Cases

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| PE-001 | Positive EPS, normal P/E | P/E = Price / EPS, matches reference source |
| PE-002 | Negative EPS (net loss) | P/E reported as N/A or "N/M" (not meaningful), NOT a negative number used for ranking |
| PE-003 | EPS = 0 exactly | Division by zero handled; P/E = N/A |
| PE-004 | Trailing P/E with mixed quarters (+1, +2, +3, -7) | Total EPS = -1, P/E = N/A |
| PE-005 | Forward P/E with no analyst estimates | Agent states data unavailable, does not fabricate |
| PE-006 | Post-stock-split P/E | P/E remains unchanged (both price and EPS adjust proportionally) |
| PE-007 | Index-level P/E with negative-earnings constituents | Negative earnings reduce denominator, raising aggregate P/E |
| PE-008 | Cyclically-adjusted P/E (CAPE/Shiller) | Uses 10-year inflation-adjusted earnings, not trailing 12-month |

### ROE Edge Cases

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| ROE-001 | Standard ROE | Net Income / Avg Shareholders' Equity matches within 0.1% |
| ROE-002 | Negative book equity | ROE flagged as "not meaningful" (e.g., after large write-downs) |
| ROE-003 | Artificially high ROE from leverage | Agent notes high debt-to-equity as context |
| ROE-004 | ROE inflated by share buybacks | Agent distinguishes operational improvement from financial engineering |
| ROE-005 | DuPont decomposition | Profit margin * Asset turnover * Equity multiplier = ROE |

### ROIC Edge Cases

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| ROIC-001 | Standard ROIC = NOPAT / Invested Capital | Matches within 0.1% of reference |
| ROIC-002 | Excess cash handling | Excess cash stripped from invested capital (rule of thumb: 2% of revenue as operating cash) |
| ROIC-003 | Share buybacks effect | ROIC unaffected by buybacks (unlike ROE) |
| ROIC-004 | Negative NOPAT, positive net income | Operating loss masked by non-operating gains; ROIC correctly negative |
| ROIC-005 | Beginning vs. average invested capital | Verify which convention is used and that it is applied consistently |
| ROIC-006 | ROIC vs. WACC comparison | Value creation (ROIC > WACC) correctly identified |
| ROIC-007 | R&D capitalization adjustment | If agent adjusts for intangible investments, verify amortization schedule is reasonable |

### Debt Ratios

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| DEBT-001 | Debt-to-Equity standard | Total Debt / Total Equity |
| DEBT-002 | Interest coverage ratio | EBIT / Interest Expense; handle zero interest expense |
| DEBT-003 | Net debt with large cash position | Net Debt = Total Debt - Cash; can be negative |
| DEBT-004 | Off-balance-sheet obligations | Operating leases capitalized under IFRS 16/ASC 842 |

---

## 4. Edge Cases Specific to Financial Data

### Missing Data

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| MISS-001 | Missing single day in price series | Interpolation or forward-fill clearly documented |
| MISS-002 | Missing entire quarter of earnings | Agent does not fabricate data; states unavailable |
| MISS-003 | Null/NaN values in FRED series | Graceful handling; not treated as zero |
| MISS-004 | Partial OHLCV data (e.g., missing volume) | Calculations that need volume fail gracefully |
| MISS-005 | Holiday gaps in international markets | Correct alignment when comparing US and non-US data |

### Corporate Actions

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| CORP-001 | Stock split (e.g., AAPL 4:1 in 2020) | All historical prices adjusted; technical indicators recalculated |
| CORP-002 | Reverse split | Adjusted correctly (price up, shares down) |
| CORP-003 | Special dividend | Price adjustment on ex-date reflected in historical data |
| CORP-004 | Spin-off | Parent company historical data adjusted; new entity tracked separately |
| CORP-005 | Ticker change (e.g., FB to META) | Continuity of data across ticker change |
| CORP-006 | Merger/acquisition | Acquiring company data continues; acquired company data terminates |
| CORP-007 | Adjusted vs. unadjusted prices | Technical analysis uses adjusted prices; agent clearly states which it uses |

### Data Quality

| Test ID | Scenario | Expected Behavior |
|---------|----------|-------------------|
| DQ-001 | Stale price (weekend/holiday) | Friday close used for Saturday query, not treated as zero change |
| DQ-002 | Erroneous spike in data | Agent has some tolerance or validation for extreme moves |
| DQ-003 | Different data sources disagree | Agent notes discrepancy or uses stated primary source |
| DQ-004 | Time zone misalignment | US market data aligned to ET; FRED data has correct timestamps |

---

## 5. Backtesting Signal Accuracy

### Framework

Based on the CFA Level 2 curriculum and recent backtesting research, the key pitfalls to test for are:

1. **Look-ahead bias** (see Section 6)
2. **Survivorship bias** (see Section 13)
3. **Overfitting / data snooping**
4. **Transaction cost assumptions**
5. **Period selection bias**

### Concrete Test Cases

| Test ID | Description | Validation |
|---------|-------------|------------|
| BT-001 | Backtest a simple RSI(14) < 30 buy signal | Compare in-sample vs. out-of-sample Sharpe ratios; flag if in-sample > 2x out-of-sample |
| BT-002 | Walk-forward validation | Train on rolling 3-year window, test on next year; 5+ folds minimum |
| BT-003 | Transaction cost sensitivity | Run backtest at 0 bps, 5 bps, 10 bps, 25 bps slippage; report which cost levels erode alpha |
| BT-004 | Benchmark comparison | Strategy returns compared to buy-and-hold S&P 500; report excess return AND risk-adjusted return |
| BT-005 | Regime-conditional performance | Separate performance by bull/bear/sideways regimes; flag strategies that only work in bull markets |
| BT-006 | Drawdown analysis | Maximum drawdown, longest drawdown duration, recovery time |
| BT-007 | Hit rate vs. profit factor | Win rate alone is insufficient; verify average win/loss ratio |
| BT-008 | Overfitting detection | Run same strategy on random/shuffled data; if Sharpe > 0.5 on random data, likely overfit |

---

## 6. Testing for Look-Ahead Bias

### Key Principles

Look-ahead bias is one of the most insidious threats to financial analysis validity. It occurs when analysis uses information that would not have been available at the time being modeled.

### Concrete Test Cases

| Test ID | Scenario | What to Check |
|---------|----------|---------------|
| LAB-001 | Point-in-time financial statements | Agent uses report DATE (SEC filing date), not period-end date. Q4 2024 earnings filed Feb 2025 should not be available to Jan 2025 analysis |
| LAB-002 | FRED data revisions | Agent uses ALFRED vintage data, not revised values. GDP first released as 2.1%, later revised to 2.4% -- model should use 2.1% for the initial period |
| LAB-003 | Index composition | S&P 500 analysis uses historical constituents, not current. Testing a 2015 strategy with 2025 S&P 500 list introduces survivorship + look-ahead bias |
| LAB-004 | Price data timing | Trading signals based on close price cannot be executed AT the close; next-open execution is realistic |
| LAB-005 | Indicator calculation timing | RSI calculated at day t uses data up to day t only, never t+1 |
| LAB-006 | Feature engineering audit | Review all features for any reference to future data. A feature like "next quarter revenue growth" is obviously wrong; subtler cases include using end-of-day data for intraday signals |
| LAB-007 | Rolling window integrity | A 20-day moving average on day t uses days [t-19, t], never [t-18, t+1] |

### Detection Methods

1. **Suspiciously high performance:** Annual returns above 12% or Sharpe ratios above 1.5 warrant investigation (per quantitative finance research).
2. **Train/test gap analysis:** If in-sample performance is dramatically better than out-of-sample, look-ahead bias (or overfitting) is likely.
3. **Timestamp audit:** For every data point used in analysis, verify the "as-of" date vs. the "available-on" date.
4. **ALFRED cross-check:** For FRED series, compare current values to ALFRED vintage values for the same observation date.

---

## 7. Stress Testing with Extreme Market Scenarios

### Historical Extreme Scenarios

Based on Federal Reserve 2025 stress test scenarios and actual market events:

| Scenario | Parameters | What to Test |
|----------|-----------|--------------|
| **2020 COVID Crash** | SPX -34% in 23 trading days, VIX from 14 to 82, 4 circuit breaker triggers | Agent handles rapid regime change; calculations work with extreme VIX values |
| **2008 GFC** | SPX -57% peak to trough, Lehman bankruptcy, interbank lending freeze | Correlation convergence (all assets to ~1.0); agent handles missing liquidity data |
| **Flash Crash (2010 / 2024)** | SPX -10% in minutes, recovery within hours | Intraday data handling; circuit breaker awareness; agent does not generate signals during halted trading |
| **Fed 2025 Severely Adverse** | Unemployment 10%, VIX peak 65, equity decline with recession | Agent stress scores hit maximum; regime correctly classified as "crisis" |
| **Fed 2026 Proposed** | Equity decline ~54%, VIX peak 72, hedge fund failures | Agent handles VIX > 70; non-bank liquidity crisis scenarios |
| **Negative Interest Rates** | 10Y yield at -0.5% (as occurred in Europe/Japan) | Yield calculations handle negative rates; Yardeni model inputs handle negatives |
| **Zero-Bound Interest Rates** | Fed Funds at 0-0.25% | Division by zero in rate-dependent calculations avoided |
| **Oil Negative Prices** | WTI futures at -$37.63 (April 2020) | Commodity calculations handle negative prices; log returns undefined for negative prices |
| **Hyperinflation Scenario** | CPI growth 50%+ annualized | Inflation adjustments work at extreme levels |

### Concrete Test Cases

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| STRESS-001 | VIX = 80 input | All VIX-dependent calculations complete without overflow or NaN |
| STRESS-002 | SPX drops 20% in one day | Circuit breaker awareness; agent notes trading halt implications |
| STRESS-003 | All correlations converge to 1.0 | Diversification analysis correctly warns of correlation breakdown |
| STRESS-004 | Zero trading volume | Volume-dependent indicators (OBV, VWAP) return N/A, not divide-by-zero |
| STRESS-005 | Negative commodity price | Agent handles WTI < 0; percentage change calculations adjusted |
| STRESS-006 | Yield curve fully inverted | All tenor pairs inverted; late-cycle detection triggers |
| STRESS-007 | Multiple simultaneous shocks | Equity crash + rate spike + commodity spike concurrently |
| STRESS-008 | Data feed outage simulation | Agent reports stale data warnings, does not silently use old data |

---

## 8. Testing Data Staleness and Freshness

### Framework

Data freshness is about the recency of data relative to its generation. In financial contexts, stale data that passes all validation checks (correct schema, valid ranges) is particularly dangerous because it appears legitimate.

### Freshness SLAs by Data Type

| Data Type | Expected Update Frequency | Staleness Threshold |
|-----------|--------------------------|---------------------|
| Market prices (equities) | Real-time / 15-min delay | > 20 minutes during market hours |
| VIX | Real-time | > 15 minutes during market hours |
| FRED economic data | Series-dependent (monthly, quarterly) | > 1 day after scheduled release |
| DXY (Dollar Index) | Real-time | > 20 minutes during market hours |
| Commodities futures | Real-time during trading | > 20 minutes during trading hours |
| BTC futures | 24/7 trading | > 30 minutes at any time |
| Corporate financials (10-K/10-Q) | Quarterly | > 1 day after SEC filing |
| Analyst estimates | Daily | > 24 hours |

### Concrete Test Cases

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| FRESH-001 | Query price during market hours | Data timestamp within freshness SLA |
| FRESH-002 | Query FRED series day after release | Latest observation present |
| FRESH-003 | Query BTC on weekend | Data still updating (24/7 market) |
| FRESH-004 | Simulate API failure (mock stale response) | Agent includes staleness warning in output |
| FRESH-005 | Cross-check data timestamp vs. wall clock | Agent reports "as of" time for all data |
| FRESH-006 | Mixed freshness across data sources | Agent warns when combining fresh equity data with stale FRED data |
| FRESH-007 | Holiday-adjacent data | Agent correctly handles reduced-hours or closed-market dates |
| FRESH-008 | Content-based freshness check | Not just timestamp -- verify data values changed if source should have updated |

### Implementation Strategy

1. **Metadata assertion:** Every data retrieval should return a `last_updated` timestamp. Test that this is always present and parseable.
2. **Threshold alerting:** Define per-source staleness thresholds. If `now - last_updated > threshold`, the agent must warn the user.
3. **End-to-end pipeline lag:** Measure total time from source publication to agent availability.
4. **Load testing freshness:** Verify freshness SLAs hold under concurrent query load (per Great Expectations best practices).

---

## 9. Numerical Precision and Rounding

### The Core Problem

Python IEEE 754 floating-point arithmetic causes `0.1 + 0.2 = 0.30000000000000004`. For financial calculations, this is unacceptable. Small rounding errors compound across thousands of calculations.

### Rules of Engagement

| Domain | Precision Requirement | Recommended Approach |
|--------|----------------------|---------------------|
| Currency / prices | 2-4 decimal places exact | `decimal.Decimal` with explicit rounding |
| Financial ratios (P/E, ROE) | 2 decimal places for display, 6+ internally | Float acceptable with `pytest.approx(rel=1e-4)` |
| Technical indicators (RSI, MACD) | 2 decimal places for display | Float acceptable; verify against reference within 0.01 |
| Percentage returns | 4-6 decimal places | Float acceptable; compound carefully |
| Basis points calculations | 0.01 = 1 basis point | `decimal.Decimal` recommended |
| Portfolio weights | Must sum to exactly 1.0 | `decimal.Decimal` or explicit normalization |

### Concrete Test Cases

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| PREC-001 | Sum of portfolio weights | Exactly 1.0, not 0.9999999... or 1.0000001... |
| PREC-002 | Compound return over 252 days | Accumulated error < 0.01% of true value |
| PREC-003 | Basis point calculation: 5.23% - 5.21% = 2 bps | Result is exactly 0.02, not 0.019999... |
| PREC-004 | Large price * small ratio | e.g., $3,000 * 0.001 = $3.00 exactly |
| PREC-005 | Division producing repeating decimal | 1/3 handled with explicit precision, not truncated silently |
| PREC-006 | Log returns vs. simple returns consistency | For small returns, ln(1+r) approximately equal to r; divergence at large returns correctly handled |
| PREC-007 | Annualization factor | sqrt(252) for daily-to-annual vol; verify constant used |
| PREC-008 | Negative return percentage | -50% followed by +50% does NOT return to even; agent correctly shows -25% net |

### Testing Strategy

Use `pytest.approx` with appropriate tolerances:
```python
# For financial ratios
assert agent_pe == pytest.approx(expected_pe, rel=1e-3)

# For currency amounts
from decimal import Decimal
assert agent_price == Decimal("152.35")

# For technical indicators
assert agent_rsi == pytest.approx(expected_rsi, abs=0.01)
```

---

## 10. Testing Cross-Asset Correlation Calculations

### Key Research Findings

- Equity/bond correlations turned significantly positive in 2022, peaking at 50% (US) and 63% (UK) in mid-2024 (PGIM research).
- Commodity/equity correlations have decreased since October 2023, returning toward pre-GFC low-correlation levels (Lazard research).
- During extreme stress, correlations across all risk assets converge toward 1.0.
- Bitcoin correlations with traditional assets increased structurally post-COVID.

### Concrete Test Cases

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| CORR-001 | SPX vs. 10Y Treasury correlation | Sign and magnitude consistent with current regime (positive in 2022-2024 inflation regime) |
| CORR-002 | Gold vs. DXY correlation | Generally negative; agent notes when this breaks down |
| CORR-003 | VIX vs. SPX correlation | Strongly negative (~-0.7 to -0.8); agent flags anomalies |
| CORR-004 | BTC vs. SPX post-COVID | Higher correlation than pre-COVID; structural break acknowledged |
| CORR-005 | Rolling correlation window sensitivity | 30-day vs. 90-day vs. 252-day windows produce different results; agent states which window |
| CORR-006 | Correlation during crisis | Test with March 2020 data; correlations should converge |
| CORR-007 | Correlation with insufficient data | < 30 data points; agent warns about statistical insignificance |
| CORR-008 | Spurious correlation detection | Two unrelated series with coincidental correlation; agent does not claim causation |
| CORR-009 | Correlation stationarity test | Agent notes when a correlation is regime-dependent, not fixed |
| CORR-010 | Illiquid asset correlation | Infrequently-traded assets may show artificially low correlation; agent acknowledges this |

### Validation Methods

1. **Reference benchmark:** Compare agent's correlations to Portfolio Visualizer, Bloomberg, or manual Pandas calculations.
2. **Rolling window test:** Verify that the agent's stated correlation window matches its actual calculation.
3. **Statistical significance:** For any stated correlation, test that the agent reports (or considers) the p-value or confidence interval.
4. **Non-linearity awareness:** Linear (Pearson) correlation may miss nonlinear relationships; verify agent does not claim "no relationship" when rank (Spearman) correlation is significant.

---

## 11. Best Practices for Testing LLM-Based Financial Agents

### Research-Based Framework

The 2025 SAEA (risk-first audit) framework for financial LLM agents identifies three audit levels:
1. **Model level:** Hallucination, temporal staleness, overconfidence
2. **Workflow level:** Error propagation across tool chains, prompt injection, tool misuse
3. **System level:** Integration with external data, regulatory compliance, audit trails

### Hallucination-Specific Tests

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| HALL-001 | Ask about a fictitious company ticker | Agent states it cannot find data, does NOT fabricate financials |
| HALL-002 | Ask for a financial metric that requires unavailable data | Agent states the data is unavailable, not a plausible-sounding number |
| HALL-003 | Ask about a very recent event (within hours) | Agent notes potential data lag; does not hallucinate news |
| HALL-004 | Ask for a specific number (e.g., "What was AAPL's exact EPS in Q3 2024?") | Number matches SEC filing exactly, or agent cites its source and notes uncertainty |
| HALL-005 | Contradictory data scenario | Feed agent conflicting data from two sources; agent notes the discrepancy |
| HALL-006 | Complex multi-step financial calculation | Verify intermediate steps, not just the final answer |
| HALL-007 | Time-sensitivity awareness | Agent distinguishes between current data and stale training knowledge |

### Agent Reasoning Tests

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| REAS-001 | Bull case for a clearly distressed company | Agent acknowledges the distress, does not give unqualified bullish recommendation |
| REAS-002 | Contradictory signals (RSI oversold, trend still down) | Agent presents both signals, notes the conflict |
| REAS-003 | Overconfidence detection | Agent uses hedging language ("suggests," "indicates") not certainties ("will," "guaranteed") |
| REAS-004 | Consistency across repeated queries | Same question asked 3 times produces consistent answers (not contradictory) |
| REAS-005 | Chain-of-thought verification | Agent's reasoning steps are logically connected; no non sequiturs |
| REAS-006 | Appropriate disclaimers | Agent includes risk disclaimers for any investment-related output |

### Multi-Tool Chain Tests

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| CHAIN-001 | Macro analysis feeds into equity analysis | Macro regime classification is consistent with equity valuation commentary |
| CHAIN-002 | Technical + fundamental contradiction | If RSI says oversold but fundamentals say overvalued, agent presents both views |
| CHAIN-003 | Error propagation | If one tool returns an error, downstream tools do not use garbage data |
| CHAIN-004 | Circular dependency detection | Agent does not enter infinite loops when tools reference each other |

### Wall Street Prep Benchmark Findings (2026)

Key deficiency patterns found in financial AI agents:
- Agents frequently hardcode values that should flow through calculations
- No agent correctly modeled shares outstanding in integrated 3-statement models
- Good for getting from 0 to ~60% of a model; bad for trusting to finish without review
- Success rates decrease after 35 minutes of continuous task complexity

---

## 12. Regulatory Considerations

### SR 11-7 Model Risk Management

The Federal Reserve's SR 11-7 (2011) remains the foundational guidance for model risk management. Key requirements applicable to financial AI agents:

1. **Model validation:** "The set of processes and activities intended to verify that models are performing as expected, in line with their design objectives and business uses."
2. **Documentation requirements:** Every model must have documentation of its methodology, assumptions, limitations, and testing results.
3. **Ongoing monitoring:** Models must be re-validated periodically and when market conditions change materially.
4. **Challenge function:** Independent review must be able to challenge model outputs effectively.

### FINRA Expectations (2025-2026)

- Existing rules (technologically neutral) apply when firms use AI, including GenAI.
- Model explainability is the biggest challenge: FINRA acknowledges "black box" concerns.
- Firms must consider supervisory processes specific to AI agents, including how to monitor agent system access and data handling.
- Firms must maintain comprehensive records of AI-generated communications and decision-making processes (Rules 17a-3 and 17a-4).
- Financial penalties exceeded $4 billion in 2024; the SEC fined 16 firms $81 million for electronic communication recordkeeping failures.

### SEC 2026 Examination Priorities

- Focus on accuracy of AI capability representations
- Assessment of policies/procedures for monitoring AI use
- Reviews of AI integration in fraud prevention, AML, trading functions
- Verification that AI disclosures are accurate (no "AI washing")

### Testing Implications

| Test ID | Regulatory Requirement | Test |
|---------|----------------------|------|
| REG-001 | Explainability (FINRA) | For every recommendation, agent can cite the data points and logic that led to it |
| REG-002 | Audit trail (SR 11-7) | Every agent invocation logs: input, tools called, intermediate results, final output, timestamps |
| REG-003 | Disclaimer requirements | Agent includes appropriate disclaimers ("not investment advice") |
| REG-004 | Accuracy of representations | Agent does not claim capabilities it lacks (e.g., "real-time" when data is delayed) |
| REG-005 | Record retention | All agent interactions stored in compliant format for required retention period |
| REG-006 | Bias detection (NIST AI RMF) | Regular testing for systematic bias in recommendations across sectors, market caps, geographies |
| REG-007 | Consistent methodology | Same inputs produce same analytical framework (not random tool selection) |

---

## 13. Testing for Survivorship Bias

### The Scale of the Problem

Research demonstrates the dramatic impact of survivorship bias:
- Excluding defunct stocks can overstate annual returns by 1-4% (academic research).
- In one Nasdaq 100 backtest, CAGR was 46% with survivorship bias vs. 16.4% without (Wealth-Lab).
- Going back 10 years in North America, a biased dataset misses 75% of stocks that were actually trading (QuantRocket).
- 58% of mutual funds that existed in 1999 did not exist in 2019 (Morningstar).
- The FINSABER framework (2025) showed that LLM-based investment strategy advantages "deteriorate significantly under broader cross-section and longer-term evaluation."

### Concrete Test Cases

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| SURV-001 | S&P 500 historical screening uses point-in-time constituents | 2015 screen uses 2015 S&P 500 members, not current members |
| SURV-002 | Delisted companies in backtest | Companies like Lehman Brothers, Enron appear in pre-failure analysis |
| SURV-003 | Merger/acquisition handling | Acquired companies correctly terminate; returns include acquisition premium |
| SURV-004 | Equity screener on historical data | Agent explicitly states whether it uses survivorship-free data |
| SURV-005 | Index reconstitution awareness | Agent notes when analyzing historical index data that composition has changed |
| SURV-006 | Performance comparison with survivorship-free benchmark | Backtested returns compared to index returns that include reconstitution effects |
| SURV-007 | Monte Carlo / bootstrap validation | Agent validates strategy robustness with resampled data |
| SURV-008 | Peer comparison with defunct peers | Industry comparison includes companies that were peers at the time, not just current survivors |

### Detection Strategy

1. **Red flag:** Unrealistically high returns that consistently beat the market.
2. **Red flag:** Overly smooth equity curves with minimal drawdowns.
3. **Verification:** Cross-reference the number of tickers in any historical screen against the actual number trading at that time.
4. **Data source audit:** Verify that the underlying data provider includes delisted securities.

---

## 14. Domain-Specific Test Cases

### VIX Framework Testing

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| VIX-001 | VIX term structure (contango vs. backwardation) | Correct identification of VIX futures curve shape |
| VIX-002 | VIX spike classification | VIX > 30: elevated; > 40: high stress; > 60: extreme/crisis |
| VIX-003 | VIX mean reversion awareness | Agent notes that VIX tends to mean-revert from extremes |
| VIX-004 | VIX vs. realized volatility divergence | Agent notes when implied vol (VIX) diverges significantly from realized vol |
| VIX-005 | VIX as predictor of SPX returns | Agent does not claim VIX predicts direction, only expected magnitude of moves |
| VIX-006 | VIX calculation limitations | Agent acknowledges VIX assumes normal distribution, missing heavy tails |

### Commodity Analysis Testing

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| COMM-001 | Oil contango/backwardation | Futures curve shape correctly identified |
| COMM-002 | Gold vs. real rates relationship | Inverse relationship acknowledged |
| COMM-003 | Commodity seasonality | Agricultural commodities show harvest-related patterns |
| COMM-004 | Negative oil price handling | WTI at -$37.63 (April 2020) does not break calculations |
| COMM-005 | Commodity supercycle detection | Multi-year trend identification across commodity complex |

### BTC Futures Testing

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| BTC-001 | 24/7 market awareness | Agent does not assume BTC follows equity market hours |
| BTC-002 | CME futures vs. spot divergence | Basis correctly calculated |
| BTC-003 | Extreme volatility handling | BTC can move 20%+ in a day; calculations robust |
| BTC-004 | Post-COVID correlation regime | Agent notes BTC-equity correlation increased structurally post-2020 |
| BTC-005 | Halving cycle awareness | Agent can discuss supply schedule impact on valuation |
| BTC-006 | Regulatory classification ambiguity | Agent notes commodity vs. security debate |

### Valuation Framework Testing

#### Graham Number

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| GRAH-001 | Standard calculation | sqrt(22.5 * EPS * BVPS) correct |
| GRAH-002 | Negative EPS input | Graham Number undefined; agent returns N/A |
| GRAH-003 | Negative BVPS input | Graham Number undefined; agent returns N/A |
| GRAH-004 | Growth company limitation | Agent notes Graham Number is conservative, not suitable for high-growth tech |
| GRAH-005 | Margin of safety calculation | Discount from Graham Number correctly applied |

#### Yardeni Model

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| YARD-001 | Standard calculation | CEY = CBY - k * LTEG, solved for implied P/E |
| YARD-002 | Negative or zero growth input | Model handles gracefully |
| YARD-003 | Historical validation | Agent acknowledges Yardeni himself noted the model stopped working well post-1997 |
| YARD-004 | Comparison with Fed Model | Agent notes limitations: Fed Model has "no power to forecast long-term stock returns" per academic research |
| YARD-005 | Current market application | Agent presents result with appropriate caveats about model limitations |

### FRED / Macroeconomic Data Testing

| Test ID | Description | Expected Behavior |
|---------|-------------|-------------------|
| FRED-001 | GDP data revision handling | Agent uses first release or states which vintage |
| FRED-002 | CPI release timing | Agent knows CPI typically released ~13th of month; analysis before release does not use unreleased data |
| FRED-003 | Unemployment rate (U3 vs. U6) | Agent specifies which measure and notes the difference |
| FRED-004 | Yield curve construction | All tenors correctly sourced and plotted |
| FRED-005 | DXY component awareness | Agent knows DXY is weighted (57.6% EUR, etc.) |
| FRED-006 | Real vs. nominal rate calculations | Fisher equation applied correctly |

---

## 15. Concrete Test Case Catalog

### Priority 1: Critical (Must-Have)

These tests prevent the most dangerous failure modes:

1. **HALL-001 through HALL-007:** Hallucination detection (LLM fabricating financial data)
2. **LAB-001 through LAB-007:** Look-ahead bias prevention
3. **PE-002, PE-003:** Division by zero / negative earnings handling
4. **STRESS-001 through STRESS-005:** Extreme market scenario robustness
5. **FRESH-001 through FRESH-004:** Data staleness detection
6. **PREC-001, PREC-003:** Precision in currency and basis point calculations
7. **REG-001 through REG-003:** Regulatory compliance basics

### Priority 2: High (Should-Have)

These tests ensure analytical accuracy:

1. **RSI-001 through RSI-007:** Technical indicator calculation accuracy
2. **MACD-001 through MACD-006:** MACD accuracy
3. **CORR-001 through CORR-006:** Cross-asset correlation validity
4. **REG-001 through REG-008:** Market regime classification
5. **SURV-001 through SURV-005:** Survivorship bias prevention
6. **ROIC-001 through ROIC-007:** Financial ratio accuracy
7. **CHAIN-001 through CHAIN-004:** Multi-tool chain integrity

### Priority 3: Medium (Nice-to-Have)

These tests improve robustness and polish:

1. **CORP-001 through CORP-007:** Corporate action handling
2. **BT-001 through BT-008:** Backtesting methodology validation
3. **VIX-001 through VIX-006:** VIX framework completeness
4. **GRAH-001 through GRAH-005:** Valuation model accuracy
5. **YARD-001 through YARD-005:** Yardeni model validation
6. **REAS-001 through REAS-006:** Agent reasoning quality
7. **FRED-001 through FRED-006:** Macroeconomic data handling

---

## Implementation Recommendations

### Test Infrastructure

1. **Golden dataset approach:** Create a curated set of known-good financial data with pre-calculated expected outputs. Use this as your regression test suite.

2. **Reference implementation comparison:** Cross-check agent calculations against:
   - TA-Lib / pandas_ta for technical indicators
   - Bloomberg / FactSet for financial ratios
   - ALFRED for point-in-time FRED data
   - Portfolio Visualizer for correlations

3. **Deterministic seed tests:** For any stochastic components, use fixed random seeds to ensure reproducibility.

4. **Snapshot testing:** Capture full agent outputs for known inputs; compare against snapshots for regression detection.

5. **Property-based testing:** Use Hypothesis (Python) to generate random valid financial inputs and verify invariants (e.g., RSI always in [0, 100], portfolio weights sum to 1.0).

### Continuous Testing Strategy

1. **Pre-commit:** Numerical precision tests, schema validation tests
2. **CI/CD pipeline:** Full regression suite against golden datasets
3. **Daily:** Data freshness SLA validation, API health checks
4. **Weekly:** Full backtest regression, cross-source data consistency checks
5. **Monthly:** Regime classification accuracy review against realized market conditions
6. **Quarterly:** Full model validation review (SR 11-7 aligned)

---

## Sources

### Financial AI Agent Testing & Governance
- [Neurons Lab: Agentic AI in Financial Services 2026](https://neurons-lab.com/article/agentic-ai-in-financial-services-2026/)
- [Wall Street Prep: Ranking AI Tools for Financial Modeling 2026](https://www.wallstreetprep.com/knowledge/ranking-the-best-ai-tools-for-financial-modeling-2026/)
- [PwC: 2026 AI Business Predictions](https://www.pwc.com/us/en/tech-effect/ai-analytics/ai-predictions.html)

### Market Regime Classification
- [State Street: Decoding Market Regimes with Machine Learning](https://www.ssga.com/library-content/assets/pdf/global/pc/2025/decoding-market-regimes-with-machine-learning.pdf)
- [Ensemble-HMM Voting Framework for Market Regime Detection](https://www.aimspress.com/article/id/69045d2fba35de34708adb5d)
- [LSEG: Market Regime Detection Using Statistical and ML Approaches](https://developers.lseg.com/en/article-catalog/article/market-regime-detection)

### Look-Ahead Bias & Backtesting
- [CFA Institute: Problems in Backtesting](https://analystprep.com/study-notes/cfa-level-2/problems-in-backtesting/)
- [Corporate Finance Institute: Look-Ahead Bias](https://corporatefinanceinstitute.com/resources/career-map/sell-side/capital-markets/look-ahead-bias/)
- [LuxAlgo: Backtesting Traps](https://www.luxalgo.com/blog/backtesting-traps-common-errors-to-avoid/)
- [Starqube: Critical Pitfalls of Backtesting](https://starqube.com/backtesting-investment-strategies/)

### Stress Testing & Extreme Scenarios
- [Federal Reserve: 2025 Stress Test Scenarios](https://www.federalreserve.gov/publications/2025-stress-test-scenarios.htm)
- [BIS: Predicting Financial Market Stress with ML](https://www.bis.org/publ/work1250.pdf)
- [CEPR: AI Financial Crises](https://cepr.org/voxeu/columns/ai-financial-crises)
- [Medium: AI's Role in the 2024 Flash Crash](https://medium.com/@jeyadev_needhi/ais-role-in-the-2024-stock-market-flash-crash-a-case-study-55d70289ad50)

### LLM Hallucination & Financial Agent Evaluation
- [Open FinLLM Leaderboard / Evaluation Suite](https://arxiv.org/html/2602.19073)
- [SAEA: Auditing LLM Agents in Finance](https://arxiv.org/pdf/2502.15865)
- [HalluLens: LLM Hallucination Benchmark (ACL 2025)](https://arxiv.org/html/2504.17550v1)
- [MIT Thesis: Mitigating LLM Hallucination in Banking](https://dspace.mit.edu/bitstream/handle/1721.1/162944/sert-dsert-meng-eecs-2025-thesis.pdf)

### Survivorship Bias
- [LuxAlgo: Survivorship Bias in Backtesting](https://www.luxalgo.com/blog/survivorship-bias-in-backtesting-explained/)
- [QuantRocket: A Primer on Survivorship Bias](https://www.quantrocket.com/blog/survivorship-bias/)
- [FINSABER: LLM Investing Strategy Evaluation](https://arxiv.org/html/2505.07078v4)
- [Wealth-Lab: Avoid Survivorship Bias with Dynamic DataSets](https://www.wealth-lab.com/blog/survivorship-bias)

### Financial Ratios & Valuation
- [Morgan Stanley: Return on Invested Capital](https://www.morganstanley.com/im/publication/insights/articles/article_returnoninvestedcapital.pdf)
- [NYU Stern (Damodaran): ROC, ROIC, and ROE](https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/returnmeasures.pdf)
- [CFA Institute: Beyond the Fed Model](https://blogs.cfainstitute.org/investor/2025/01/17/beyond-the-fed-model-dissecting-equity-valuation-trends/)
- [Graham Number: Applying in Value Investing](https://pictureperfectportfolios.com/applying-the-graham-number-in-value-investing/)

### Cross-Asset Correlations
- [PGIM: Cross-Asset Correlations in Market Turbulence](https://www.pgim.com/us/en/institutional/insights/asset-class/multi-asset/quantitative-solutions/cross-asset-correlations-constructing-portfolios-amid-market-turbulence)
- [Lazard: Why Commodities?](https://www.lazardassetmanagement.com/docs/231442/WhyCommoditiesAForgottenAssetClass.pdf)
- [PIMCO: Negative Correlations, Positive Allocations](https://www.pimco.com/us/en/insights/negative-correlations-positive-allocations)

### Numerical Precision
- [Python Official: Floating-Point Arithmetic](https://docs.python.org/3/tutorial/floatingpoint.html)
- [Pytest with Eric: pytest.approx for Numeric Testing](https://pytest-with-eric.com/pytest-advanced/pytest-approx/)
- [UC Berkeley: Round-off Errors in Python](https://pythonnumericalmethods.berkeley.edu/notebooks/chapter09.03-Roundoff-Errors.html)

### Regulatory Compliance
- [ModelOp: SR 11-7 Compliance & Governance](https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7)
- [FINRA: 2026 Annual Regulatory Oversight Report](https://www.finra.org/sites/default/files/2025-12/2026-annual-regulatory-oversight-report.pdf)
- [FINRA: GenAI Emerging Trends](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai)
- [SEC: 2026 Examination Priorities](https://www.sec.gov/files/2026-exam-priorities.pdf)
- [GAO: AI Use and Oversight in Financial Services](https://www.gao.gov/assets/gao-25-107197.pdf)

### Data Freshness & FRED
- [FRED API Documentation](https://fred.stlouisfed.org/docs/api/fred/)
- [ALFRED: Archival FRED](https://alfred.stlouisfed.org/)
- [St. Louis Fed: Data Revisions with FRED](https://www.stlouisfed.org/publications/page-one-economics/2022/08/01/data-revisions-with-fred)
- [Great Expectations: Validate Data Freshness](https://docs.greatexpectations.io/docs/reference/learn/data_quality_use_cases/freshness/)

### Bitcoin & Cryptocurrency
- [PMC: Forecasting Bitcoin Futures Mid-Price](https://pmc.ncbi.nlm.nih.gov/articles/PMC8296834/)
- [PMC: Bitcoin Spot and Futures Risk Spillovers](https://pmc.ncbi.nlm.nih.gov/articles/PMC9476405/)
