# Financial Agent: Qualitative "Taste" Evaluation Report

**Date**: 2026-03-12 (v3 — second post-fix re-evaluation)
**Target**: `/full_report` pipeline (8 tools)
**Evaluated by**: Testing Agent — 5 approaches, 100+ checks
**Runs**: v1 (baseline) → v2 (first fix) → v3 (second fix)

---

## Executive Summary

The Financial Agent codebase received a second round of fixes targeting the 5 remaining bugs from v2. This v3 evaluation shows **continued incremental progress** — the breakeven contradiction is resolved and housing leading indicators are improved — but core issues in consumer health labeling and analytical quality remain.

### Scorecard: v1 → v2 → v3

| Approach | What It Tests | v1 | v2 | v3 | v2→v3 Delta |
|----------|--------------|----|----|----|----|
| #2 Coherence | Do sections contradict each other? | 90.9% (10/11) | 90.9% (10/11) | 90.9% (10/11) | ➡️ Same — C-01b still failing |
| #3 Grounding | Do labels match numbers? | 40.0% (4/10) | 66.7% (4/6) | 66.7% (4/6) | ➡️ Same — bond false positive + consumer health |
| #4 LLM Judge | How good is this analysis? | 3.35/10 | 3.3/10 | 3.4/10 | ➡️ +0.1 — within LLM variance |
| #5 Backtesting | Do signals predict reality? | 20 signals | 19 signals | 19 signals | ➡️ New snapshot taken |
| #6 Data Accuracy | Are the numbers correct? | 87.1% (61/70) | 89.9% (62/69) | 92.2% (59/64) | ⬆️ +2.3pp — 3 fixes confirmed |

### What Was Fixed in v3

| Bug | Fix Applied | Evidence |
|-----|------------|----------|
| BUG-2: Breakeven contradiction | ✅ **FIXED** | `BREAKEVEN_FALLING` replaced with `BREAKEVEN_MIXED`. Signals now `BREAKEVEN_RISING` + `BREAKEVEN_MIXED` — logically coherent when different tenors diverge. Approach #6 I-01 now passes. |
| BUG-3: Market cap data (partial) | ✅ **PARTIALLY FIXED** | `marketcap_to_gdp` no longer shows -99.86% daily move (now 1.26%). `market_cap` daily move reduced to 8.57% (under 50% threshold). But monthly move still +108.74%. |
| BUG-5: Housing leading indicator (partial) | ✅ **PARTIALLY FIXED** | `leading_indicator_signal` changed from `NO_WARNING` → `HOUSING_CAUTION` with explanatory text: "Existing home sales plunging — demand-side weakness. Monitor permits and starts for supply-side confirmation." Approach #6 I-04 now passes. Cycle phase still "mixed." |

### What Remains Unfixed

