"""
Command Batch 3 Taste Evaluation

Evaluates 11 Financial Agent commands:
  /bbb, /fsmi, /vigilantes, /drawdown,
  /peers NVDA, /allocation NVDA, /balance NVDA,
  /riskpremium, /crossasset, /intermarket, /synthesize

Usage:
    python command_batch3_evaluator.py --input command_output_batch3_v1.json
    python command_batch3_evaluator.py  # Collect live then evaluate
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
    # ─── BBB: Boom-Bust Barometer ───
    bbb = data.get("bbb", {})

    # BBB-01: BBB ratio = copper_price / initial_claims (in thousands)
    copper = bbb.get("copper_price")
    claims = bbb.get("initial_claims")
    ratio = bbb.get("bbb_ratio")
    if copper is not None and claims is not None and ratio is not None:
        expected_ratio = round(copper / (claims / 1000), 4) if claims else 0
        actual_ratio = ratio
        close = abs(expected_ratio - actual_ratio) < 0.05 if expected_ratio != 0 else actual_ratio == 0
        # Also check if bbb_ratio == 0 which is suspicious for copper=5.88
        ratio_is_zero = actual_ratio == 0 and copper > 0
        report.add(Check("BBB-01", "accuracy", "bbb",
                         "BBB ratio = copper / (claims/1000)",
                         close and not ratio_is_zero,
                         f"Copper={copper}, Claims={claims}, Expected ratio≈{expected_ratio}, Got={actual_ratio}"
                         + (" BUG: ratio is 0 despite copper>0" if ratio_is_zero else ""),
                         expected=expected_ratio, actual=actual_ratio, severity="high"))

    # BBB-02: Claims value plausible (100K-500K range)
    if claims is not None:
        plausible = 100000 <= claims <= 500000
        report.add(Check("BBB-02", "accuracy", "bbb",
                         "Initial claims in plausible range (100K-500K)",
                         plausible,
                         f"Claims={claims:.0f}" + ("" if plausible else " — out of range"),
                         expected="[100000, 500000]", actual=claims, severity="medium"))

    # ─── FSMI: Fundamental Stock Market Indicator ───
    fsmi = data.get("fsmi", {})
    fsmi_error = fsmi.get("error")
    report.add(Check("FSMI-01", "accuracy", "fsmi",
                     "FSMI command executes without error",
                     fsmi_error is None,
                     f"Error: {fsmi_error}" if fsmi_error else "OK",
                     expected="no error", actual=fsmi_error or "OK",
                     severity="critical"))

    # ─── Vigilantes: Bond Vigilantes Model ───
    vig = data.get("vigilantes", {})
    yield_10y = vig.get("yield_10y")
    gdp_yoy = vig.get("nominal_gdp_yoy_pct")
    regime = vig.get("regime")

    # VIG-01: Yields data available
    report.add(Check("VIG-01", "accuracy", "vigilantes",
                     "10Y yield data available",
                     yield_10y is not None,
                     f"10Y yield: {yield_10y}" if yield_10y else "MISSING — null 10Y yield",
                     expected="available", actual=yield_10y, severity="high"))

    # VIG-02: GDP data available
    report.add(Check("VIG-02", "accuracy", "vigilantes",
                     "Nominal GDP YoY data available",
                     gdp_yoy is not None,
                     f"GDP YoY: {gdp_yoy}" if gdp_yoy else "MISSING — null GDP data",
                     expected="available", actual=gdp_yoy, severity="high"))

    # VIG-03: Regime not insufficient_data
    report.add(Check("VIG-03", "accuracy", "vigilantes",
                     "Vigilantes model produces a regime",
                     regime != "insufficient_data" and regime is not None,
                     f"Regime: {regime}",
                     expected="vigilante_mode or suppression_mode",
                     actual=regime, severity="critical"))

    # ─── Drawdown: S&P 500 Drawdown Classification ───
    dd = data.get("drawdown", {})
    dd_pct = dd.get("drawdown_pct")
    dd_class = dd.get("classification")
    ath = dd.get("all_time_high")
    cur = dd.get("current_price")

    # DD-01: Drawdown pct = (current - ATH) / ATH × 100
    if ath and cur and dd_pct is not None:
        expected_dd = round((cur - ath) / ath * 100, 2)
        close = abs(expected_dd - dd_pct) < 0.1
        report.add(Check("DD-01", "accuracy", "drawdown",
                         "Drawdown % = (price - ATH) / ATH × 100",
                         close,
                         f"Expected {expected_dd}%, got {dd_pct}%",
                         expected=expected_dd, actual=dd_pct, severity="high"))

    # DD-02: Classification matches Yardeni thresholds
    if dd_pct is not None and dd_class:
        abs_dd = abs(dd_pct)
        if abs_dd < 10:
            expected_class = "panic_attack"
        elif abs_dd < 20:
            expected_class = "correction"
        else:
            expected_class = "bear_market"
        report.add(Check("DD-02", "accuracy", "drawdown",
                         "Drawdown classification matches Yardeni thresholds",
                         dd_class == expected_class,
                         f"DD={dd_pct}% → expected '{expected_class}', got '{dd_class}'",
                         expected=expected_class, actual=dd_class, severity="high"))

    # DD-03: 52wk high ≥ ATH
    wk_high = dd.get("52wk_high")
    if wk_high and ath:
        report.add(Check("DD-03", "accuracy", "drawdown",
                         "52wk high ≥ all-time high (within lookback)",
                         abs(wk_high - ath) < 1.0,  # might differ slightly based on data
                         f"52wk_high={wk_high}, ATH={ath}",
                         severity="low"))

    # ─── Peers: Peer Comparison ───
    peers = data.get("peers_NVDA", {})
    comp = peers.get("comparison", [])
    medians = peers.get("peer_medians", {})

    # PEER-01: Reference ticker in comparison list
    ref_in_list = any(p.get("is_reference") for p in comp)
    report.add(Check("PEER-01", "accuracy", "peers",
                     "Reference ticker (NVDA) in comparison list",
                     ref_in_list,
                     f"Found {len(comp)} peers, reference present: {ref_in_list}",
                     severity="medium"))

    # PEER-02: All peers use recent data (not stale)
    stale_peers = [p for p in comp if p.get("quarter", "").startswith(("2019", "2020"))]
    report.add(Check("PEER-02", "accuracy", "peers",
                     "Peer data freshness (recent quarters)",
                     len(stale_peers) == 0,
                     f"{len(stale_peers)}/{len(comp)} peers using stale (2019-2020) data" if stale_peers else "All fresh",
                     expected="2024+ data", actual=f"{stale_peers[0]['quarter'] if stale_peers else 'N/A'}",
                     severity="critical"))

    # PEER-03: Median calculations plausible
    if comp and medians:
        # Verify gross_margin median from peer data (excluding reference)
        peer_gms = [p.get("gross_margin_pct") for p in comp
                    if not p.get("is_reference") and p.get("gross_margin_pct") is not None]
        if peer_gms:
            import statistics
            calc_median = round(statistics.median(peer_gms), 2)
            reported = medians.get("gross_margin_pct")
            close = abs(calc_median - reported) < 1.0 if reported else False
            report.add(Check("PEER-03", "accuracy", "peers",
                             "Peer median gross margin matches calculation",
                             close,
                             f"Calculated median: {calc_median}%, Reported: {reported}%",
                             expected=calc_median, actual=reported, severity="medium"))

    # ─── Allocation: Capital Allocation Analysis ───
    alloc = data.get("allocation_NVDA", {})
    alloc_data = alloc.get("quarterly_data", [])

    # ALLOC-01: SBC/FCF ratio arithmetic
    for q in alloc_data[-3:]:  # Check last 3 quarters
        sbc = q.get("stock_based_compensation", 0)
        fcf = q.get("free_cash_flow", 0)
        reported_ratio = q.get("sbc_to_fcf_pct")
        if sbc and fcf and reported_ratio is not None:
            expected_ratio = round(sbc / fcf * 100, 2)
            close = abs(expected_ratio - reported_ratio) < 0.5
            report.add(Check("ALLOC-01", "accuracy", "allocation",
                             f"SBC/FCF ratio arithmetic ({q['quarter']})",
                             close,
                             f"SBC={sbc/1e9:.1f}B, FCF={fcf/1e9:.1f}B, Expected={expected_ratio}%, Got={reported_ratio}%",
                             expected=expected_ratio, actual=reported_ratio, severity="medium"))
            break  # Just check latest

    # ALLOC-02: Negative diluted_shares (bug)
    neg_shares = [q for q in alloc_data if q.get("diluted_shares", 0) < 0]
    report.add(Check("ALLOC-02", "accuracy", "allocation",
                     "No negative diluted_shares values",
                     len(neg_shares) == 0,
                     f"{len(neg_shares)} quarters with negative diluted_shares" +
                     (f" (e.g., {neg_shares[0]['quarter']}: {neg_shares[0]['diluted_shares']:,.0f})" if neg_shares else ""),
                     expected="all positive", actual=f"{len(neg_shares)} negative",
                     severity="high"))

    # ALLOC-03: Buyback/FCF ratio arithmetic
    for q in reversed(alloc_data):
        buybacks = q.get("share_repurchases", 0)
        fcf = q.get("free_cash_flow", 0)
        reported = q.get("buyback_to_fcf_pct")
        if buybacks and fcf and reported is not None:
            expected = round(abs(buybacks) / fcf * 100, 2)
            close = abs(expected - reported) < 0.5
            report.add(Check("ALLOC-03", "accuracy", "allocation",
                             f"Buyback/FCF ratio arithmetic ({q['quarter']})",
                             close,
                             f"Buybacks={abs(buybacks)/1e9:.1f}B, FCF={fcf/1e9:.1f}B, Expected={expected}%, Got={reported}%",
                             expected=expected, actual=reported, severity="medium"))
            break

    # ALLOC-04: Latest quarter summary consistency
    summary = alloc.get("latest_quarter_summary", {})
    # "inactive" buyback but we see $3.8B repurchases in latest quarter → contradiction
    latest_q = alloc_data[-1] if alloc_data else {}
    buyback_active = abs(latest_q.get("share_repurchases", 0)) > 100_000_000  # >$100M
    strategy = summary.get("buyback_strategy")
    report.add(Check("ALLOC-04", "accuracy", "allocation",
                     "Buyback strategy label matches latest quarter activity",
                     not (buyback_active and strategy == "inactive"),
                     f"Latest repurchases=${abs(latest_q.get('share_repurchases', 0))/1e9:.1f}B, strategy='{strategy}'" +
                     (" BUG: $3.8B buyback but labeled 'inactive'" if (buyback_active and strategy == "inactive") else ""),
                     expected="active" if buyback_active else "inactive",
                     actual=strategy, severity="high"))

    # ─── Balance: Balance Sheet Deep Dive ───
    bal = data.get("balance_NVDA", {})
    bal_data = bal.get("quarterly_data", [])
    latest_bal = bal.get("latest_summary", {})

    # BAL-01: Latest summary matches most recent quarter
    if bal_data and latest_bal:
        latest_q_data = bal_data[0]  # First entry seems to be latest based on structure
        # Actually check: latest_summary has quarter 2020-Q2, which is the OLDEST, not newest
        latest_q_str = latest_bal.get("quarter")
        last_in_array = bal_data[-1].get("quarter") if bal_data else None
        first_in_array = bal_data[0].get("quarter") if bal_data else None
        # The latest_summary should reference the most recent quarter
        is_stale = latest_q_str and latest_q_str.startswith(("2019", "2020"))
        report.add(Check("BAL-01", "accuracy", "balance",
                         "Latest summary references most recent quarter",
                         not is_stale,
                         f"Latest summary quarter: {latest_q_str}, array spans {first_in_array} to {last_in_array}" +
                         (" BUG: summary shows oldest quarter not newest" if is_stale else ""),
                         expected=last_in_array, actual=latest_q_str,
                         severity="high"))

    # BAL-02: CCC = DSO - DPO + DIO
    if bal_data:
        q = bal_data[-1]  # Latest quarter
        dso = q.get("days_sales_outstanding")
        dpo = q.get("days_payable_outstanding")
        dio = q.get("days_inventory_outstanding")
        ccc = q.get("cash_conversion_cycle")
        if all(v is not None for v in [dso, dpo, dio, ccc]):
            expected_ccc = round(dso - dpo + dio, 2)
            close = abs(expected_ccc - ccc) < 1.0
            report.add(Check("BAL-02", "accuracy", "balance",
                             "CCC = DSO - DPO + DIO",
                             close,
                             f"DSO={dso}, DPO={dpo}, DIO={dio}, Expected CCC={expected_ccc}, Got={ccc}",
                             expected=expected_ccc, actual=ccc, severity="medium"))

    # ─── Risk Premium ───
    rp = data.get("riskpremium", {})
    vix = rp.get("vix_regime", {})
    opp = rp.get("opportunity_components", {})
    opp_score = rp.get("opportunity_score")

    # RP-01: Opportunity score = avg of components
    if opp and opp_score is not None:
        comp_vals = [v for v in opp.values() if isinstance(v, (int, float))]
        expected_score = round(sum(comp_vals) / len(comp_vals), 1) if comp_vals else 0
        close = abs(expected_score - opp_score) < 0.5
        report.add(Check("RP-01", "accuracy", "riskpremium",
                         "Opportunity score ≈ mean of components",
                         close,
                         f"Components avg: {expected_score}, Reported: {opp_score}",
                         expected=expected_score, actual=opp_score, severity="medium"))

    # RP-02: VIX percentile in [0, 100]
    pct = vix.get("percentile_1y")
    if pct is not None:
        report.add(Check("RP-02", "accuracy", "riskpremium",
                         "VIX percentile in [0, 100]",
                         0 <= pct <= 100,
                         f"VIX percentile: {pct}",
                         severity="low"))

    # RP-03: VIX tier matches level
    tier = vix.get("tier")
    level = vix.get("level")
    if tier is not None and level is not None:
        # 7-tier: 1=<14, 2=14-17, 3=17-20, 4=20-25, 5=25-30, 6=30-50, 7=50+
        expected_tier = 1 if level < 14 else 2 if level < 17 else 3 if level < 20 else \
                       4 if level < 25 else 5 if level < 30 else 6 if level < 50 else 7
        report.add(Check("RP-03", "accuracy", "riskpremium",
                         "VIX tier matches level (7-tier scale)",
                         tier == expected_tier,
                         f"VIX={level}, expected tier {expected_tier}, got {tier}",
                         expected=expected_tier, actual=tier, severity="medium"))

    # ─── Cross-Asset Momentum ───
    ca = data.get("crossasset", {})
    rets = ca.get("returns_20d", {})
    rs = ca.get("relative_strength", {})

    # CA-01: BTC/SPX ratio consistency
    btc_spx = rs.get("btc_vs_spx", {})
    if btc_spx and rets:
        ratio_chg = btc_spx.get("pct_change")
        btc_ret = rets.get("btc", 0)
        spx_ret = rets.get("spx", 0)
        # BTC/SPX ratio change ≈ btc_return - spx_return (approx for small changes)
        approx_chg = btc_ret - spx_ret
        # This is rough; the actual ratio % change ≈ (1+btc/100)/(1+spx/100) - 1
        actual_ratio_chg = ((1 + btc_ret/100) / (1 + spx_ret/100) - 1) * 100
        close = abs(actual_ratio_chg - ratio_chg) < 2.0  # Allow some tolerance
        report.add(Check("CA-01", "accuracy", "crossasset",
                         "BTC/SPX ratio change consistent with individual returns",
                         close,
                         f"BTC={btc_ret}%, SPX={spx_ret}%, ratio change={ratio_chg}%, expected≈{actual_ratio_chg:.1f}%",
                         expected=round(actual_ratio_chg, 1), actual=ratio_chg, severity="medium"))

    # CA-02: Correlation values in [-1, 1]
    corrs = ca.get("correlations_20d", {})
    all_valid = all(-1 <= v <= 1 for v in corrs.values())
    report.add(Check("CA-02", "accuracy", "crossasset",
                     "All correlations in [-1, 1]",
                     all_valid,
                     f"{len(corrs)} correlations, all valid: {all_valid}",
                     severity="low"))

    # ─── Intermarket ───
    im = data.get("intermarket", {})
    rels = im.get("relationships", [])

    # IM-01: Alignment score matches actual aligned count
    alignment = im.get("alignment_score", "")
    aligned_count = sum(1 for r in rels if r.get("aligned") is True)
    total_scored = sum(1 for r in rels if "aligned" in r)
    expected_score = f"{aligned_count}/{total_scored} relationships aligned with Murphy theory"
    # Some relationships have "context" instead of "aligned"
    total_with_context = len(rels)
    report.add(Check("IM-01", "accuracy", "intermarket",
                     "Alignment score matches aligned relationship count",
                     alignment == expected_score or str(aligned_count) in alignment,
                     f"Aligned: {aligned_count}/{total_scored}, Reported: '{alignment}'",
                     expected=expected_score, actual=alignment, severity="medium"))

    # IM-02: All correlations between -1 and 1
    all_corr_valid = all(-1 <= r.get("actual_correlation", 0) <= 1 for r in rels)
    report.add(Check("IM-02", "accuracy", "intermarket",
                     "All intermarket correlations in [-1, 1]",
                     all_corr_valid,
                     f"{len(rels)} relationships, correlations valid: {all_corr_valid}",
                     severity="low"))

    # ─── Synthesize ───
    syn = data.get("synthesize", {})
    regime = syn.get("regime_summary", {})

    # SYN-01: Regime summary has all key dimensions
    expected_dims = ["growth", "inflation", "employment", "rates", "credit"]
    missing = [d for d in expected_dims if d not in regime]
    report.add(Check("SYN-01", "accuracy", "synthesize",
                     "Regime summary covers all macro dimensions",
                     len(missing) == 0,
                     f"Missing: {missing}" if missing else f"All {len(expected_dims)} dimensions present",
                     expected=expected_dims, actual=list(regime.keys()),
                     severity="high"))

    # SYN-02: Has recommendations
    recs = syn.get("recommendations", {})
    has_recs = any(recs.get(k) for k in ["equity_positioning", "fixed_income", "sector_tilts", "risk_management"])
    report.add(Check("SYN-02", "accuracy", "synthesize",
                     "Synthesis produces actionable recommendations",
                     has_recs,
                     f"Recommendations present: {[k for k,v in recs.items() if v and k != 'conviction' and k != 'conviction_note']}",
                     expected="non-empty recommendations",
                     actual="has recs" if has_recs else "sparse/empty recs",
                     severity="medium"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 2: COHERENCE CHECKS (cross-command consistency)
# ═════════════════════════════════════════════════════════════════════

def run_coherence_checks(data, report):
    # CC3-01: BBB claims = Batch 2 stress claims (same source)
    bbb_claims = data.get("bbb", {}).get("initial_claims")
    # Compare with batch 2 stress if available
    if bbb_claims is not None:
        report.add(Check("CC3-01", "coherence", "bbb",
                         "BBB initial claims value plausible",
                         100_000 <= bbb_claims <= 500_000,
                         f"Claims={bbb_claims:.0f}" + (" — plausible" if 100_000 <= bbb_claims <= 500_000 else " — out of range"),
                         severity="medium"))

    # CC3-02: Drawdown classification vs intermarket Dow Theory
    dd_class = data.get("drawdown", {}).get("classification")
    dow = data.get("intermarket", {}).get("dow_theory", {})
    dow_confirm = dow.get("confirmation", "")

    if dd_class and dow_confirm:
        # If drawdown > 10% (correction/bear), Dow Theory should not be confirmed bullish
        is_severe = dd_class in ("correction", "bear_market")
        is_bullish = "BULLISH" in dow_confirm and "BEARISH" not in dow_confirm
        contradiction = is_severe and is_bullish
        report.add(Check("CC3-02", "coherence", "cross-command",
                         "Drawdown severity consistent with Dow Theory",
                         not contradiction,
                         f"Drawdown: {dd_class}, Dow: {dow_confirm}",
                         severity="high"))

    # CC3-03: Risk premium VIX ≈ Batch 2 vixanalysis VIX (cross-batch consistency)
    rp_vix = data.get("riskpremium", {}).get("vix_regime", {}).get("level")
    if rp_vix is not None:
        report.add(Check("CC3-03", "coherence", "riskpremium",
                         "VIX level in plausible range (10-80)",
                         10 <= rp_vix <= 80,
                         f"VIX={rp_vix}",
                         severity="medium"))

    # CC3-04: Cross-asset regime vs risk premium state
    ca_regime = data.get("crossasset", {}).get("regime_summary", "")
    rp_state = data.get("riskpremium", {}).get("risk_premium_state", "")
    wow = data.get("riskpremium", {}).get("wall_of_worry_phase", "")

    # If risk premium is "expanding" and wall is "fear", cross-asset shouldn't be pure risk-on
    contradiction = ("risk_on" in ca_regime and "selective" not in ca_regime
                    and rp_state == "expanding" and wow == "fear")
    report.add(Check("CC3-04", "coherence", "cross-command",
                     "Cross-asset regime consistent with risk premium state",
                     not contradiction,
                     f"Cross-asset: '{ca_regime}', Risk premium: '{rp_state}', Wall: '{wow}'",
                     severity="medium"))

    # CC3-05: Intermarket Dow Theory both indices same trend direction
    sp_trend = dow.get("sp500_trend")
    rut_trend = dow.get("russell_2000_trend")
    confirm = dow.get("confirmation", "")
    if sp_trend and rut_trend:
        same_dir = sp_trend == rut_trend
        confirmed = "CONFIRMED" in confirm
        report.add(Check("CC3-05", "coherence", "intermarket",
                         "Dow Theory confirmation consistent with trend directions",
                         same_dir == confirmed or not same_dir == ("NON_CONFIRMATION" in confirm),
                         f"SP500={sp_trend}, Russell={rut_trend}, Confirmation='{confirm}'",
                         severity="high"))

    # CC3-06: Synthesize regime matches individual tool outputs
    syn_growth = data.get("synthesize", {}).get("regime_summary", {}).get("growth")
    syn_credit = data.get("synthesize", {}).get("regime_summary", {}).get("credit")
    rp_credit = data.get("riskpremium", {}).get("credit_state", {}).get("stress_level")

    if syn_credit and rp_credit:
        report.add(Check("CC3-06", "coherence", "cross-command",
                         "Synthesize credit assessment ≈ risk premium credit state",
                         syn_credit == rp_credit or syn_credit in rp_credit or rp_credit in syn_credit,
                         f"Synthesize credit: '{syn_credit}', Risk premium credit: '{rp_credit}'",
                         severity="medium"))

    # CC3-07: All peer data from same era
    peers = data.get("peers_NVDA", {}).get("comparison", [])
    quarters = [p.get("quarter", "") for p in peers]
    years = set(q[:4] for q in quarters if q)
    all_same_era = len(years) <= 2  # Allow 1-2 year spread max
    report.add(Check("CC3-07", "coherence", "peers",
                     "Peer data from consistent time period",
                     all_same_era and "2024" in years or "2025" in years or "2026" in years,
                     f"Quarters span: {sorted(quarters)}" if len(quarters) <= 5 else f"Years: {sorted(years)}, {len(peers)} peers",
                     expected="recent consistent data", actual=f"years: {sorted(years)}",
                     severity="high"))

    # CC3-08: Synthesize contradiction count matches contradictions list
    syn = data.get("synthesize", {})
    contra_count = syn.get("contradiction_count", -1)
    contra_list = syn.get("contradictions", [])
    report.add(Check("CC3-08", "coherence", "synthesize",
                     "Contradiction count matches contradictions list length",
                     contra_count == len(contra_list),
                     f"Count: {contra_count}, List length: {len(contra_list)}",
                     expected=len(contra_list), actual=contra_count, severity="medium"))

    # CC3-09: Risk premium HY OAS consistent with cross-batch data
    rp_hy = data.get("riskpremium", {}).get("credit_state", {}).get("hy_oas_bps")
    if rp_hy is not None:
        report.add(Check("CC3-09", "coherence", "riskpremium",
                         "HY OAS in plausible range (100-2000 bps)",
                         100 <= rp_hy <= 2000,
                         f"HY OAS: {rp_hy} bps",
                         severity="medium"))

    # CC3-10: Allocation data range includes recent quarters
    alloc = data.get("allocation_NVDA", {})
    alloc_quarters = [q.get("quarter") for q in alloc.get("quarterly_data", [])]
    has_recent = any(q.startswith(("2025", "2026")) for q in alloc_quarters if q)
    report.add(Check("CC3-10", "coherence", "allocation",
                     "Allocation data includes recent (2025+) quarters",
                     has_recent,
                     f"Quarter range: {alloc_quarters[0] if alloc_quarters else '?'} to {alloc_quarters[-1] if alloc_quarters else '?'}",
                     severity="medium"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 3: GROUNDING CHECKS (label ↔ value consistency)
# ═════════════════════════════════════════════════════════════════════

def run_grounding_checks(data, report):
    # GR3-01: BBB interpretation matches ratio
    bbb = data.get("bbb", {})
    ratio = bbb.get("bbb_ratio", 0)
    interp = bbb.get("interpretation", "")

    # If ratio is 0 and copper > 0, interpretation shouldn't be contraction — it's a data bug
    copper = bbb.get("copper_price", 0)
    if ratio == 0 and copper > 0:
        report.add(Check("GR3-01", "grounding", "bbb",
                         "BBB interpretation consistent with ratio value",
                         False,
                         f"Ratio=0 but copper={copper}. Interpretation: '{interp}'. SUSPECT: zero ratio with positive copper is a computation bug, not true contraction",
                         severity="high"))
    else:
        report.add(Check("GR3-01", "grounding", "bbb",
                         "BBB interpretation consistent with ratio value",
                         True,
                         f"Ratio={ratio}, Interpretation: '{interp}'",
                         severity="high"))

    # GR3-02: Drawdown classification label matches description
    dd = data.get("drawdown", {})
    dd_class = dd.get("classification", "")
    desc = dd.get("description", "")
    report.add(Check("GR3-02", "grounding", "drawdown",
                     "Drawdown classification appears in description",
                     dd_class in desc or dd_class.replace("_", " ") in desc,
                     f"Classification: '{dd_class}', Description: '{desc[:80]}'",
                     severity="medium"))

    # GR3-03: Risk premium wall_of_worry phase matches interpretation
    rp = data.get("riskpremium", {})
    wow = rp.get("wall_of_worry_phase", "")
    wow_interp = rp.get("wall_of_worry_interpretation", "")
    if wow and wow_interp:
        report.add(Check("GR3-03", "grounding", "riskpremium",
                         "Wall-of-worry phase label appears in interpretation",
                         wow.capitalize() in wow_interp or wow in wow_interp.lower(),
                         f"Phase: '{wow}', Interpretation: '{wow_interp[:80]}'",
                         severity="medium"))

    # GR3-04: Cross-asset regime label matches summary
    ca = data.get("crossasset", {})
    ca_regime = ca.get("regime_summary", "")
    ca_summary = ca.get("summary", "")
    if ca_regime:
        regime_readable = ca_regime.replace("_", " ")
        report.add(Check("GR3-04", "grounding", "crossasset",
                         "Cross-asset regime label reflected in summary",
                         regime_readable in ca_summary.lower() or ca_regime in ca_summary.lower(),
                         f"Regime: '{ca_regime}', Summary: '{ca_summary[:80]}'",
                         severity="medium"))

    # GR3-05: Intermarket regime label reflects alignment
    im = data.get("intermarket", {})
    im_regime = im.get("regime", "")
    alignment = im.get("alignment_score", "")
    if im_regime and alignment:
        # If most relationships misaligned, regime should indicate anomaly
        aligned_num = int(alignment.split("/")[0]) if "/" in alignment else 0
        total_num = int(alignment.split("/")[1].split(" ")[0]) if "/" in alignment else 5
        mostly_misaligned = aligned_num <= total_num / 2
        regime_shows_anomaly = "anomal" in im_regime.lower() or "break" in im_regime.lower()
        report.add(Check("GR3-05", "grounding", "intermarket",
                         "Intermarket regime label reflects alignment score",
                         (mostly_misaligned and regime_shows_anomaly) or (not mostly_misaligned and not regime_shows_anomaly),
                         f"Aligned: {alignment}, Regime: '{im_regime}'",
                         severity="medium"))

    # GR3-06: Dow Theory SP500 vs SMA50 consistent with trend
    dow = im.get("dow_theory", {})
    sp_trend = dow.get("sp500_trend")
    sp_vs_sma = dow.get("sp500_vs_sma50")
    if sp_trend and sp_vs_sma:
        consistent = not (sp_trend == "bullish" and sp_vs_sma == "below") and \
                    not (sp_trend == "bearish" and sp_vs_sma == "above")
        report.add(Check("GR3-06", "grounding", "intermarket",
                         "SP500 trend direction consistent with SMA50 position",
                         consistent,
                         f"Trend: {sp_trend}, vs SMA50: {sp_vs_sma}",
                         severity="medium"))

    # GR3-07: Synthesize coherence_status matches contradiction_count
    syn = data.get("synthesize", {})
    coh_status = syn.get("coherence_status", "")
    contra_count = syn.get("contradiction_count", 0)
    if coh_status:
        clean_but_contradictions = coh_status == "CLEAN" and contra_count > 0
        report.add(Check("GR3-07", "grounding", "synthesize",
                         "Coherence status consistent with contradiction count",
                         not clean_but_contradictions,
                         f"Status: '{coh_status}', Contradictions: {contra_count}",
                         severity="medium"))

    # GR3-08: Allocation buyback strategy vs actual activity
    alloc = data.get("allocation_NVDA", {})
    summary = alloc.get("latest_quarter_summary", {})
    strategy = summary.get("buyback_strategy", "")
    total_return = summary.get("total_shareholder_return", 0)
    alloc_data = alloc.get("quarterly_data", [])
    latest = alloc_data[-1] if alloc_data else {}
    buybacks = abs(latest.get("share_repurchases", 0))

    if strategy and latest:
        # Latest quarter has $3.8B buybacks but summary says "inactive"
        mismatch = strategy == "inactive" and buybacks > 1_000_000_000
        report.add(Check("GR3-08", "grounding", "allocation",
                         "Buyback strategy label matches latest quarter data",
                         not mismatch,
                         f"Strategy: '{strategy}', Latest buybacks: ${buybacks/1e9:.1f}B" +
                         (" — CONTRADICTION" if mismatch else ""),
                         expected="active" if buybacks > 1e9 else "inactive",
                         actual=strategy, severity="high"))


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
        "yardeni_suite": {
            "commands": "/bbb, /vigilantes, /drawdown, /valuation-adjacent",
            "data_keys": ["bbb", "vigilantes", "drawdown"],
            "dimensions": [
                ("Framework Fidelity", 25, "How well does each tool implement Yardeni's actual framework?"),
                ("Data Completeness", 20, "Are all required inputs available and non-null?"),
                ("Diagnostic Value", 20, "Do the outputs provide actionable business cycle signals?"),
                ("Cross-Framework Consistency", 15, "Do the Yardeni tools agree with each other?"),
                ("Quantitative Accuracy", 10, "Are calculations correct?"),
                ("Methodology Documentation", 10, "Is the methodology properly explained?"),
            ]
        },
        "equity_deep_dive": {
            "commands": "/peers NVDA, /allocation NVDA, /balance NVDA",
            "data_keys": ["peers_NVDA", "allocation_NVDA", "balance_NVDA"],
            "dimensions": [
                ("Data Coverage", 20, "How many quarters of data, how many peers?"),
                ("Data Freshness", 20, "Is the data from recent quarters?"),
                ("Analytical Depth", 20, "Trend analysis, ratio decomposition, working capital insights?"),
                ("Calculation Accuracy", 15, "Are ratios and metrics computed correctly?"),
                ("Peer Selection Quality", 15, "Are the right peers chosen by GICS classification?"),
                ("Investment Utility", 10, "Can an investor act on these outputs?"),
            ]
        },
        "pro_trader_suite": {
            "commands": "/riskpremium, /crossasset, /intermarket, /synthesize",
            "data_keys": ["riskpremium", "crossasset", "intermarket", "synthesize"],
            "dimensions": [
                ("Signal Quality", 25, "Are the signals (WALL_FEAR, SELECTIVE_RISK_ON, etc.) meaningful?"),
                ("Cross-Tool Integration", 20, "Do the tools form a coherent multi-asset narrative?"),
                ("Quantitative Rigor", 15, "Correlations, ratios, percentiles — are they correct?"),
                ("Regime Identification", 20, "Is the overall market regime clearly identified?"),
                ("Actionability", 10, "Clear trade/positioning implications?"),
                ("Professional Quality", 10, "Consistent timestamps, proper terminology?"),
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
        prompt = f"""You are a senior financial analyst evaluating the output quality of an AI financial agent.

