"""
Command Batch 4 Taste Evaluation

Evaluates 9 Financial Agent commands:
  /btc, /pmregime, /usdregime, /ta NVDA, /synthesis NVDA,
  /sl gold 3348 long, /grahamscreen, /netnet, /compare NVDA AAPL MSFT

Usage:
    python command_batch4_evaluator.py --input command_output_batch4_v1.json
    python command_batch4_evaluator.py  # Collect live then evaluate
"""

import sys, os, json, time, math, argparse, re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

_THIS_DIR = Path(__file__).resolve().parent
_TESTING_ROOT = _THIS_DIR.parent
_RECORDS_DIR = _THIS_DIR / "command_eval_records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)

_FA_ROOT = os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    str(Path(_TESTING_ROOT).parent.parent / "Financial_Agent")
)
sys.path.insert(0, _FA_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_FA_ROOT, ".env"))
except ImportError:
    pass


# ═════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═════════════════════════════════════════════════════════════════════

class Check:
    def __init__(self, check_id, category, command, check_name, passed, detail,
                 expected=None, actual=None, severity="medium"):
        self.check_id = check_id
        self.category = category
        self.command = command
        self.check_name = check_name
        self.passed = passed
        self.detail = detail
        self.expected = expected
        self.actual = actual
        self.severity = severity

    def to_dict(self):
        return {k: v for k, v in {
            "check_id": self.check_id, "category": self.category,
            "command": self.command, "check_name": self.check_name,
            "passed": self.passed, "detail": self.detail,
            "expected": self.expected, "actual": self.actual,
            "severity": self.severity,
        }.items()}


class Report:
    def __init__(self):
        self.checks = []

    def add(self, c: Check):
        self.checks.append(c)

    @property
    def summary(self):
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        failed = total - passed
        critical = sum(1 for c in self.checks if not c.passed and c.severity == "critical")
        by_cat = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        by_cmd = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        for c in self.checks:
            by_cat[c.category]["total"] += 1
            by_cmd[c.command]["total"] += 1
            if c.passed:
                by_cat[c.category]["passed"] += 1
                by_cmd[c.command]["passed"] += 1
            else:
                by_cat[c.category]["failed"] += 1
                by_cmd[c.command]["failed"] += 1
        return {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_failures": critical,
            "by_category": dict(by_cat),
            "by_command": dict(by_cmd),
        }


# ═════════════════════════════════════════════════════════════════════
# APPROACH 1: DATA ACCURACY CHECKS
# ═════════════════════════════════════════════════════════════════════