| Bug | Status | Impact |
|-----|--------|--------|
| BUG-3 residual: market_cap +108.74% monthly | ❌ **NOT FIXED** | Still implies market cap more than doubled in a month (Approach #6 F-03) |
| BUG-4: Consumer health "stable" at 3.13 | ❌ **NOT FIXED** | Score 3.13/10 should map to "stressed" (Approaches #3, #6 I-05) |
| BUG-5 residual: Housing phase "mixed" with distress | ❌ **NOT FIXED** | `housing_cycle_phase = "mixed"` despite 3 distress signals firing (Approach #6 I-07) |
| BUG-6: Recessionary regime + moderate stress | ❌ **NOT FIXED** | Stress 3.9/10 while regime says "Recessionary" (Approach #2 C-01b) |
| Analytical quality | ❌ **NOT ADDRESSED** | LLM judge 3.4/10 — no causal reasoning, no actionable recommendations |

### Cumulative Progress (v1 → v3)

| Bug | v1 | v2 | v3 |
|-----|----|----|-----|
| BUG-1: Credit spread classification | ❌ | ✅ Fixed | ✅ Stays fixed |
| BUG-2: Breakeven contradiction | ❌ | ❌ | ✅ Fixed |
| BUG-3: Market cap data | ❌ | ❌ | ⚠️ Partially fixed (daily resolved, monthly remains) |
| BUG-4: Consumer health label | ❌ | ❌ | ❌ |
| BUG-5: Housing logic | ❌ | ❌ | ⚠️ Partially fixed (leading indicator improved, phase remains) |
| BUG-6: Regime-stress coherence | — | 🆕 | ❌ |

---

## How Testing Is Conducted

This section describes each evaluation approach in detail — what it does, how it works, what data it consumes, what it checks, and how to interpret results. This is intended for the agent working on the Financial Agent codebase so you understand exactly what is being tested and why failures occur.

### Input Data

All approaches consume the same input: the JSON output of the 8 `/full_report` tools executed together:

```
scan_all_indicators    → 27 indicators with latest, daily_pct, top_flags
analyze_macro_regime   → regime classifications, composite_outlook, signals, inflation_detail
analyze_financial_stress → composite_score, 8 weighted components, supplemental, signals
detect_late_cycle_signals → count, confidence_level, firing signals
analyze_equity_drivers → real_yield_impact, credit_equity_link, dxy_impact, rolling_correlations
analyze_bond_market    → yield_curve, real_yields, breakevens, credit_spreads, term_premium
analyze_consumer_health → composite_score, 4 weighted components, consumer_health_level
analyze_housing_market → starts, permits, sales_trend, affordability, cycle_phase, signals
```

Tests can run against live data (`python <approach>.py`) or a saved JSON snapshot (`python <approach>.py --input full_report_output.json`).

---

### Approach #2: Internal Coherence & Contradiction Detection

**File**: `taste/approach_2_coherence/coherence_checker.py`
**Technique**: Pure Python rule-based cross-checking. No LLM needed.

**What it does**: Compares claims made by different tools within the same `/full_report` to see if they logically agree with each other. It does NOT check if the data is correct — it checks if Tool A's conclusion is compatible with Tool B's conclusion, given the same underlying data.

**How it works structurally**:
1. Loads the full report JSON (all 8 tools).
2. Extracts key values and classifications from each tool (e.g., HY OAS from `analyze_bond_market`, stress level from `analyze_financial_stress`, regime from `analyze_macro_regime`).
3. Applies 11 domain-logic rules that encode known financial relationships (e.g., "if VIX > 25, stress level should not be 'low'").
4. Each rule produces a `CoherenceResult` with: rule_id, left_claim (what Tool A says), right_claim (what Tool B says), passed/failed, severity, and an explanation of why the contradiction matters.

**The 11 rules it checks**:

| Rule ID | Rule | Logic |
|---------|------|-------|
| C-01 | Macro regime vs. stress level | Reflationary/goldilocks → stress < 6. Recessionary → stress > 4. |
| C-02 | Credit spread level vs. interpretation | If HY OAS > 250bps, narrative must NOT say "tight" / "supportive" / "benign". |
| C-03 | Yield curve shape vs. late-cycle count | Inverted curve → late-cycle count should be >= 3. Normal curve → count should be <= 8. |
| C-04 | Housing distress vs. consumer health | If housing signals include "plunging" / "collapse", consumer health must NOT be "healthy". |
| C-05 | VIX level vs. stress classification | VIX > 25 → stress at least "moderate". VIX < 15 → stress should not be "high"/"extreme". |
| C-06 | Growth regime vs. ISM signal | Regime = "expansion" should not coexist with ISM_CONTRACTION signal. |
| C-07 | Contradictory signal pairs | Scans ALL signals across ALL tools for mutually exclusive pairs (CREDIT_LOOSE + CREDIT_TIGHT, INFLATION_HOT + INFLATION_COOLING, etc.). |
| C-08 | Bank stress vs. consumer credit | BANK_SYSTEMIC_STRESS signal → consumer credit should not be "healthy" / "robust". |
| C-09 | Real yield direction vs. equity narrative | Real yields > 2% and rising → equity summary should mention headwind / pressure / compression. |
| C-10 | Rate regime vs. Fed policy signals | Rate regime "easing" must not coexist with FED_TIGHTENING signal (and vice versa). |
| C-11 | Scan flag rate vs. stress level | > 70% of indicators flagged → stress should not be "low". |

**How to interpret results**: Each rule is either `PASS` or `FAIL`. Failures include severity (critical/high/medium/low). A "left_claim" and "right_claim" show the two contradicting pieces. The "explanation" tells you *why it matters from a financial perspective*.

**What it CANNOT catch**: It only catches contradictions you've coded rules for. It won't find novel inconsistencies. It also doesn't evaluate if the *data itself* is correct — only if the *conclusions across tools* are mutually compatible.

**When this test will pass**: When every tool's classification, label, and signal is consistent with every other tool's classification for the same underlying metric. No tool says "tight" while another says "loose" for the same spread.

---

### Approach #3: Narrative-vs-Data Grounding (Hallucination Detection)

**File**: `taste/approach_3_grounding/grounding_evaluator.py`
**Technique**: Rule-based claim extraction + financial threshold dictionary. No LLM in current version.

**What it does**: Checks whether the **qualitative labels** in narrative fields (like "summary", "interpretation", "assessment", "composite_outlook") are supported by the **quantitative numbers** in the same output. When the narrative says "credit spreads are tight" but the data shows HY OAS = 313bps, the label "tight" is not grounded in the data.

**How it works structurally**:
1. Defines a `THRESHOLDS` dictionary mapping metric names to labeled ranges:
   ```
   hy_oas_bps:  tight=(0,150), normal=(150,300), wide=(300,500), stressed=(500,800)
   vix:         complacent=(0,12), calm=(12,16), normal=(16,20), elevated=(20,25), fearful=(25,35)
   stress_score: low=(0,2.5), moderate=(2.5,5), elevated=(5,7), high=(7,9)
   cpi_yoy_pct: deflationary=(<0), low=(0,2), target=(2,2.5), above_target=(2.5,3.5), hot=(3.5,5)
   real_yield_10y_pct: negative=(<0), low=(0,1), moderate=(1,2), high=(2,3)
   consumer_health_score: critical=(0,3), stressed=(3,5), stable=(5,7), healthy=(7,10)
   late_cycle_count: early_cycle=(0,3), mid_cycle=(3,6), late_cycle=(6,10)
   ```
2. Extracts narrative text from summary/interpretation/assessment fields across all tools.
3. Scans each narrative for label words ("tight", "wide", "supportive", "stressed", "cooling", "elevated", etc.).
4. Looks up the actual metric value in the structured data.
5. Classifies the actual value using the threshold dictionary.
6. Compares: Does the label in the narrative match the classification from the threshold dictionary?
7. Produces `GroundingClaim` objects: source_tool, source_field, metric_name, asserted_label, actual_value, actual_label, grounded (bool), explanation.

**What it checks specifically** (7 claim categories):
1. Credit spread interpretation — Does "tight"/"supportive"/"wide" in bond/equity narratives match HY OAS level?
2. Stress level vs. composite score — Does the stress_level label match the numeric stress_score?
3. VIX characterization — Do VIX descriptions in any narrative match the actual VIX value?
4. Inflation characterization — Does inflation regime ("hot"/"cooling") match CPI YoY?
5. Late-cycle confidence — Does confidence_level label match the late_cycle_count?
6. Real yield characterization — Do real yield descriptions ("moderate"/"high") match actual 10Y real yield?
7. Consumer health level vs. score — Does "stable"/"stressed"/"healthy" match the composite_score?

**Known limitation (v2+)**: The scanner matches label words like "accommodative" anywhere in narrative text. The bond market summary uses "Neutral-to-accommodative" to describe **Fed policy**, but the scanner attributes this to credit spread classification, creating a false positive. The word "accommodative" maps to the "supportive" label family, which then gets compared against HY OAS. This is a test sensitivity issue, not an agent bug.

**How to interpret results**: Each claim is either `GROUNDED` (label matches data) or `UNGROUNDED` (label contradicts data). The output shows what the narrative asserted vs. what the threshold dictionary says the data actually means. Grounding rate is the % of claims that match.

**What it CANNOT catch**: It only checks labels it has thresholds for. Ambiguous or subjective claims ("conditions are challenging") can't be verified. It also doesn't check if the *numbers* are correct — only if the *labels applied to those numbers* are correct.

**Key difference from Approach #6**: Approach #3 asks "does 'tight' match 313bps?" (answer: no, 313bps is 'wide'). Approach #6 asks "does 313bps - 84bps = 229bps?" (answer: yes, the arithmetic is correct). They test different layers of correctness.

**When this test will pass**: When every label in every narrative field accurately describes the underlying metric. "tight" is only used when HY OAS < 150bps. "stable" is only used when consumer health score is 5-7. No mismatch between words and numbers.

---

### Approach #4: Comparative Benchmarking (LLM-as-Judge)

**File**: `taste/approach_4_comparative/comparative_benchmark.py`
**Technique**: Sends the agent's full output to an LLM judge for scoring on a 7-dimension rubric.

**What it does**: Evaluates the *overall quality* of the analysis as a financial research product — not just correctness, but depth, coherence, actionability, and professionalism. Scores each dimension 1-10 and produces written critiques with specific improvement suggestions. Can also do pairwise comparison against professional analyst reports.

**How it works structurally**:
1. Converts the agent's structured JSON output into human-readable text (formats each tool's output into paragraphs).
2. Constructs a detailed evaluation prompt with the rubric definitions.
3. Sends to an LLM judge with `temperature=0.3` for consistency.
4. Parses the LLM's structured JSON response containing scores, critiques, verdict, and improvement areas.
5. Computes a weighted aggregate score.

**The 7 rubric dimensions** (adapted from CFA Research Challenge + FinDeepResearch HisRubric):

| Dimension | Weight | What It Evaluates | Score Guide |
|-----------|--------|-------------------|-------------|
| Data Accuracy & Traceability | 15% | Are figures cited with sources? FRED/BLS references? Verifiable? | 3-4 = numbers present but no sources |
| Analytical Depth | 20% | Does it explain *why*, not just *what*? Cause-effect chains? Second-order thinking? | 3-4 = describes conditions; 7+ = explains causality |
| Internal Coherence | 15% | Do sections agree? Are contradictions reconciled? | 3-4 = contradictions present, unacknowledged |
| Actionability | 20% | Sector tilts? Duration calls? Risk management? Hedging? | 1-2 = no recommendations at all |
| Completeness & Risk Assessment | 10% | Alternative scenarios? Base/bull/bear cases? Risks identified? | 3-4 = single scenario, no alternatives |
| Professional Quality | 10% | Terminology, caveats, structure, proportionate detail? | 5-6 = well-structured but with gaps |
| Signal Specificity & Originality | 10% | Cross-dimensional insights? Or generic enums? Beyond Bloomberg terminal? | 3-4 = restates data as signals |

**Scoring calibration**:
- 1-2: Missing or fundamentally wrong
- 3-4: Present but superficial/template-like
- 5-6: Adequate but lacks depth or specificity
- 7-8: Good — demonstrates real analytical thinking
- 9-10: Excellent — insightful, actionable, professional-grade

**How to interpret results**: The weighted score (currently 3.4/10) is the headline metric. Per-dimension scores show where the agent is weakest. The LLM's written critiques explain *specifically what is wrong* with examples from the text. The "top_improvement_areas" are the highest-leverage changes.

**Modes**:
- **Solo mode** (`--solo`): Evaluates the agent's output standalone, no reference needed. Used for current baseline.
- **Pairwise mode** (`--ref <path>`): Compares agent vs. a professional analyst report on the same rubric. Produces gap analysis.

**What it CANNOT catch**: LLM judges have variance (~1-2 points per dimension across runs). The rubric is calibrated against CFA expectations, which may be unrealistically high for an automated system. It also doesn't verify factual correctness — it evaluates analytical quality.

**When this score will improve**: When narratives explain *why* indicators are moving (e.g., "inflation is cooling due to base effects and declining used car prices, not demand destruction"), when contradictions are explicitly reconciled (e.g., "despite recessionary conditions, stress remains moderate because..."), and when actionable recommendations are added (e.g., "overweight defensive sectors, reduce duration exposure").

---

### Approach #5: Forward-Looking Signal Backtesting

**File**: `taste/approach_5_backtesting/signal_tracker.py`
**Technique**: Snapshot-then-verify longitudinal tracking.

**What it does**: Captures every directional signal the agent emits (e.g., `INFLATION_COOLING`, `ISM_CONTRACTION`, `CREDIT_TIGHT`) with a timestamp, then checks after 1/4/12 weeks whether the predicted direction actually materialized. This is the ultimate test: does the analysis predict reality?

**How it works structurally**:
1. **SNAPSHOT phase** (`python signal_tracker.py snapshot`):
   - Runs /full_report or loads saved JSON.
   - Extracts all `signals` arrays from every tool.
   - Matches each signal to a `SIGNAL_DEFINITIONS` dictionary containing: category, predicted direction (up/down/neutral), verification metric, verification condition, FRED series, and horizon (1w/4w/12w).
   - Saves snapshot with timestamp and 19 key reference metrics (CPI, ISM, VIX, HY OAS, fed funds, etc.) for later comparison.

2. **VERIFY phase** (`python signal_tracker.py verify`):
   - Loads old snapshot(s) that have matured past their horizon.
   - Pulls current data for the verification metrics.
   - Compares direction: Did the metric move in the predicted direction?
   - Example: `INFLATION_COOLING` predicted CPI would decrease → Did it?

3. **REPORT phase** (`python signal_tracker.py report`):
   - Aggregates all verifications into per-signal precision/recall/F1.
   - Compares against naive baselines ("no change" model).

**Signal definitions** (30+ defined, example entries):

| Signal | Category | Direction | Verification Metric | Horizon |
|--------|----------|-----------|-------------------|---------|
| INFLATION_COOLING | inflation | down | CPI YoY decrease | 4w, 12w |
| ISM_CONTRACTION | growth | down | ISM PMI stays < 50 | 4w |
| CREDIT_TIGHT | credit | up | HY OAS widens or stays elevated | 4w |
| EXISTING_SALES_PLUNGING | housing | down | Existing sales continue declining | 4w, 12w |
| FED_EASING | rates | down | Fed funds rate decreases | 4w, 12w |

**Current status**: Three snapshots taken. v1 (20 signals, 6 known), v2 (19 signals, 6 known), v3 (19 signals, 6 known). Verification windows: v1 +1w (Mar 18), +4w (Apr 8), +12w (Jun 3).

**What it CANNOT catch**: Slow-moving macro signals (regime changes) need 3-12 months to evaluate. Small sample sizes in early stages. Also cannot evaluate the *quality* of signals — only whether their directional prediction was correct.

**When this test will show results**: After the first verification horizon passes (1 week minimum). Full utility requires 2-3 months of weekly snapshots.

---

### Approach #6: Data Accuracy Verification

**File**: `taste/approach_6_data_accuracy/data_accuracy_checker.py`
**Technique**: Pure Python arithmetic verification, cross-tool comparison, and domain-rule checking. No LLM needed.

**What it does**: Verifies whether the **numbers themselves** are mathematically correct — whether computed fields match their inputs, whether the same metric agrees across tools, whether composite scores decompose properly, and whether percentage moves are plausible. This is the most granular, "mechanical" test.

**How it works structurally**:
1. Loads the full report JSON.
2. Runs 7 categories of checks (64-70 total, varies based on conditional checks) via `run_all_checks(report_data)`:
   - `check_arithmetic()` — 10 checks
   - `check_cross_tool_consistency()` — 8 checks
   - `check_composite_scores()` — 4 checks
   - `check_flag_alignment()` — ~19-23 checks (varies with market data)
   - `check_range_plausibility()` — 16 checks
   - `check_internal_contradictions()` — 5-7 checks (some conditional)
   - `check_temporal_consistency()` — 2 checks

**The 7 check categories in detail**:

#### Category 1: Arithmetic Consistency (10 checks)
Verifies mathematical identities that must hold:

| Check | Formula | Tolerance |
|-------|---------|-----------|
| A-01 | 2s10s spread = 10Y_nominal - 2Y_nominal | +/-2bp |
| A-02 | Term premium = nominal_10Y - real_10Y - breakeven_10Y | +/-10bp |
| A-03 | HY-IG differential = HY_OAS_bps - IG_OAS_bps | +/-2bp |
| A-04 | OAS_pct x 100 = OAS_bps (for HY, IG, BBB) | +/-1bp |
| A-05 | Permits/starts ratio = permits_value / starts_value | +/-2% |
| A-06 | Monthly payment ~ median_price x mortgage_rate / 12 | +/-5% |
| A-07 | 10Y breakeven ~ nominal_10Y - real_10Y | +/-15bp |
| A-07b | 5Y breakeven ~ nominal_5Y - real_5Y | +/-15bp |

#### Category 2: Cross-Tool Consistency (8 checks)
Verifies the same metric agrees across different tools:

| Check | Metric | Tools Compared |
|-------|--------|---------------|
| X-01 | VIX | analyze_financial_stress vs. analyze_equity_drivers |
| X-02 | HY OAS (pct) | analyze_bond_market vs. analyze_equity_drivers |
| X-03 | Real yield 10Y | analyze_equity_drivers vs. analyze_bond_market |
| X-04 | Fed funds rate | analyze_macro_regime vs. analyze_bond_market |
| X-05 | Nominal 10Y | yield_curve vs. term_premium (within bond_market) |
| X-06 | Credit spread direction | bond_market.signals vs. equity_drivers.signals |
| X-07 | Mortgage rate | analyze_macro_regime vs. analyze_housing_market |
| X-08 | Credit classification | Consistent label across all tools that classify credit |

#### Category 3: Composite Score Decomposition (4 checks)
Verifies that composite scores are the weighted average of their components:

| Check | Score | How Verified |
|-------|-------|-------------|
| S-01 | Financial stress (3.9) | Recompute: sum(component_value x component_weight) / sum(available_weights) |
| S-02 | Consumer health (3.13) | Same weighted-average decomposition |
| S-03 | Late-cycle count (3) | Count signals that are actually firing in the output |
| S-04 | Scan flagged_count | Count length of flagged_indicators list |

#### Category 4: Flag Alignment (~19 checks, varies)
Verifies that flags/thresholds match the underlying data:

- **F-01**: Threshold flags — e.g., `OIL_ELEVATED` should only fire if crude_oil > known threshold. Checks named flags against actual latest values.
- **F-02**: 52-week proximity flags — e.g., `NEAR_52W_LOW` with reference value. Checks the current value is within 5% of it.
- **F-03**: Implausible percentage moves — Flags any daily move > +/-50% or monthly move > +/-100% as suspicious.

#### Category 5: Range Plausibility (16 checks)
Verifies metrics fall within historically possible bounds:

```python
PLAUSIBLE_RANGES = {
    "vix": (8, 90),           "fed_funds_rate": (0, 7),
    "cpi_yoy_pct": (-3, 15),  "unemployment_pct": (2, 15),
    "hy_oas_bps": (200, 2500), "ig_oas_bps": (40, 600),
    "real_yield_10y": (-2, 5), "stress_score": (0, 10),
    "consumer_health_score": (0, 10), "late_cycle_count": (0, 13),
    "mortgage_rate": (2, 10),  "housing_starts_k": (400, 2500),
    "existing_sales": (1e6, 8e6), "ism_pmi": (30, 70),
    "savings_rate": (0, 35),   "breakeven_inflation": (0, 5),
}
```

#### Category 6: Internal Contradictions (5-7 checks, some conditional)
Checks for logically impossible combinations within a single tool's output:

| Check | What's Contradictory | Why It's Impossible |
|-------|---------------------|-------------------|
| I-01 | BREAKEVEN_RISING + BREAKEVEN_FALLING simultaneously | Mutually exclusive directions |
| I-02 | CREDIT_LOOSE signal + credit regime "tight" | Same tool says opposite things |
| I-03 | CREDIT_TAILWIND signal + HY OAS > 300bps | Tailwind implies tightening; 300+ is wide |
| I-04 | SALES_PLUNGING + leading indicator NO_WARNING | Plunging sales IS a warning |
| I-05 | Consumer health label vs. numeric score | "stable" requires score 5-7; actual is 3.13 |
| I-06 | Stress level label vs. numeric score | Same pattern as I-05 |
| I-07 | Housing phase "mixed" + multiple distress signals | Should be "declining"/"distressed" |

Note: I-02 and I-03 are **conditional checks** — they only run if the contradictory signals exist. I-04 is conditional on leading indicator being NO_WARNING.

#### Category 7: Temporal Consistency (2 checks)
- T-01: All tools report the same date/timestamp.
- T-02: Fewer than 3 "data_unavailable" or null fields (more indicates data pipeline issues).

**How to interpret results**: Results are grouped by category. 100% pass rate in a category means that layer is clean. Failures include check_id, expected vs. actual, and a detail string explaining the issue. Severity (critical/high/medium/low) indicates impact.

**When this test will pass completely**: When arithmetic identities hold (they already do), cross-tool values agree (they already do), no impossible percentage moves exist, no contradictory signal pairs fire, and all labels match their numeric scores.

---

## Detailed Findings (v3)

### 1. What Works Well (maintained across all versions, plus new fixes)

| Finding | Evidence | Approaches |
|---------|----------|------------|
| **Arithmetic is perfect** | All 10 arithmetic identities verified (2s10s spread, breakeven, term premium, OAS conversion, permits ratio, monthly payment) | #6 |
| **Cross-tool consistency** | VIX, HY OAS, real yields, fed funds, mortgage rate, credit spreads — identical values across all 8 tools | #6 |
| **Composite scores decompose correctly** | Stress 3.9, consumer health 3.13, late-cycle count 3, scan flagged count — all verify against components | #6 |
| **Range plausibility** | All 16 key metrics within historical bounds (VIX 24.6, Fed funds 3.64%, CPI 2.83%, etc.) | #6 |
| **Credit classification fixed (v2)** | CREDIT_TIGHT signal fires. Regime "elevated". Bond interp "above average — watchful (73th pctile)". | #2, #3, #6 |
| **Breakeven signals fixed (v3)** | BREAKEVEN_FALLING replaced with BREAKEVEN_MIXED. No more contradictory directions. | #6 |
| **Housing leading indicator improved (v3)** | NO_WARNING escalated to HOUSING_CAUTION with explanatory interpretation. | #6 |
| **90.9% coherence** | 10 of 11 cross-section consistency rules pass | #2 |

### 2. Remaining High-Severity Logic Errors

#### BUG-3 residual: Implausible Market Cap Monthly Move
**Severity**: HIGH | **Detected by**: Approach #6 F-03

The `market_cap` indicator shows +108.74% monthly move. Total market cap cannot more than double in a month. The daily move has improved (now 8.57%, down from prior extreme values), but the monthly aggregation is still producing implausible numbers.

**What the test expects**: Monthly percentage move < +/-100%. Add bounds-checking in the scan pipeline to cap or null-out implausible moves.

**Progress**: The `marketcap_to_gdp` daily extreme (-99.86%) has been resolved. Daily `market_cap` moves are now reasonable (8.57%). Only the monthly aggregation for `market_cap` remains problematic.

#### BUG-4: Consumer Health "stable" at Score 3.13 (UNCHANGED across v1-v3)
**Severity**: HIGH | **Detected by**: Approaches #3, #6 I-05

Consumer health score of 3.13/10 is still labeled "stable." A score of 3.13/10 maps to "stressed" (stable = 5-7).

**What the test expects**: `consumer_health_level` must correspond to `composite_score`: critical=(0-3), stressed=(3-5), stable=(5-7), healthy=(7-10). Score 3.13 should produce label "stressed".

**Fix location**: Find the `consumer_health_level` assignment in `tools/consumer_housing_analysis.py`. The threshold boundaries likely have an off-by-one or inverted range. This is a one-line fix.

#### BUG-5 residual: Housing Cycle Phase "mixed" with Distress Signals
**Severity**: MEDIUM | **Detected by**: Approach #6 I-07

Three distress signals fire simultaneously (`SALES_PLUNGING`, `EXISTING_SALES_PLUNGING`, `AFFORDABILITY_STRESSED`) but the `housing_cycle_phase` is still labeled "mixed" with interpretation "Housing signals mixed — no clear directional trend."

**What the test expects**: If >= 2 distress signals fire, `housing_cycle_phase.phase` should be "declining" or "distressed", not "mixed."

**Progress**: The leading indicator was fixed (NO_WARNING → HOUSING_CAUTION), so I-04 now passes. The cycle phase classification logic still needs updating.

#### BUG-6: Recessionary Regime + Moderate Stress (UNCHANGED since v2)
**Severity**: HIGH | **Detected by**: Approach #2 C-01b

The macro regime says "Recessionary" but the financial stress score is only 3.9/10 ("moderate"). The coherence rule expects recessionary regimes to show stress > 4.0.

**What the test expects**: Either (a) stress score >= 4.0 for a recessionary regime (check if stress components are underweighted or if yield curve component is null), or (b) the narrative should reconcile the disconnect (e.g., "Recessionary with moderate stress — stress may lag as credit conditions haven't fully tightened yet").

**Note**: This is a borderline case (3.9 vs. 4.0). It may resolve naturally if missing data components (e.g., yield curve stress) get populated.

### 3. Analytical Quality (UNCHANGED)

**LLM Judge v3 Score**: 3.4/10 (was 3.35 in v1, 3.3 in v2 — all within LLM variance)

| Dimension | v1 | v2 | v3 | v2→v3 |
|-----------|----|----|----|----|
| Data Accuracy & Traceability | 4 | 4 | 3 | -1 |
| Analytical Depth | 3 | 3 | 4 | +1 |
| Internal Coherence | 3 | 4 | 3 | -1 |
| Actionability | 2 | 2 | 2 | — |
| Completeness & Risk Assessment | 4 | 3 | 4 | +1 |
| Professional Quality | 6 | 5 | 6 | +1 |
| Signal Specificity & Originality | 3 | 3 | 3 | — |

All dimension changes are within normal LLM judge variance (+/-1). The weighted score has remained flat at 3.3-3.4/10 across all three versions because no narrative quality improvements have been made. The bug fixes (credit, breakeven, housing) improve correctness but don't change the fundamental issue: the agent describes conditions without explaining causality or providing investment implications.

**The LLM judge's top 3 improvement areas (v3)**:
1. Add explicit investment implications and recommendations
2. Resolve internal contradictions (recessionary macro vs. normal yield curve, late-cycle vs. confidence level)
3. Explain WHY not just WHAT — causal mechanisms, second-order effects, historical precedents

### 4. Data Availability Gaps

7 fields returned "data_unavailable" or null (stable across v2-v3):
- `analyze_macro_regime/regimes.housing.classification`
- `analyze_macro_regime/regimes.housing.evidence`
- `analyze_equity_drivers/equity_risk_premium`
- `analyze_equity_drivers/erp_pct=null`
- `analyze_consumer_health/components.credit_growth_velocity.value=null`

---

## Cross-Approach Convergence Map (v3)

```
Credit Spread Classification (313bps) — RESOLVED in v2
├── Approach #2: C-02 PASSES (since v2)
├── Approach #3: 1 false positive remains ("accommodative" = Fed policy, not credit — test issue)
├── Approach #4: Coherence dimension fluctuates 3-4 (LLM variance)
└── Approach #6: I-02, I-03 PASS (since v2)

Breakeven Signals — RESOLVED in v3
└── Approach #6: I-01 PASSES (BREAKEVEN_FALLING → BREAKEVEN_MIXED)

Housing Leading Indicator — PARTIALLY RESOLVED in v3
├── Approach #6: I-04 PASSES (NO_WARNING → HOUSING_CAUTION)
└── Approach #6: I-07 STILL FAILS (cycle phase "mixed" with 3 distress signals)

Consumer Health Mislabel (3.13 = "stable") — UNCHANGED
├── Approach #3: 1 ungrounded claim
└── Approach #6: I-05 label-vs-score mismatch

Regime-Stress Tension (Recessionary + stress 3.9) — UNCHANGED since v2
└── Approach #2: C-01b (stress 3.9 < 4.0 threshold for recessionary regime)

Market Cap Data Quality — PARTIALLY RESOLVED in v3
├── Approach #6: F-03b PASSES (marketcap_to_gdp daily extreme fixed)
└── Approach #6: F-03 STILL FAILS (market_cap +108.74% monthly)

Analytical Quality — UNCHANGED
├── Approach #4: 3.4/10 (Actionability still 2/10)
└── No causal reasoning, no recommendations added across any version
```

---

## Scorecard Summary (v3)

### By Severity

| Severity | Count | Issues |
|----------|-------|--------|
| HIGH | 3 | Market cap monthly move (BUG-3r), consumer health label (BUG-4), regime-stress coherence (BUG-6) |
| MEDIUM | 3 | Housing phase "mixed" with distress (BUG-5r), date inconsistency (T-01), 7 unavailable data fields (T-02) |
| RESOLVED | 6 | Credit classification (v2), breakeven signals (v3), market cap daily (v3), housing leading indicator (v3), CREDIT_LOOSE (v2), CREDIT_TAILWIND (v2) |

### Progress Tracking

| Metric | v1 | v2 | v3 | Target |
|--------|----|----|----|----|
| Coherence rate | 90.9% | 90.9% | 90.9% | 100% |
| Grounding rate | 40.0% | 66.7% | 66.7% | >80% |
| Data accuracy rate | 87.1% | 89.9% | 92.2% | >95% |
| LLM judge score | 3.35/10 | 3.3/10 | 3.4/10 | >5.0/10 |
| Critical failures | 3 | 2 | 0 | 0 |
| High failures | 4 | 4 | 3 | 0 |
| Total failures | 9 | 7 | 5 | <=2 |

**Notable**: Critical failures have reached 0 for the first time. The breakeven and credit signal contradictions — both critical — are now resolved. Remaining issues are high/medium severity.

---

## Approach Status & What's Next

| Approach | Status | Next Action |
|----------|--------|-------------|
| #2 Coherence | v3 Complete (11 rules) | Address C-01b (regime-stress). Consider if 4.0 threshold is too strict or if stress model needs yield curve component. |
| #3 Grounding | v3 Complete (6 claims) | Fix consumer health label to resolve 1 failure. Bond "accommodative" is a test false positive — consider excluding Fed policy context. |
| #4 LLM Judge | v3 Complete (7 dimensions) | No improvement until narrative quality is enhanced. Re-run after narrative generation upgrade. |
| #5 Backtesting | 3 snapshots taken (19 signals each) | Verify at +1w (Mar 18), +4w (Apr 8), +12w (Jun 3) |
| #6 Data Accuracy | v3 Complete (64 checks) | Fix remaining 5 failures: market cap monthly, consumer health label, housing phase, temporal issues. |

---

## Files & Records

```
taste/
├── taste_evaluation_report.md                            <- This file
├── approach_2_coherence/
│   ├── coherence_checker.py                              (11 rules)
│   ├── records/coherence_20260311_163012.{json,md}       (v1 baseline)
│   ├── records/coherence_20260311_223848.{json,md}       (v2 first fix)
│   └── records/coherence_20260312_014255.{json,md}       (v3 second fix)
├── approach_3_grounding/
│   ├── grounding_evaluator.py
│   ├── records/grounding_20260311_163013.{json,md}       (v1 baseline)
│   ├── records/grounding_20260311_223849.{json,md}       (v2 first fix)
│   └── records/grounding_20260312_014300.{json,md}       (v3 second fix)
├── approach_4_comparative/
│   ├── comparative_benchmark.py                          (LLM-as-Judge)
│   ├── reference_reports/
│   ├── records/benchmark_20260311_163218.{json,md}       (v1 baseline)
│   ├── records/benchmark_20260311_224002.{json,md}       (v2 first fix)
│   └── records/benchmark_20260312_014356.{json,md}       (v3 second fix)
├── approach_5_backtesting/
│   ├── signal_tracker.py                                 (snapshot + verify)
│   ├── records/snapshots/snapshot_20260311_163013.json    (v1 snapshot)
│   ├── records/snapshots/snapshot_20260311_224002.json    (v2 snapshot)
│   └── records/snapshots/snapshot_20260312_014359.json    (v3 snapshot)
└── approach_6_data_accuracy/
    ├── data_accuracy_checker.py                          (7 categories)
    ├── records/data_accuracy_20260311_165224.{json,md}    (v1 baseline)
    ├── records/data_accuracy_20260311_223849.{json,md}    (v2 first fix)
    └── records/data_accuracy_20260312_014303.{json,md}    (v3 second fix)
```

---

## Sample Prompt for Financial Agent Iteration

The following prompt is designed to be given to an agent working on the Financial Agent codebase. It provides the context needed to understand, reproduce, and fix the remaining issues. Copy and adapt as needed.

---

### Prompt

```
You are working on the Financial Agent codebase. A taste evaluation (v3, second post-fix)
has been run against the /full_report pipeline output. The evaluation report is at:
  Testing_Agent/taste/taste_evaluation_report.md

Read the "How Testing Is Conducted" section to understand exactly what each approach
checks and why failures occur.

## PROGRESS ACROSS 3 ITERATIONS

v1 → v2: Fixed BUG-1 (credit spread classification — CREDIT_LOOSE/TAILWIND removed,
          CREDIT_TIGHT added, regime "elevated", interpretations corrected)
v2 → v3: Fixed BUG-2 (breakeven FALLING → MIXED), partially fixed BUG-3 (market cap
          daily extreme resolved), partially fixed BUG-5 (housing NO_WARNING → CAUTION)

Current scores: Coherence 90.9%, Grounding 66.7%, Data Accuracy 92.2%, LLM Judge 3.4/10
Critical failures: 0 (down from 3 in v1). High failures: 3.

## REMAINING BUGS TO FIX (4 items)

### BUG-3 residual: market_cap +108.74% monthly move (HIGH)
- The market_cap indicator still shows a +108.74% monthly move in flagged_indicators.
- Daily moves are now reasonable (8.57%), so the daily guard is working.
- The monthly aggregation needs the same guard.
- Fix: In the scan pipeline, apply the same bounds-check to monthly_pct:
  if abs(monthly_pct) > 100: set monthly_pct = None
- Search: _safe_pct() or monthly percentage calculation in tools/macro_data.py or
  tools/fred_data.py. Look for where monthly_pct is computed for the market_cap
  indicator.

### BUG-4: Consumer health "stable" at score 3.13 (HIGH)
- Score 3.13/10 should map to "stressed" (stable = 5-7 range)
- This has been unfixed across ALL THREE iterations — it is the oldest remaining bug.
- Fix: Find the consumer_health_level assignment in tools/consumer_housing_analysis.py
- Expected thresholds: critical=(0,3), stressed=(3,5), stable=(5,7), healthy=(7,10)
- Score 3.13 → "stressed"
- This is likely a one-line threshold fix.

### BUG-5 residual: Housing cycle phase "mixed" with distress (MEDIUM)
- 3 distress signals fire: SALES_PLUNGING, EXISTING_SALES_PLUNGING, AFFORDABILITY_STRESSED
- housing_cycle_phase = {"phase": "mixed", "interpretation": "Housing signals mixed —
  no clear directional trend"}
- The leading indicator was correctly fixed to HOUSING_CAUTION, but the cycle phase
  classification still doesn't account for multiple simultaneous distress signals.
- Fix: In the cycle_phase determination logic, if >= 2 distress signals are firing,
  set phase = "declining" (or "distressed" if >= 3).
- Search: housing_cycle_phase assignment in tools/consumer_housing_analysis.py

### BUG-6: Recessionary regime + moderate stress 3.9 (HIGH)
- Macro says "Recessionary" but stress is only 3.9/10 (rule expects > 4.0)
- 3.9 is barely below the threshold — this may be a data completeness issue.
- Check: Is the yield curve stress component null/zero? If so, populating it may push
  the score above 4.0 naturally.
- Alternative: Add a narrative caveat when recession is detected with moderate stress:
  "Recessionary conditions with below-expected stress — stress may lag as credit defaults
  haven't materialized yet."
- Search: stress component weights and yield_curve contribution in
  tools/market_regime_enhanced.py, analyze_financial_stress function

## ANALYTICAL QUALITY (after bugs fixed)

LLM judge: 3.4/10 across all 3 versions — no narrative improvements have been made.

The top 3 improvements (in order of impact on score):

1. **Actionability (2/10)**: Add investment implications to each tool's output.
   Examples:
   - "Given ISM contraction and tight credit, favor defensive sectors (utilities,
     healthcare) over cyclicals."
   - "Real yields at 1.8% support short-duration positioning."
   - "Elevated VIX (24.6) with plunging housing suggests hedging via put spreads
     on XHB/ITB."

2. **Analytical depth (3-4/10)**: Add causal explanations. Examples:
   - Instead of "Inflation is cooling": "Inflation cooling (CPI 2.83%) driven by
     goods deflation as supply chains normalize, while services remain sticky."
   - Instead of "ISM contraction": "ISM at 49.12 marks continued contraction,
     reflecting order book weakness as rate-sensitive sectors pull back."

3. **Coherence (3-4/10)**: Reconcile contradictions explicitly. Example:
   - "Regime: Recessionary. However, financial stress remains moderate (3.9/10)
     — this disconnect suggests EARLY recession where credit defaults haven't
     materialized yet. Watch for stress acceleration in coming weeks."
   - "Yield curve shows normal shape (no inversion) despite recessionary conditions
     — this reflects Fed easing expectations priced into the long end."

## HOW TO VERIFY FIXES

After changes, run the evaluation suite:

    cd Testing_Agent/taste

    # Approach 2: Coherence (target: 11/11 pass, 0 contradictions)
    python approach_2_coherence/coherence_checker.py --input <your_output.json>

    # Approach 3: Grounding (target: >80% grounding rate)
    python approach_3_grounding/grounding_evaluator.py --input <your_output.json>

    # Approach 6: Data accuracy (target: >95% accuracy, 0 high/critical failures)
    python approach_6_data_accuracy/data_accuracy_checker.py --input <your_output.json>

    # Approach 4: LLM judge (target: >5.0/10 weighted score)
    python approach_4_comparative/comparative_benchmark.py --solo --input <your_output.json>

Expected results after fixing all 4 remaining bugs:
- Approach #2: 11/11 pass (100%). C-01b resolves with stress or narrative fix.
- Approach #3: 5/6 or 6/6 grounded (83-100%). Consumer health fix eliminates 1 failure.
- Approach #6: 60/64 or better (94%+). Consumer health, housing phase, market cap monthly
  fixes eliminate 3 failures. Only temporal issues (T-01, T-02) may remain.
- Approach #4: Improvement only with narrative quality work (items 1-3 above).

## PRIORITY ORDER

1. Fix BUG-4 (consumer health label) — quickest fix, one threshold boundary, unfixed for
   3 iterations. Should take minutes.
2. Fix BUG-5r (housing cycle phase) — logic fix in cycle phase determination.
3. Fix BUG-3r (market cap monthly guard) — add bounds-check to monthly_pct calculation.
4. Address BUG-6 (regime-stress coherence) — check yield curve component, add narrative.
5. Add analytical quality improvements — largest effort, biggest quality lift, path from
   3.4/10 to 5.0+/10.
```

---

## Bottom Line

### v3 Progress

The second round of fixes addressed **3 of 5 remaining bugs** (2 fully, 1 partially):
- Breakeven contradiction fully resolved (BREAKEVEN_MIXED replaces conflicting signals)
- Market cap daily extremes fixed (marketcap_to_gdp no longer shows -99.86% daily)
- Housing leading indicator improved (NO_WARNING escalated to HOUSING_CAUTION)

**Critical failures have reached zero** for the first time. The remaining issues are all high/medium severity.

### v1 → v3 Trajectory

| Iteration | Fixes Applied | Critical | High | Total Failures | Data Accuracy |
|-----------|--------------|----------|------|----------------|---------------|
| v1 (baseline) | — | 3 | 4 | 9 | 87.1% |
| v2 (first fix) | Credit classification | 2 | 4 | 7 | 89.9% |
| v3 (second fix) | Breakeven, market cap daily, housing leading | 0 | 3 | 5 | 92.2% |
| Target | All bugs + narrative | 0 | 0 | <=2 | >95% |

### Current Assessment

The agent is converging on data correctness. Each iteration resolves 2-3 issues and the trajectory is positive. The most stubborn bug is **BUG-4 (consumer health "stable" at 3.13)** — it has survived all three iterations despite being a simple threshold fix. It should be prioritized first in the next round.

The largest remaining gap is **analytical quality** (3.4/10 LLM judge). This won't improve until the agent generates causal explanations, reconciles contradictions in its narratives, and provides actionable investment implications. This is a fundamentally different class of work from bug fixing — it requires upgrading the narrative generation from template lookups to contextual reasoning.

### Remaining Fix Priority
1. **Fix consumer health label** (one-line threshold — has been unfixed for 3 iterations)
2. **Fix housing cycle phase** (logic update for distress signal counting)
3. **Fix market cap monthly guard** (bounds-check on monthly_pct)
4. **Address regime-stress coherence** (model or narrative adjustment)
5. **Upgrade narrative generation** (biggest lift — the path from 3.4/10 to 5.0+/10)