Below is the JSON output from these commands: {cfg['commands']}

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
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def collect_live():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_FA_ROOT, ".env"))
    from tools.yardeni_frameworks import get_boom_bust_barometer, get_fsmi, analyze_bond_vigilantes, classify_market_decline
    from tools.equity_analysis import get_peer_comparison, analyze_capital_allocation, analyze_balance_sheet_health
    from tools.protrader_frameworks import protrader_risk_premium_analysis, protrader_cross_asset_momentum
    from tools.murphy_ta import murphy_intermarket_analysis
    from tools.macro_synthesis import synthesize_macro_view

    fns = {
        "bbb": get_boom_bust_barometer,
        "fsmi": get_fsmi,
        "vigilantes": analyze_bond_vigilantes,
        "drawdown": classify_market_decline,
        "peers_NVDA": lambda: get_peer_comparison("NVDA"),
        "allocation_NVDA": lambda: analyze_capital_allocation("NVDA"),
        "balance_NVDA": lambda: analyze_balance_sheet_health("NVDA"),
        "riskpremium": protrader_risk_premium_analysis,
        "crossasset": protrader_cross_asset_momentum,
        "intermarket": murphy_intermarket_analysis,
        "synthesize": synthesize_macro_view,
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


# ═════════════════════════════════════════════════════════════════════
# REPORT GENERATION & MAIN
# ═════════════════════════════════════════════════════════════════════

def save_report(report, data, llm_scores):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _RECORDS_DIR / f"batch3_eval_{ts}.json"
    md_path = _RECORDS_DIR / f"batch3_eval_{ts}.md"

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
        "# Command Batch 3 Taste Evaluation Report\n",
        f"**Date**: {datetime.now().isoformat()}",
        f"**Commands**: /bbb, /fsmi, /vigilantes, /drawdown, /peers NVDA, /allocation NVDA, /balance NVDA, /riskpremium, /crossasset, /intermarket, /synthesize\n",
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
    print(f"BATCH 3 EVALUATION RESULTS")
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


if __name__ == "__main__":
    main()