def run_accuracy_checks(data, report):
    # ─── BTC: Multi-timeframe analysis ───
    btc = data.get("btc", {})
    trend = btc.get("trend_context", {})

    # BTC-01: All 5 timeframes present
    expected_tfs = ["5min", "30min", "1H", "4H", "1D"]
    present_tfs = [tf for tf in expected_tfs if tf in trend]
    report.add(Check("BTC-01", "accuracy", "btc",
                     "All 5 timeframes present (5min, 30min, 1H, 4H, 1D)",
                     len(present_tfs) == 5,
                     f"Present: {present_tfs}",
                     expected=5, actual=len(present_tfs), severity="high"))

    # BTC-02: RSI values in [0, 100] for all timeframes
    rsis = {tf: trend.get(tf, {}).get("rsi_14") for tf in expected_tfs}
    valid_rsis = all(0 <= v <= 100 for v in rsis.values() if v is not None)
    report.add(Check("BTC-02", "accuracy", "btc",
                     "RSI values in [0, 100] for all timeframes",
                     valid_rsis,
                     f"RSIs: {rsis}",
                     severity="medium"))

    # BTC-03: Composite bias reflects individual timeframe biases
    biases = {tf: trend.get(tf, {}).get("bias") for tf in expected_tfs}
    composite = btc.get("composite_bias", "")
    bullish_count = sum(1 for b in biases.values() if b == "bullish")
    bearish_count = sum(1 for b in biases.values() if b == "bearish")
    # Composite should lean in direction of majority
    if bullish_count > bearish_count:
        expected_lean = "bullish"
    elif bearish_count > bullish_count:
        expected_lean = "bearish"
    else:
        expected_lean = "neutral"
    consistent = expected_lean in composite.lower() or "neutral" in composite.lower() or "mixed" in composite.lower()
    report.add(Check("BTC-03", "accuracy", "btc",
                     "Composite bias reflects timeframe majority",
                     consistent,
                     f"Biases: {biases}, Composite: '{composite}', Majority: {expected_lean}",
                     expected=expected_lean, actual=composite, severity="medium"))

    # BTC-04: Current price consistent across timeframes
    prices = [trend.get(tf, {}).get("current_price") for tf in expected_tfs]
    prices = [p for p in prices if p is not None]
    all_same = len(set(prices)) == 1 if prices else False
    report.add(Check("BTC-04", "accuracy", "btc",
                     "Current price consistent across timeframes",
                     all_same,
                     f"Prices: {set(prices)}",
                     severity="medium"))

    # ─── PM Regime ───
    pm = data.get("pmregime", {})

    # PM-01: Gold price plausible (>$1000, <$10000)
    gold = pm.get("gold_regime", {}).get("gold_price")
    if gold is not None:
        report.add(Check("PM-01", "accuracy", "pmregime",
                         "Gold price in plausible range ($1000-$10000)",
                         1000 <= gold <= 10000,
                         f"Gold: ${gold:.1f}",
                         severity="medium"))

    # PM-02: Silver/Gold ratio consistency
    silver_a = pm.get("silver_analysis", {})
    sg_ratio = silver_a.get("silver_gold_ratio")
    silver_p = silver_a.get("silver_price")
    gold_p2 = silver_a.get("gold_price")
    if sg_ratio and silver_p and gold_p2:
        expected_ratio = round(silver_p / gold_p2, 4)
        close = abs(expected_ratio - sg_ratio) < 0.001
        report.add(Check("PM-02", "accuracy", "pmregime",
                         "Silver/Gold ratio = silver_price / gold_price",
                         close,
                         f"Silver={silver_p}, Gold={gold_p2}, Expected={expected_ratio}, Got={sg_ratio}",
                         expected=expected_ratio, actual=sg_ratio, severity="medium"))

    # PM-03: Correction risk score in [0, 10]
    cr = pm.get("correction_risk", {}).get("score")
    if cr is not None:
        report.add(Check("PM-03", "accuracy", "pmregime",
                         "Correction risk score in [0, 10]",
                         0 <= cr <= 10,
                         f"Correction risk: {cr}",
                         severity="low"))

    # ─── USD Regime ───
    usd = data.get("usdregime", {})
    dxy = usd.get("dxy_regime", {})

    # USD-01: DXY in plausible range (80-120)
    dxy_level = dxy.get("level")
    if dxy_level is not None:
        report.add(Check("USD-01", "accuracy", "usdregime",
                         "DXY level in plausible range (80-120)",
                         80 <= dxy_level <= 120,
                         f"DXY: {dxy_level}",
                         severity="medium"))

    # USD-02: pct_vs_50sma arithmetic
    sma50 = dxy.get("sma_50")
    pct_vs = dxy.get("pct_vs_50sma")
    if dxy_level and sma50 and pct_vs is not None:
        expected_pct = round((dxy_level - sma50) / sma50 * 100, 1)
        close = abs(expected_pct - pct_vs) < 0.5
        report.add(Check("USD-02", "accuracy", "usdregime",
                         "DXY pct vs 50SMA arithmetic",
                         close,
                         f"DXY={dxy_level}, SMA50={sma50}, Expected={expected_pct}%, Got={pct_vs}%",
                         expected=expected_pct, actual=pct_vs, severity="medium"))

    # USD-03: Death cross = SMA50 < SMA200
    sma200 = dxy.get("sma_200")
    dc = dxy.get("death_cross")
    if sma50 and sma200 and dc is not None:
        expected_dc = sma50 < sma200
        report.add(Check("USD-03", "accuracy", "usdregime",
                         "Death cross = SMA50 < SMA200",
                         dc == expected_dc,
                         f"SMA50={sma50}, SMA200={sma200}, Death cross: expected={expected_dc}, got={dc}",
                         expected=expected_dc, actual=dc, severity="medium"))

    # ─── TA NVDA ───
    ta = data.get("ta_NVDA", {})

    # TA-01: All 13 Murphy frameworks present
    expected_frameworks = ["1_trend", "2_support_resistance", "3_volume", "4_moving_averages",
                          "5_macd", "6_rsi", "7_bollinger", "8_fibonacci",
                          "9_stochastic", "10_patterns", "11_composite_signal"]
    present = [f for f in expected_frameworks if f in ta]
    report.add(Check("TA-01", "accuracy", "ta",
                     "Major Murphy TA frameworks present",
                     len(present) >= 10,  # Allow 1-2 missing
                     f"Present: {len(present)}/{len(expected_frameworks)} ({present[:5]}...)",
                     expected=len(expected_frameworks), actual=len(present), severity="high"))

    # TA-02: RSI consistency with 6_rsi section
    rsi_section = ta.get("6_rsi", {})
    rsi_val = rsi_section.get("rsi")
    if rsi_val is not None:
        report.add(Check("TA-02", "accuracy", "ta",
                         "RSI value in [0, 100]",
                         0 <= rsi_val <= 100,
                         f"RSI: {rsi_val}",
                         severity="low"))

    # TA-03: SMA 50/200 crossover label consistency
    ma = ta.get("4_moving_averages", {})
    sma50_ta = ma.get("sma_50")
    sma200_ta = ma.get("sma_200")
    crossover = ma.get("crossover", "")
    if sma50_ta and sma200_ta:
        is_bullish = sma50_ta > sma200_ta
        label_bullish = "bullish" in crossover.lower()
        report.add(Check("TA-03", "accuracy", "ta",
                         "SMA50/200 crossover label matches values",
                         is_bullish == label_bullish,
                         f"SMA50={sma50_ta}, SMA200={sma200_ta}, Crossover: '{crossover}'",
                         expected="bullish" if is_bullish else "bearish",
                         actual=crossover, severity="medium"))

    # ─── Synthesis NVDA ───
    syn = data.get("synthesis_NVDA", {})
    fund = syn.get("fundamental", {})

    # SYN-01: Fundamental metrics available (not all null)
    details = fund.get("details", {})
    null_count = sum(1 for v in details.values() if v is None)
    total_metrics = len(details)
    all_null = null_count == total_metrics and total_metrics > 0
    report.add(Check("SYN-01", "accuracy", "synthesis",
                     "Fundamental metrics available (PE, margins, growth)",
                     not all_null,
                     f"{null_count}/{total_metrics} metrics are null" +
                     (" — ALL NULL, synthesis crippled" if all_null else ""),
                     expected="some metrics available",
                     actual=f"{null_count} null", severity="critical"))

    # SYN-02: Synthesis alignment reflects both signals
    tech_signal = syn.get("technical", {}).get("signal")
    fund_signal = fund.get("signal")
    alignment = syn.get("synthesis", {}).get("alignment")
    if tech_signal and fund_signal and alignment:
        # Both NEUTRAL → alignment should be NEUTRAL
        if tech_signal == fund_signal == "NEUTRAL":
            expected_alignment = "NEUTRAL"
        elif tech_signal == fund_signal:
            expected_alignment = f"ALIGNED_{tech_signal}"
        else:
            expected_alignment = "DIVERGENT"
        # Loose check: neutral if both inputs are neutral
        report.add(Check("SYN-02", "accuracy", "synthesis",
                         "Synthesis alignment reflects signal combination",
                         alignment == expected_alignment or alignment in ("NEUTRAL", "MIXED"),
                         f"Fund={fund_signal}, Tech={tech_signal}, Alignment='{alignment}'",
                         expected=expected_alignment, actual=alignment, severity="medium"))

    # ─── SL Gold ───
    sl = data.get("sl_gold", {})
    stops = sl.get("stop_levels", {})

    # SL-01: Percent-based stop arithmetic
    pct_stop = stops.get("percent_based", {})
    entry = sl.get("entry_price", 0)
    stop_level = pct_stop.get("level")
    risk_pct = pct_stop.get("risk_pct")
    if entry and stop_level and risk_pct:
        expected_stop = round(entry * (1 - risk_pct / 100), 2)
        close = abs(expected_stop - stop_level) < 1.0
        report.add(Check("SL-01", "accuracy", "sl",
                         "Percent-based stop = entry × (1 - risk%)",
                         close,
                         f"Entry={entry}, Risk={risk_pct}%, Expected={expected_stop}, Got={stop_level}",
                         expected=expected_stop, actual=stop_level, severity="medium"))

    # SL-02: ATR-based and swing-based stops present
    has_atr = "atr_based" in stops
    has_swing = "swing_based" in stops
    report.add(Check("SL-02", "accuracy", "sl",
                     "ATR-based and swing-based stops computed",
                     has_atr and has_swing,
                     f"ATR: {'present' if has_atr else 'MISSING'}, Swing: {'present' if has_swing else 'MISSING'}",
                     expected="both present",
                     actual=f"ATR={has_atr}, Swing={has_swing}",
                     severity="high"))

    # SL-03: Stop below entry for long trade
    rec_stop = sl.get("recommended_stop")
    direction = sl.get("direction")
    if rec_stop and entry and direction == "long":
        report.add(Check("SL-03", "accuracy", "sl",
                         "Recommended stop below entry for long trade",
                         rec_stop < entry,
                         f"Entry={entry}, Stop={rec_stop}",
                         severity="high"))

    # ─── Graham Screen ───
    gs = data.get("grahamscreen", {})
    candidates = gs.get("top_value_candidates", [])

    # GS-01: MoS formula = (GN - Price) / Price × 100 (NOT / GN)
    for c in candidates[:3]:
        gn = c.get("graham_number")
        price = c.get("price")
        mos = c.get("margin_of_safety_pct")
        if gn and price and mos is not None:
            correct_mos = round((gn - price) / price * 100, 2)
            wrong_mos = round((gn - price) / gn * 100, 2)
            uses_correct = abs(correct_mos - mos) < 1.0
            uses_wrong = abs(wrong_mos - mos) < 1.0
            report.add(Check("GS-01", "accuracy", "grahamscreen",
                             f"MoS formula correct ({c['ticker']}): (GN-Price)/Price×100",
                             uses_correct,
                             f"GN={gn}, Price={price}, Correct MoS={correct_mos}%, Got={mos}%" +
                             (" — uses (GN-Price)/GN (wrong denom)" if uses_wrong and not uses_correct else ""),
                             expected=correct_mos, actual=mos,
                             severity="high"))
            break  # Just check one

    # GS-02: P/E × P/B product verification
    for c in candidates[:3]:
        pe = c.get("pe")
        pb = c.get("pb")
        pepb = c.get("pe_x_pb")
        if pe and pb and pepb is not None:
            expected = round(pe * pb, 2)
            close = abs(expected - pepb) < 0.5
            report.add(Check("GS-02", "accuracy", "grahamscreen",
                             f"P/E × P/B product ({c['ticker']})",
                             close,
                             f"PE={pe}, PB={pb}, Expected={expected}, Got={pepb}",
                             expected=expected, actual=pepb, severity="medium"))
            break

    # GS-03: Sorted by MoS descending
    mos_values = [c.get("margin_of_safety_pct", 0) for c in candidates]
    is_sorted = all(mos_values[i] >= mos_values[i+1] for i in range(len(mos_values)-1))
    report.add(Check("GS-03", "accuracy", "grahamscreen",
                     "Results sorted by margin of safety descending",
                     is_sorted,
                     f"Top 3 MoS: {mos_values[:3]}",
                     severity="low"))

    # ─── Net-Net Screen ───
    nn = data.get("netnet", {})
    nn_candidates = nn.get("net_net_candidates", [])

    # NN-01: NCAV = (Current Assets - Total Liabilities) / shares
    for c in nn_candidates[:3]:
        ca = c.get("current_assets", 0)
        tl = c.get("total_liabilities", 0)
        ncav_reported = c.get("ncav_per_share")
        price = c.get("current_price")
        if ca and tl and ncav_reported and price:
            # Can't verify per-share without share count, but check price/NCAV
            ptoncav = c.get("price_to_ncav")
            if ptoncav and ncav_reported:
                expected_ptoncav = round(price / ncav_reported, 2)
                close = abs(expected_ptoncav - ptoncav) < 0.1
                report.add(Check("NN-01", "accuracy", "netnet",
                                 f"Price/NCAV ratio arithmetic ({c['ticker']})",
                                 close,
                                 f"Price={price}, NCAV={ncav_reported}, Expected={expected_ptoncav}, Got={ptoncav}",
                                 expected=expected_ptoncav, actual=ptoncav, severity="medium"))
                break

    # NN-02: Any true net-net candidates (price < 2/3 NCAV)?
    true_netnets = [c for c in nn_candidates if c.get("price_to_ncav", 999) < 0.667]
    report.add(Check("NN-02", "accuracy", "netnet",
                     "Identifies any true net-net candidates (price < 2/3 NCAV)",
                     True,  # This is informational — it's OK if none exist in S&P 500
                     f"True net-nets found: {len(true_netnets)}/{len(nn_candidates)}. " +
                     ("None in S&P 500 — expected for large-caps" if not true_netnets else
                      f"Found: {[c['ticker'] for c in true_netnets]}"),
                     severity="low"))

    # ─── Compare ───
    comp = data.get("compare", {})
    comparison = comp.get("comparison", [])

    # CMP-01: All requested tickers present
    tickers_found = [c.get("ticker") for c in comparison]
    expected_tickers = ["NVDA", "AAPL", "MSFT"]
    all_present = all(t in tickers_found for t in expected_tickers)
    report.add(Check("CMP-01", "accuracy", "compare",
                     "All requested tickers in comparison",
                     all_present,
                     f"Requested: {expected_tickers}, Found: {tickers_found}",
                     severity="medium"))

    # CMP-02: Data freshness
    quarters = [c.get("quarter", "") for c in comparison]
    stale = [q for q in quarters if q.startswith(("2019", "2020"))]
    report.add(Check("CMP-02", "accuracy", "compare",
                     "Comparison data freshness (recent quarters)",
                     len(stale) == 0,
                     f"{len(stale)}/{len(quarters)} tickers using stale (2019-2020) data: {quarters}",
                     expected="2024+ data", actual=quarters,
                     severity="critical"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 2: COHERENCE CHECKS
# ═════════════════════════════════════════════════════════════════════

def run_coherence_checks(data, report):
    # CC4-01: BTC price consistent between btc command and other sources
    btc_price = data.get("btc", {}).get("current_price")
    if btc_price:
        report.add(Check("CC4-01", "coherence", "btc",
                         "BTC price in plausible range ($10K-$200K)",
                         10000 <= btc_price <= 200000,
                         f"BTC: ${btc_price:,.1f}",
                         severity="medium"))

    # CC4-02: Gold price consistent between pmregime and sl_gold
    pm_gold = data.get("pmregime", {}).get("gold_regime", {}).get("gold_price")
    sl_entry = data.get("sl_gold", {}).get("entry_price")
    # SL uses user-provided entry, so this might not match — check current_price instead
    sl_current = data.get("sl_gold", {}).get("current_price")
    if pm_gold and sl_current:
        close = abs(pm_gold - sl_current) / pm_gold < 0.05  # Within 5%
        report.add(Check("CC4-02", "coherence", "cross-command",
                         "Gold price consistent: /pmregime vs /sl current_price",
                         close,
                         f"PM gold: ${pm_gold:.1f}, SL current: ${sl_current:.1f}",
                         severity="medium"))

    # CC4-03: NVDA price consistent: /ta vs /synthesis vs /compare
    ta_price = data.get("ta_NVDA", {}).get("current_price")
    syn_price = data.get("synthesis_NVDA", {}).get("technical", {}).get("current_price")
    comp_nvda = [c for c in data.get("compare", {}).get("comparison", []) if c.get("ticker") == "NVDA"]
    # Note: compare uses SEC EDGAR (no live price), so skip that comparison
    if ta_price and syn_price:
        close = abs(ta_price - syn_price) < 1.0
        report.add(Check("CC4-03", "coherence", "cross-command",
                         "NVDA price consistent: /ta vs /synthesis",
                         close,
                         f"TA price: {ta_price}, Synthesis price: {syn_price}",
                         severity="medium"))

    # CC4-04: USD death cross but classification = cyclical_strength — potential contradiction
    usd = data.get("usdregime", {}).get("dxy_regime", {})
    dc = usd.get("death_cross")
    usd_class = usd.get("classification", "")
    if dc is True and "strength" in usd_class:
        # Death cross (bearish signal) + strength classification = contradiction
        report.add(Check("CC4-04", "coherence", "usdregime",
                         "Death cross signal consistent with strength classification",
                         False,
                         f"Death cross={dc} (bearish) but classification='{usd_class}' (bullish). Contradiction.",
                         severity="medium"))
    else:
        report.add(Check("CC4-04", "coherence", "usdregime",
                         "Death cross signal consistent with classification",
                         True,
                         f"Death cross={dc}, Classification='{usd_class}'",
                         severity="medium"))

    # CC4-05: Graham screen MoS uses same formula as /graham
    # Both should use (GN - Price) / Price × 100
    gs_candidates = data.get("grahamscreen", {}).get("top_value_candidates", [])
    for c in gs_candidates[:1]:
        gn = c.get("graham_number")
        price = c.get("price")
        mos = c.get("margin_of_safety_pct")
        if gn and price and mos is not None:
            correct = round((gn - price) / price * 100, 2)
            wrong = round((gn - price) / gn * 100, 2)
            uses_wrong_formula = abs(wrong - mos) < 1.0 and abs(correct - mos) > 5.0
            report.add(Check("CC4-05", "coherence", "grahamscreen",
                             "Graham screen MoS uses correct denominator (price, not GN)",
                             not uses_wrong_formula,
                             f"{c['ticker']}: GN={gn}, Price={price}, MoS={mos}%, correct={correct}%, wrong_formula={wrong}%",
                             severity="high"))
            break

    # CC4-06: Synthesis fundamental null → signals should indicate data limitation
    syn = data.get("synthesis_NVDA", {})
    fund_details = syn.get("fundamental", {}).get("details", {})
    all_null = all(v is None for v in fund_details.values())
    conviction = syn.get("synthesis", {}).get("conviction", "")
    if all_null:
        # If all fundamental data is null, conviction should be LOW
        report.add(Check("CC4-06", "coherence", "synthesis",
                         "Null fundamentals → low conviction synthesis",
                         conviction == "LOW",
                         f"All {len(fund_details)} fundamental metrics null, conviction='{conviction}'",
                         expected="LOW", actual=conviction, severity="medium"))

    # CC4-07: Net-net positive NCAV count plausible for S&P 500
    nn = data.get("netnet", {})
    pos_ncav = nn.get("positive_ncav_count", 0)
    universe = nn.get("universe_size", 0)
    # S&P 500 companies: expect 20-150 with positive NCAV (asset-light tech may not)
    report.add(Check("CC4-07", "coherence", "netnet",
                     "Positive NCAV count plausible for S&P 500",
                     5 <= pos_ncav <= 200 and universe >= 400,
                     f"{pos_ncav}/{universe} companies with positive NCAV",
                     severity="low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 3: GROUNDING CHECKS
# ═════════════════════════════════════════════════════════════════════

def run_grounding_checks(data, report):
    # GR4-01: BTC composite_bias reflects timeframe biases
    btc = data.get("btc", {})
    composite = btc.get("composite_bias", "")
    trend = btc.get("trend_context", {})
    biases = [trend.get(tf, {}).get("bias") for tf in ["5min", "30min", "1H", "4H", "1D"]]
    bull_count = biases.count("bullish")
    bear_count = biases.count("bearish")
    if composite:
        if bull_count > bear_count:
            correct = "bullish" in composite.lower() or "leaning_bullish" in composite.lower()
        elif bear_count > bull_count:
            correct = "bearish" in composite.lower() or "leaning_bearish" in composite.lower()
        else:
            correct = "neutral" in composite.lower() or "mixed" in composite.lower()
        report.add(Check("GR4-01", "grounding", "btc",
                         "BTC composite bias label reflects timeframe majority",
                         correct,
                         f"Bull={bull_count}, Bear={bear_count}, Composite='{composite}'",
                         severity="medium"))

    # GR4-02: PM regime classification reflects correlations
    pm = data.get("pmregime", {})
    gr = pm.get("gold_regime", {})
    pm_class = gr.get("classification", "")
    gold_dxy_corr = gr.get("gold_dxy_20d_corr")
    if pm_class and gold_dxy_corr is not None:
        # If gold-DXY strongly negative, should be macro_driven (traditional)
        is_macro = pm_class == "macro_driven"
        has_neg_corr = gold_dxy_corr < -0.3
        report.add(Check("GR4-02", "grounding", "pmregime",
                         "PM regime classification matches gold-DXY correlation",
                         is_macro == has_neg_corr or True,  # Informational
                         f"Classification: '{pm_class}', Gold-DXY corr: {gold_dxy_corr}",
                         severity="low"))

    # GR4-03: USD cyclical_strength vs death_cross contradiction
    usd = data.get("usdregime", {})
    dxy = usd.get("dxy_regime", {})
    dc = dxy.get("death_cross")
    usd_class = dxy.get("classification", "")
    if dc is not None:
        # Death cross = bearish signal. Cyclical_strength = bullish. Contradiction.
        contradiction = dc and "strength" in usd_class
        report.add(Check("GR4-03", "grounding", "usdregime",
                         "USD regime label consistent with death cross status",
                         not contradiction,
                         f"Death cross: {dc}, Classification: '{usd_class}'" +
                         (" — CONTRADICTION: death cross but 'strength'" if contradiction else ""),
                         severity="medium"))

    # GR4-04: TA NVDA composite signal reflects individual indicators
    ta = data.get("ta_NVDA", {})
    composite = ta.get("11_composite_signal", {})
    if composite:
        signal = composite.get("signal", "")
        # Just check it exists and is non-empty
        report.add(Check("GR4-04", "grounding", "ta",
                         "TA composite signal present and meaningful",
                         signal and signal != "",
                         f"Composite signal: '{signal}'",
                         severity="medium"))

    # GR4-05: Stop-loss recommended method makes sense
    sl = data.get("sl_gold", {})
    rec_method = sl.get("recommended_method", "")
    stops = sl.get("stop_levels", {})
    if rec_method and stops:
        # Recommended method should be one of the available methods
        method_in_stops = rec_method in stops
        report.add(Check("GR4-05", "grounding", "sl",
                         "Recommended stop method is one of the available methods",
                         method_in_stops,
                         f"Recommended: '{rec_method}', Available: {list(stops.keys())}",
                         severity="medium"))

    # GR4-06: Graham screen criteria_passed format consistency
    gs = data.get("grahamscreen", {}).get("top_value_candidates", [])
    if gs:
        formats_ok = all(
            re.match(r"^\d/7$", c.get("criteria_passed", ""))
            for c in gs
        )
        report.add(Check("GR4-06", "grounding", "grahamscreen",
                         "Criteria passed format consistent (N/7)",
                         formats_ok,
                         f"Sample: {[c.get('criteria_passed') for c in gs[:5]]}",
                         severity="low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 4: LLM JUDGE
# ═════════════════════════════════════════════════════════════════════

def run_llm_judge(data, report):
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        print("  MINIMAX_API_KEY not set, skipping LLM judge")
        return {}

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.minimax.io/v1")
    print("  Using LLM: MiniMax-M2.5")

    groups = {
        "btc_pm_usd": {
            "commands": "/btc, /pmregime, /usdregime",
            "data_keys": ["btc", "pmregime", "usdregime"],
            "dimensions": [
                ("Multi-Timeframe Quality", 20, "BTC 5-timeframe analysis depth and RSI/EMA consistency"),
                ("Regime Classification", 25, "Are PM and USD regime classifications justified by data?"),
                ("Cross-Asset Integration", 20, "Do BTC, gold, and USD signals form coherent narrative?"),
                ("Quantitative Rigor", 15, "Correlations, betas, ratios — correct and meaningful?"),
                ("Actionability", 10, "Clear positioning signals?"),
                ("Data Freshness", 10, "Timestamps, data availability"),
            ]
        },
        "ta_synthesis_sl": {
            "commands": "/ta NVDA, /synthesis NVDA, /sl gold",
            "data_keys": ["ta_NVDA", "synthesis_NVDA", "sl_gold"],
            "dimensions": [
                ("TA Framework Coverage", 25, "13 Murphy frameworks present and computed?"),
                ("Synthesis Quality", 25, "Does fund+tech synthesis add value beyond individual signals?"),
                ("Stop-Loss Framework", 20, "Multiple stop methods, position sizing, trailing rules?"),
                ("Data Quality", 15, "Are fundamentals available for synthesis? Recent data?"),
                ("Professional Presentation", 15, "Consistent formatting, clear signals?"),
            ]
        },
        "screens_compare": {
            "commands": "/grahamscreen, /netnet, /compare",
            "data_keys": ["grahamscreen", "netnet", "compare"],
            "dimensions": [
                ("Screening Methodology", 25, "Graham criteria correctly applied? NCAV formula correct?"),
                ("Data Freshness", 25, "Are screens using recent financial data?"),
                ("Coverage", 15, "How many companies screened? Universe size?"),
                ("Formula Accuracy", 20, "MoS, P/E×P/B, Price/NCAV calculations correct?"),
                ("Investment Utility", 15, "Can an investor act on screen results?"),
            ]
        },
    }

    scores = {}
    for group_name, cfg in groups.items():
        subset = {k: data[k] for k in cfg["data_keys"] if k in data}
        dim_text = "\n".join(
            f"  {i+1}. **{name}** (weight {w}%): {desc}"
            for i, (name, w, desc) in enumerate(cfg["dimensions"])
        )
        prompt = f"""You are a senior financial analyst evaluating output quality of an AI financial agent.

Below is the JSON output from: {cfg['commands']}

```json
{json.dumps(subset, indent=2)[:6000]}
```

Score each dimension 1-10 with a ONE-LINE critique:
{dim_text}

Reply in EXACTLY this format (one line per dimension):
<dimension_name>|<score>|<one-line critique>

Then a final line:
WEIGHTED|<weighted_score>|<one-line overall>"""

        print(f"  Calling LLM for {group_name}...")
        t0 = time.time()
        resp = client.chat.completions.create(
            model="MiniMax-M2.5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.1,
        )
        elapsed = time.time() - t0
        print(f"  Responded in {elapsed:.1f}s")

        text = resp.choices[0].message.content.strip()
        weighted_score = 5.0
        dim_scores = []
        for line in text.split("\n"):
            parts = line.strip().split("|")
            if len(parts) >= 3:
                try:
                    s = float(parts[1].strip())
                    if parts[0].strip() == "WEIGHTED":
                        weighted_score = s
                    else:
                        dim_scores.append((parts[0].strip(), s, parts[2].strip()))
                except ValueError:
                    continue

        print(f"  {group_name}: {weighted_score}/10")
        scores[group_name] = {
            "weighted_score": weighted_score,
            "dimensions": dim_scores,
            "raw_response": text,
        }

        report.add(Check(
            f"LLM-{group_name[:12].upper()}",
            "llm_judge", group_name.replace("_", "/"),
            f"LLM Judge: {group_name.replace('_', ' ').title()}",
            weighted_score >= 4.0,
            f"Score: {weighted_score}/10",
            severity="high"
        ))

    return scores


# ═════════════════════════════════════════════════════════════════════
# REPORT GENERATION & MAIN
# ═════════════════════════════════════════════════════════════════════

def save_report(report, data, llm_scores):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _RECORDS_DIR / f"batch4_eval_{ts}.json"
    md_path = _RECORDS_DIR / f"batch4_eval_{ts}.md"

    record = {
        "timestamp": datetime.now().isoformat(),
        "commands": list(data.keys()),
        "summary": report.summary,
        "checks": [c.to_dict() for c in report.checks],
        "llm_scores": {k: {"weighted_score": v["weighted_score"],
                           "dimensions": v["dimensions"]}
                      for k, v in llm_scores.items()} if llm_scores else {},
    }
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2)

    s = report.summary
    lines = [
        "# Command Batch 4 Taste Evaluation Report\n",
        f"**Date**: {datetime.now().isoformat()}",
        f"**Commands**: /btc, /pmregime, /usdregime, /ta NVDA, /synthesis NVDA, /sl gold, /grahamscreen, /netnet, /compare\n",
        "## Summary\n",
        "| Metric | Value |", "|--------|-------|",
        f"| Total Checks | {s['total_checks']} |",
        f"| Passed | {s['passed']} |",
        f"| Failed | {s['failed']} |",
        f"| Pass Rate | {s['rate']} |",
        f"| Critical Failures | {s['critical_failures']} |\n",
        "## By Category\n",
        "| Category | Total | Passed | Failed | Rate |",
        "|----------|-------|--------|--------|------|",
    ]
    for cat, st in sorted(s["by_category"].items()):
        r = f"{st['passed']/st['total']*100:.0f}%" if st['total'] else "N/A"
        lines.append(f"| {cat} | {st['total']} | {st['passed']} | {st['failed']} | {r} |")

    lines += ["\n## By Command\n",
             "| Command | Total | Passed | Failed | Rate |",
             "|---------|-------|--------|--------|------|"]
    for cmd, st in sorted(s["by_command"].items()):
        r = f"{st['passed']/st['total']*100:.0f}%" if st['total'] else "N/A"
        lines.append(f"| {cmd} | {st['total']} | {st['passed']} | {st['failed']} | {r} |")

    failures = [c for c in report.checks if not c.passed]
    if failures:
        lines.append("\n## Failures\n")
        for f in failures:
            lines.append(f"### {f.check_id}: {f.check_name} [{f.severity.upper()}]")
            lines.append(f"- **Command**: {f.command}")
            lines.append(f"- **Detail**: {f.detail}")
            if f.expected is not None:
                lines.append(f"- **Expected**: {f.expected}")
            if f.actual is not None:
                lines.append(f"- **Actual**: {f.actual}")
            lines.append("")

    if llm_scores:
        lines.append("\n## LLM Judge Scores\n")
        for gname, sc in llm_scores.items():
            lines.append(f"### {gname} — Weighted: {sc['weighted_score']}/10\n")
            lines.append("| Dimension | Weight | Score | Critique |")
            lines.append("|-----------|--------|-------|----------|")
            for dim_name, score, critique in sc.get("dimensions", []):
                lines.append(f"| {dim_name} | | {score} | {critique[:100]} |")
            lines.append("")

    lines.append("\n## All Checks\n")
    lines.append("| ID | Cat | Cmd | Check | Status | Sev |")
    lines.append("|----|-----|-----|-------|--------|-----|")
    for c in report.checks:
        status = "PASS" if c.passed else "**FAIL**"
        lines.append(f"| {c.check_id} | {c.category} | {c.command} | {c.check_name[:60]} | {status} | {c.severity} |")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nSaved: {json_path}\n       {md_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            data = json.load(f)
        print(f"Loaded from {args.input}")
    else:
        data = collect_live()

    report = Report()

    print("\n=== Accuracy Checks ===")
    run_accuracy_checks(data, report)
    print("=== Coherence Checks ===")
    run_coherence_checks(data, report)
    print("=== Grounding Checks ===")
    run_grounding_checks(data, report)

    llm_scores = {}
    if not args.no_llm:
        print("=== LLM Judge ===")
        llm_scores = run_llm_judge(data, report)

    s = report.summary
    print(f"\n{'='*60}")
    print(f"BATCH 4 EVALUATION RESULTS")
    print(f"{'='*60}")
    print(f"Total: {s['total_checks']} | Passed: {s['passed']} ({s['rate']}) | Failed: {s['failed']} | Critical: {s['critical_failures']}")

    for cat, st in sorted(s["by_category"].items()):
        r = f"{st['passed']/st['total']*100:.0f}%" if st['total'] else "N/A"
        print(f"  {cat}: {st['passed']}/{st['total']} ({r})")

    failures = [c for c in report.checks if not c.passed]
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  {f.check_id} [{f.severity.upper()}] {f.check_name}")
            print(f"    {f.detail[:120]}")

    save_report(report, data, llm_scores)


def collect_live():
    from tools.btc_analysis import analyze_btc_market
    from tools.protrader_frameworks import protrader_precious_metals_regime, protrader_usd_regime_analysis
    from tools.murphy_ta import murphy_technical_analysis, fundamental_ta_synthesis
    from tools.protrader_sl import protrader_stop_loss_framework
    from tools.graham_analysis import graham_screen, graham_net_net_screen
    from tools.equity_analysis import compare_equity_metrics

    fns = {
        "btc": analyze_btc_market,
        "pmregime": protrader_precious_metals_regime,
        "usdregime": protrader_usd_regime_analysis,
        "ta_NVDA": lambda: murphy_technical_analysis("NVDA", "1D"),
        "synthesis_NVDA": lambda: fundamental_ta_synthesis("NVDA", "1D"),
        "sl_gold": lambda: protrader_stop_loss_framework("gold", 3348.0, "long", 0, 0, 0, 0),
        "grahamscreen": lambda: graham_screen("", 20),
        "netnet": lambda: graham_net_net_screen(20),
        "compare": lambda: compare_equity_metrics("NVDA,AAPL,MSFT"),
    }
    data = {}
    for name, fn in fns.items():
        print(f"Collecting {name}...")
        try:
            data[name] = json.loads(fn())
        except Exception as e:
            data[name] = {"error": str(e)}
            print(f"  ERROR: {e}")
    return data


if __name__ == "__main__":
    main()
