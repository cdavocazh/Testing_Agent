"""
Command Batch 2 Taste Evaluation

Evaluates 10 Financial Agent commands:
  /macro, /bonds, /stress, /latecycle, /consumer,
  /housing, /labor, /graham NVDA, /valuation, /vixanalysis

Usage:
    python command_batch2_evaluator.py --input command_output_batch2_v1.json
    python command_batch2_evaluator.py  # Collect live then evaluate
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
# RESULT TYPES (same as batch 1)
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
        self.start_time = time.time()

    def add(self, c):
        self.checks.append(c)

    @property
    def summary(self):
        elapsed = time.time() - self.start_time
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        by_cat = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        by_cmd = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        for c in self.checks:
            by_cat[c.category]["total"] += 1
            by_cat[c.category]["passed" if c.passed else "failed"] += 1
            by_cmd[c.command]["total"] += 1
            by_cmd[c.command]["passed" if c.passed else "failed"] += 1
        crit = sum(1 for c in self.checks if not c.passed and c.severity == "critical")
        return {
            "total_checks": total, "passed": passed, "failed": total - passed,
            "rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_failures": crit,
            "by_category": dict(by_cat), "by_command": dict(by_cmd),
            "elapsed": f"{elapsed:.1f}s",
        }


def _safe(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d

def _approx_eq(a, b, tol=0.02):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= tol
    except:
        return False


# ═════════════════════════════════════════════════════════════════════
# APPROACH 1: DATA ACCURACY
# ═════════════════════════════════════════════════════════════════════

def run_accuracy_checks(d, report):
    macro = d.get("macro", {})
    bonds = d.get("bonds", {})
    stress = d.get("stress", {})
    latecycle = d.get("latecycle", {})
    consumer = d.get("consumer", {})
    housing = d.get("housing", {})
    labor = d.get("labor", {})
    graham = d.get("graham_NVDA", {})
    valuation = d.get("valuation", {})
    vix = d.get("vixanalysis", {})

    # ── /macro accuracy ──────────────────────────────────────────
    # MA-01: 2s10s spread = 10Y - 2Y
    y10 = _safe(bonds, "yield_curve", "nominal_yields", "10y", "latest_value")
    y2 = _safe(bonds, "yield_curve", "nominal_yields", "2y", "latest_value")
    spread_2s10s = _safe(bonds, "yield_curve", "spreads", "2s10s", "latest_value")
    if y10 and y2 and spread_2s10s is not None:
        expected = round(y10 - y2, 2)
        report.add(Check("MA-01", "accuracy", "bonds",
                         "2s10s spread = 10Y - 2Y",
                         _approx_eq(expected, spread_2s10s, 0.03),
                         f"Expected {expected}, got {spread_2s10s}",
                         expected, spread_2s10s, "high"))

    # MA-02: Term premium = nominal_10y - real_10y - breakeven_10y
    tp = _safe(bonds, "term_premium", "term_premium_pct")
    nom10 = _safe(bonds, "term_premium", "components", "nominal_10y")
    real10 = _safe(bonds, "term_premium", "components", "real_10y")
    be10 = _safe(bonds, "term_premium", "components", "breakeven_10y")
    if tp is not None and nom10 and real10 and be10:
        expected_tp = round(nom10 - real10 - be10, 2)
        report.add(Check("MA-02", "accuracy", "bonds",
                         "Term premium = nominal - real - breakeven",
                         _approx_eq(expected_tp, tp, 0.02),
                         f"Expected {expected_tp}, got {tp}",
                         expected_tp, tp, "high"))

    # MA-03: HY OAS bps = pct × 100 (in bonds)
    hy_pct = _safe(bonds, "credit_spreads", "high_yield_oas", "latest_value")
    hy_bps = _safe(bonds, "credit_spreads", "high_yield_oas", "latest_value_bps")
    if hy_pct and hy_bps:
        expected_bps = round(hy_pct * 100)
        report.add(Check("MA-03", "accuracy", "bonds",
                         "HY OAS bps = pct × 100",
                         abs(expected_bps - hy_bps) <= 1,
                         f"Expected {expected_bps}, got {hy_bps}",
                         expected_bps, hy_bps, "medium"))

    # MA-04: IG OAS bps = pct × 100
    ig_pct = _safe(bonds, "credit_spreads", "ig_corporate_oas", "latest_value")
    ig_bps = _safe(bonds, "credit_spreads", "ig_corporate_oas", "latest_value_bps")
    if ig_pct and ig_bps:
        expected_bps = round(ig_pct * 100)
        report.add(Check("MA-04", "accuracy", "bonds",
                         "IG OAS bps = pct × 100",
                         abs(expected_bps - ig_bps) <= 1,
                         f"Expected {expected_bps}, got {ig_bps}",
                         expected_bps, ig_bps, "medium"))

    # MA-05: HY-IG differential = HY bps - IG bps
    diff_bps = _safe(bonds, "credit_spreads", "hy_ig_differential", "value_bps")
    if hy_bps and ig_bps and diff_bps is not None:
        expected_diff = hy_bps - ig_bps
        report.add(Check("MA-05", "accuracy", "bonds",
                         "HY-IG differential = HY bps - IG bps",
                         abs(expected_diff - diff_bps) <= 2,
                         f"Expected {expected_diff}, got {diff_bps}",
                         expected_diff, diff_bps, "medium"))

    # ── /stress accuracy ──────────────────────────────────────────
    # SA-01: Composite score = weighted sum of components
    components = stress.get("components", {})
    comp_score = stress.get("composite_score")
    if components and comp_score is not None:
        weighted_sum = 0
        total_weight = 0
        for name, comp in components.items():
            s = comp.get("score")
            w = comp.get("weight")
            if s is not None and w is not None:
                weighted_sum += s * w
                total_weight += w
        if total_weight > 0:
            expected_score = round(weighted_sum / total_weight, 2) if total_weight < 0.99 else round(weighted_sum, 2)
            # The composite may be weighted_sum directly if weights sum to 1
            report.add(Check("SA-01", "accuracy", "stress",
                             "Composite score = weighted sum of component scores",
                             _approx_eq(weighted_sum, comp_score, 0.3),
                             f"Weighted sum: {weighted_sum:.2f}, Reported: {comp_score}",
                             round(weighted_sum, 2), comp_score, "high"))

    # SA-02: All component scores in 0-10 range
    bad_scores = []
    for name, comp in components.items():
        s = comp.get("score")
        if s is not None and (s < 0 or s > 10):
            bad_scores.append(f"{name}={s}")
    report.add(Check("SA-02", "accuracy", "stress",
                     "All stress component scores in [0, 10]",
                     len(bad_scores) == 0,
                     f"{'All OK' if not bad_scores else 'Out of range: ' + ', '.join(bad_scores)}",
                     "all [0,10]", bad_scores or "OK", "medium"))

    # SA-03: All component weights sum to ~1.0
    total_w = sum(c.get("weight", 0) for c in components.values())
    report.add(Check("SA-03", "accuracy", "stress",
                     "Component weights sum to ~1.0",
                     _approx_eq(total_w, 1.0, 0.05),
                     f"Total weight: {total_w}",
                     1.0, round(total_w, 3), "medium"))

    # SA-04: Initial claims interpretation — "213000K" is wrong (should be 213K or 213,000)
    claims_interp = _safe(stress, "components", "initial_claims", "interpretation", default="")
    claims_val = _safe(stress, "components", "initial_claims", "value")
    has_unit_error = "213000K" in claims_interp or (claims_val and "K" in claims_interp and claims_val > 1000)
    report.add(Check("SA-04", "accuracy", "stress",
                     "Initial claims interpretation units correct",
                     not has_unit_error,
                     f"Interpretation: '{claims_interp}'. "
                     f"{'BUG: 213000K should be 213K' if has_unit_error else 'OK'}",
                     "213K", claims_interp, "high"))

    # ── /latecycle accuracy ──────────────────────────────────────
    # LA-01: count matches actual firing signals
    signals_list = latecycle.get("signals_firing", [])
    reported_count = latecycle.get("count")
    actual_firing = sum(1 for s in signals_list if s.get("status") == "firing")
    if reported_count is not None:
        report.add(Check("LA-01", "accuracy", "latecycle",
                         "Reported count matches actual firing signals",
                         reported_count == actual_firing,
                         f"Reported: {reported_count}, Actual firing: {actual_firing}",
                         actual_firing, reported_count, "high"))

    # LA-02: total matches length of signals list
    reported_total = latecycle.get("total")
    actual_total = len(signals_list)
    if reported_total is not None:
        report.add(Check("LA-02", "accuracy", "latecycle",
                         "Reported total matches signals list length",
                         reported_total == actual_total,
                         f"Reported: {reported_total}, List length: {actual_total}",
                         actual_total, reported_total, "medium"))

    # ── /consumer accuracy ──────────────────────────────────────
    # CA-01: Consumer composite score weighted calculation
    cons_comps = consumer.get("components", {})
    cons_score = consumer.get("composite_score")
    if cons_comps and cons_score is not None:
        ws = 0
        tw = 0
        avail = 0
        for name, comp in cons_comps.items():
            s = comp.get("score")
            w = comp.get("weight", 0)
            if s is not None and s > 0:
                ws += s * w
                tw += w
                avail += 1
        # Score likely rescaled to available components
        if tw > 0:
            expected = round(ws / tw, 2)
            report.add(Check("CON-01", "accuracy", "consumer",
                             "Consumer composite = weighted avg of available components",
                             _approx_eq(expected, cons_score, 0.5),
                             f"Weighted avg: {expected}, Reported: {cons_score} ({avail}/{len(cons_comps)} components)",
                             expected, cons_score, "medium"))

    # CA-02: Credit growth velocity data availability
    cgv = _safe(consumer, "components", "credit_growth_velocity", "value")
    report.add(Check("CON-02", "accuracy", "consumer",
                     "Credit growth velocity data available",
                     cgv is not None,
                     f"{'Available: ' + str(cgv) if cgv is not None else 'MISSING — key consumer metric unavailable'}",
                     "available", cgv, "high"))

    # ── /housing accuracy ──────────────────────────────────────
    # HA-01: Permits/starts ratio arithmetic
    permits = _safe(housing, "permits_pipeline", "latest_value")
    starts = _safe(housing, "starts_momentum", "latest_value")
    ratio = _safe(housing, "permits_pipeline", "permits_to_starts_ratio")
    if permits and starts and ratio and starts > 0:
        expected_ratio = round(permits / starts, 2)
        report.add(Check("HA-01", "accuracy", "housing",
                         "Permits/starts ratio = permits / starts",
                         _approx_eq(expected_ratio, ratio, 0.02),
                         f"Expected {expected_ratio}, got {ratio}",
                         expected_ratio, ratio, "medium"))

    # HA-02: Price dynamics data available
    pd_status = _safe(housing, "price_dynamics", "status")
    report.add(Check("HA-02", "accuracy", "housing",
                     "Price dynamics data available",
                     pd_status != "data_unavailable",
                     f"{'Available' if pd_status != 'data_unavailable' else 'MISSING — Case-Shiller data unavailable'}",
                     "available", pd_status, "high"))

    # ── /labor accuracy ──────────────────────────────────────────
    # LB-01: Hires/layoffs ratio arithmetic
    hires = _safe(labor, "hiring_firing_balance", "hires_latest_thousands")
    layoffs = _safe(labor, "hiring_firing_balance", "layoffs_latest_thousands")
    h2l = _safe(labor, "hiring_firing_balance", "hires_to_layoffs_ratio")
    if hires and layoffs and h2l and layoffs > 0:
        expected = round(hires / layoffs, 2)
        report.add(Check("LB-01", "accuracy", "labor",
                         "Hires/layoffs ratio = hires / layoffs",
                         _approx_eq(expected, h2l, 0.05),
                         f"Expected {expected}, got {h2l}",
                         expected, h2l, "medium"))

    # LB-02: Productivity data availability
    prod = _safe(labor, "productivity_vs_ulc", "productivity_yoy_pct")
    ulc = _safe(labor, "productivity_vs_ulc", "ulc_yoy_pct")
    report.add(Check("LB-02", "accuracy", "labor",
                     "Productivity vs ULC data available",
                     prod is not None and ulc is not None,
                     f"Productivity: {prod}, ULC: {ulc}. "
                     f"{'Available' if prod is not None else 'MISSING — core labor metric'}",
                     "both available", f"prod={prod}, ulc={ulc}", "high"))

    # LB-03: Core CPI YoY plausibility
    core_cpi = _safe(labor, "wage_inflation_link", "core_cpi_yoy_pct")
    if core_cpi is not None:
        plausible = -5 <= core_cpi <= 15
        report.add(Check("LB-03", "accuracy", "labor",
                         "Core CPI YoY in plausible range",
                         plausible,
                         f"Core CPI YoY: {core_cpi}%. {'OK' if plausible else 'SUSPICIOUS'}",
                         "[-5, 15]", core_cpi, "critical"))

    # ── /graham accuracy ──────────────────────────────────────────
    # GA-01: Graham Number = sqrt(22.5 × EPS_TTM × BVPS)
    eps = _safe(graham, "graham_number", "eps_ttm")
    bvps = _safe(graham, "graham_number", "bvps")
    gn = _safe(graham, "graham_number", "value")
    if eps and bvps and gn and eps > 0 and bvps > 0:
        expected_gn = round(math.sqrt(22.5 * eps * bvps), 2)
        report.add(Check("GA-01", "accuracy", "graham",
                         "Graham Number = sqrt(22.5 × EPS × BVPS)",
                         _approx_eq(expected_gn, gn, 0.5),
                         f"Expected {expected_gn}, got {gn}",
                         expected_gn, gn, "high"))

    # GA-02: Margin of Safety = (Graham# - Price) / Price × 100
    price = graham.get("current_price")
    mos = _safe(graham, "margin_of_safety", "pct")
    if gn and price and mos is not None and price > 0:
        expected_mos = round((gn - price) / price * 100, 2)
        report.add(Check("GA-02", "accuracy", "graham",
                         "Margin of Safety = (GN - Price) / Price × 100",
                         _approx_eq(expected_mos, mos, 1.0),
                         f"Expected {expected_mos}%, got {mos}%",
                         expected_mos, mos, "high"))

    # GA-03: P/E × P/B = pe × pb
    pe = _safe(graham, "valuation_metrics", "trailing_pe")
    pb = _safe(graham, "valuation_metrics", "price_to_book")
    pe_pb = _safe(graham, "valuation_metrics", "pe_x_pb")
    if pe and pb and pe_pb:
        expected = round(pe * pb, 2)
        report.add(Check("GA-03", "accuracy", "graham",
                         "P/E × P/B product",
                         _approx_eq(expected, pe_pb, 2.0),
                         f"Expected {expected}, got {pe_pb}",
                         expected, pe_pb, "medium"))

    # GA-04: Graham data freshness (same stale NVDA data issue)
    lq = graham.get("latest_quarter", "")
    is_stale = False
    if lq:
        try:
            is_stale = int(lq.split("-")[0]) < 2024
        except:
            is_stale = True
    report.add(Check("GA-04", "accuracy", "graham",
                     "Graham data freshness (latest quarter)",
                     not is_stale,
                     f"Latest quarter: {lq}. {'STALE' if is_stale else 'OK'}",
                     "≥ 2024", lq, "critical"))

    # GA-05: NCAV per share = (CA - TL) / shares
    ca = _safe(graham, "net_net_wcav", "current_assets")
    tl = _safe(graham, "net_net_wcav", "total_liabilities")
    ncav = _safe(graham, "net_net_wcav", "ncav_per_share")
    shares_raw = _safe(graham, "graham_number", "bvps")
    # Need shares — approximate from equity / bvps
    if ca and tl and ncav and price:
        # price_to_ncav should = price / ncav
        p2ncav = _safe(graham, "net_net_wcav", "price_to_ncav")
        if p2ncav and ncav > 0:
            expected_p2ncav = round(price / ncav, 2)
            report.add(Check("GA-05", "accuracy", "graham",
                             "Price/NCAV = current_price / ncav_per_share",
                             _approx_eq(expected_p2ncav, p2ncav, 0.2),
                             f"Expected {expected_p2ncav}, got {p2ncav}",
                             expected_p2ncav, p2ncav, "medium"))

    # ── /valuation accuracy ──────────────────────────────────────
    # VA-01: Valuation has usable output (not insufficient_data)
    val_status = valuation.get("assessment")
    report.add(Check("VA-01", "accuracy", "valuation",
                     "Yardeni valuation produces results",
                     val_status != "insufficient_data",
                     f"Assessment: '{val_status}'. "
                     f"{'MISSING — CPI data required' if val_status == 'insufficient_data' else 'OK'}",
                     "has results", val_status, "critical"))

    # VA-02: CPI YoY data available for valuation
    cpi = _safe(valuation, "inputs", "cpi_yoy_pct")
    report.add(Check("VA-02", "accuracy", "valuation",
                     "CPI YoY available for valuation frameworks",
                     cpi is not None,
                     f"CPI YoY: {cpi}. {'Available' if cpi is not None else 'MISSING — blocks Rule of 20/24'}",
                     "available", cpi, "critical"))

    # ── /vixanalysis accuracy ──────────────────────────────────────
    # VX-01: VIX tier matches value
    vix_val = _safe(vix, "vix", "latest")
    vix_tier = _safe(vix, "vix", "tier")
    if vix_val is not None and vix_tier is not None:
        expected_tier = (7 if vix_val >= 50 else 6 if vix_val >= 40 else
                         5 if vix_val >= 30 else 4 if vix_val >= 25 else
                         3 if vix_val >= 20 else 2 if vix_val >= 14 else 1)
        report.add(Check("VX-01", "accuracy", "vixanalysis",
                         "VIX tier matches value",
                         expected_tier == vix_tier,
                         f"VIX={vix_val}, Expected tier {expected_tier}, got {vix_tier}",
                         expected_tier, vix_tier, "high"))

    # VX-02: MOVE/VIX ratio = MOVE / VIX
    move_val = _safe(vix, "move", "latest")
    ratio_val = _safe(vix, "move", "move_vix_ratio")
    if move_val and vix_val and ratio_val:
        expected_ratio = round(move_val / vix_val, 2)
        report.add(Check("VX-02", "accuracy", "vixanalysis",
                         "MOVE/VIX ratio = MOVE / VIX",
                         _approx_eq(expected_ratio, ratio_val, 0.05),
                         f"Expected {expected_ratio}, got {ratio_val}",
                         expected_ratio, ratio_val, "medium"))

    # VX-03: VIX percentile plausibility (0-100)
    pctile = _safe(vix, "vix", "percentile_1y")
    if pctile is not None:
        report.add(Check("VX-03", "accuracy", "vixanalysis",
                         "VIX percentile in [0, 100]",
                         0 <= pctile <= 100,
                         f"Percentile: {pctile}",
                         "[0, 100]", pctile, "low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 2: COHERENCE
# ═════════════════════════════════════════════════════════════════════

def run_coherence_checks(d, report):
    macro = d.get("macro", {})
    bonds = d.get("bonds", {})
    stress = d.get("stress", {})
    latecycle = d.get("latecycle", {})
    consumer = d.get("consumer", {})
    housing = d.get("housing", {})
    labor = d.get("labor", {})
    vix = d.get("vixanalysis", {})

    # CC-01: Macro growth "contraction" ↔ ISM < 50
    growth = _safe(macro, "regimes", "growth", "classification")
    ism = _safe(macro, "regimes", "growth", "value")
    if growth and ism:
        expected = "contraction" if ism < 50 else "expansion" if ism > 55 else "moderate"
        # "contraction" at 49.12 is correct
        report.add(Check("CC-01", "coherence", "macro",
                         "Growth classification ↔ ISM value",
                         (growth == "contraction" and ism < 50) or (growth != "contraction" and ism >= 50),
                         f"ISM: {ism}, Classification: '{growth}'",
                         expected, growth, "high"))

    # CC-02: Credit classification ↔ stress level (same data source)
    macro_credit = _safe(macro, "regimes", "credit", "stress_level")
    stress_hy = _safe(stress, "components", "hy_oas", "stress_level")
    if macro_credit and stress_hy:
        report.add(Check("CC-02", "coherence", "cross-command",
                         "Macro credit stress ↔ Stress HY OAS level (same source)",
                         macro_credit == stress_hy,
                         f"Macro: '{macro_credit}', Stress: '{stress_hy}'",
                         "match", f"{macro_credit} vs {stress_hy}", "high"))

    # CC-03: Bond yield curve shape ↔ macro rates curve_shape
    bond_shape = _safe(bonds, "yield_curve", "shape")
    macro_shape = _safe(macro, "regimes", "rates", "curve_shape")
    if bond_shape and macro_shape:
        report.add(Check("CC-03", "coherence", "cross-command",
                         "Bond yield curve shape ↔ Macro rates curve shape",
                         bond_shape == macro_shape,
                         f"Bonds: '{bond_shape}', Macro: '{macro_shape}'",
                         "match", f"'{bond_shape}' vs '{macro_shape}'", "high"))

    # CC-04: Macro "Recessionary" ↔ stress score
    outlook = macro.get("composite_outlook", "")
    stress_score = stress.get("composite_score")
    if "recessionary" in outlook.lower() and stress_score is not None:
        # Recessionary outlook should have elevated stress (> 4)
        consistent = stress_score >= 4
        report.add(Check("CC-04", "coherence", "cross-command",
                         "Recessionary outlook ↔ stress score ≥ 4",
                         consistent,
                         f"Outlook: '{outlook}', Stress: {stress_score}",
                         "≥ 4", stress_score,
                         "critical" if not consistent else "medium"))

    # CC-05: Housing signals in macro ↔ housing command
    macro_housing_signals = [s for s in macro.get("signals", []) if "HOUSING" in s or "SALES" in s]
    housing_signals = housing.get("signals", [])
    # EXISTING_SALES_PLUNGING should appear in both
    shared = set(macro_housing_signals) & set(housing_signals)
    report.add(Check("CC-05", "coherence", "cross-command",
                     "Housing signals consistent between /macro and /housing",
                     len(shared) > 0 or (len(macro_housing_signals) == 0 and len(housing_signals) == 0),
                     f"Macro signals: {macro_housing_signals}, Housing: {housing_signals}, Shared: {list(shared)}",
                     severity="medium"))

    # CC-06: Consumer health level ↔ stress consumer component
    consumer_level = consumer.get("consumer_health_level")
    cons_delinq_score = _safe(stress, "components", "consumer_credit", "score")
    if consumer_level and cons_delinq_score is not None:
        # "stable" consumer + low delinquency score (1) should be coherent
        report.add(Check("CC-06", "coherence", "cross-command",
                         "Consumer health ↔ stress consumer credit (informational)",
                         True,
                         f"Consumer level: '{consumer_level}', Delinquency score: {cons_delinq_score}/10",
                         severity="low"))

    # CC-07: Late-cycle ISM contraction ↔ macro growth contraction
    lc_ism = next((s for s in latecycle.get("signals_firing", [])
                   if "ISM" in s.get("name", "") and s.get("status") == "firing"), None)
    macro_ism_signal = "ISM_CONTRACTION" in macro.get("signals", [])
    report.add(Check("CC-07", "coherence", "cross-command",
                     "Late-cycle ISM firing ↔ macro ISM_CONTRACTION signal",
                     (lc_ism is not None) == macro_ism_signal,
                     f"Late-cycle ISM: {'firing' if lc_ism else 'not firing'}, "
                     f"Macro ISM_CONTRACTION: {macro_ism_signal}",
                     severity="high"))

    # CC-08: VIX value consistent between /stress and /vixanalysis
    stress_vix = _safe(stress, "components", "vix", "value")
    vix_latest = _safe(vix, "vix", "latest")
    if stress_vix and vix_latest:
        report.add(Check("CC-08", "coherence", "cross-command",
                         "VIX value consistent: /stress vs /vixanalysis",
                         _approx_eq(stress_vix, vix_latest, 0.5),
                         f"Stress VIX: {stress_vix}, VIX analysis: {vix_latest}",
                         stress_vix, vix_latest, "high"))

    # CC-09: HY OAS consistent between /bonds and /stress
    bond_hy = _safe(bonds, "credit_spreads", "high_yield_oas", "latest_value")
    stress_hy_val = _safe(stress, "components", "hy_oas", "value")
    if bond_hy and stress_hy_val:
        report.add(Check("CC-09", "coherence", "cross-command",
                         "HY OAS consistent: /bonds vs /stress",
                         _approx_eq(bond_hy, stress_hy_val, 0.05),
                         f"Bonds HY: {bond_hy}, Stress HY: {stress_hy_val}",
                         bond_hy, stress_hy_val, "high"))

    # CC-10: Labor "hiring_dominant" ↔ macro employment "moderate"
    labor_balance = _safe(labor, "hiring_firing_balance", "balance")
    macro_emp = _safe(macro, "regimes", "employment", "classification")
    if labor_balance and macro_emp:
        report.add(Check("CC-10", "coherence", "cross-command",
                         "Labor balance ↔ macro employment (informational)",
                         True,
                         f"Labor: '{labor_balance}', Macro employment: '{macro_emp}'",
                         severity="low"))

    # CC-11: Core CPI YoY anomaly — macro shows -8.22% for core CPI
    core_cpi_yoy = _safe(macro, "inflation_detail", "core_cpi", "yoy_change_pct")
    if core_cpi_yoy is not None:
        plausible = -5 <= core_cpi_yoy <= 15
        report.add(Check("CC-11", "coherence", "macro",
                         "Core CPI YoY plausible (-5% to 15%)",
                         plausible,
                         f"Core CPI YoY: {core_cpi_yoy}%. "
                         f"{'IMPLAUSIBLE — -8.22% core CPI never happens in normal economy' if not plausible else 'OK'}",
                         "[-5, 15]", core_cpi_yoy, "critical"))

    # CC-12: Core PCE at 0.28% labeled "cooling" — but is that the actual level or YoY change?
    core_pce_val = _safe(macro, "regimes", "inflation", "value")
    core_pce_evidence = _safe(macro, "regimes", "inflation", "evidence", default="")
    if core_pce_val is not None:
        # Core PCE YoY at 0.28% is extremely low — nearly zero inflation
        report.add(Check("CC-12", "coherence", "macro",
                         "Core PCE value plausibility",
                         core_pce_val > 1.0 or core_pce_val < -1.0,
                         f"Core PCE YoY: {core_pce_val}%. Evidence: '{core_pce_evidence}'. "
                         f"{'SUSPICIOUS — 0.28% Core PCE YoY is implausibly low' if 0 < core_pce_val < 1.0 else 'OK'}",
                         "> 1% or plausible", core_pce_val, "critical"))

    # CC-13: Macro "CREDIT_TIGHT" signal ↔ credit classification
    has_credit_tight = "CREDIT_TIGHT" in macro.get("signals", [])
    credit_class = _safe(macro, "regimes", "credit", "classification")
    if has_credit_tight and credit_class:
        # CREDIT_TIGHT usually means classification is "elevated" or "stressed"
        report.add(Check("CC-13", "coherence", "macro",
                         "CREDIT_TIGHT signal ↔ credit classification",
                         credit_class in ("elevated", "stressed", "severe_stress", "crisis"),
                         f"Signal: CREDIT_TIGHT, Classification: '{credit_class}'",
                         "elevated+", credit_class, "medium"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 3: GROUNDING
# ═════════════════════════════════════════════════════════════════════

def run_grounding_checks(d, report):
    macro = d.get("macro", {})
    stress = d.get("stress", {})
    consumer = d.get("consumer", {})
    housing = d.get("housing", {})
    labor = d.get("labor", {})
    latecycle = d.get("latecycle", {})
    bonds = d.get("bonds", {})

    # GR-01: Inflation "cooling" ↔ Core PCE trend
    inf_class = _safe(macro, "regimes", "inflation", "classification")
    inf_trend = _safe(macro, "regimes", "inflation", "trend")
    # "cooling" classification but "rising" trend is contradictory
    if inf_class and inf_trend:
        contradicts = inf_class == "cooling" and inf_trend == "rising"
        report.add(Check("GR-01", "grounding", "macro",
                         "Inflation 'cooling' ↔ trend direction",
                         not contradicts,
                         f"Classification: '{inf_class}', Trend: '{inf_trend}'. "
                         f"{'CONTRADICTION: cooling but rising trend' if contradicts else 'OK'}",
                         "consistent", f"{inf_class} + {inf_trend}", "critical"))

    # GR-02: Stress level label ↔ composite score
    stress_level = stress.get("stress_level")
    stress_score = stress.get("composite_score")
    if stress_level and stress_score is not None:
        # Expected: 0-2 = benign, 2-4 = moderate, 4-6 = elevated, 6-8 = stressed, 8-10 = crisis
        expected = ("benign" if stress_score < 2 else
                    "moderate" if stress_score < 4 else
                    "elevated" if stress_score < 6 else
                    "stressed" if stress_score < 8 else "crisis")
        report.add(Check("GR-02", "grounding", "stress",
                         "Stress level label ↔ composite score",
                         stress_level == expected,
                         f"Score: {stress_score}, Expected: '{expected}', Got: '{stress_level}'",
                         expected, stress_level, "high"))

    # GR-03: Late-cycle confidence label ↔ count
    lc_count = latecycle.get("count")
    lc_conf = latecycle.get("confidence_level")
    if lc_count is not None and lc_conf:
        # "late-early warning" is a confusing/non-standard label
        report.add(Check("GR-03", "grounding", "latecycle",
                         "Late-cycle confidence label clarity",
                         "late-early" not in lc_conf,
                         f"Count: {lc_count}/13, Confidence: '{lc_conf}'. "
                         f"{'CONFUSING: late-early warning is ambiguous' if 'late-early' in lc_conf else 'Clear label'}",
                         "clear label", lc_conf, "medium"))

    # GR-04: Consumer "stable" ↔ score 6.87/10
    cons_level = consumer.get("consumer_health_level")
    cons_score = consumer.get("composite_score")
    if cons_level and cons_score is not None:
        # "stable" at 6.87 seems reasonable (not "healthy" which would be 8+)
        expected = ("critical" if cons_score < 3 else
                    "stressed" if cons_score < 5 else
                    "stable" if cons_score < 8 else "healthy")
        report.add(Check("GR-04", "grounding", "consumer",
                         "Consumer health label ↔ score",
                         cons_level == expected,
                         f"Score: {cons_score}, Expected: '{expected}', Got: '{cons_level}'",
                         expected, cons_level, "medium"))

    # GR-05: Housing cycle "distressed" ↔ signals
    housing_phase = _safe(housing, "housing_cycle_phase", "phase")
    housing_signals = housing.get("signals", [])
    if housing_phase:
        distress_signals = [s for s in housing_signals if "PLUNGING" in s or "STRESSED" in s]
        report.add(Check("GR-05", "grounding", "housing",
                         "Housing cycle 'distressed' ↔ distress signals present",
                         (housing_phase == "distressed" and len(distress_signals) > 0) or
                         housing_phase != "distressed",
                         f"Phase: '{housing_phase}', Distress signals: {distress_signals}",
                         severity="medium"))

    # GR-06: Bond duration risk "moderate-high" ↔ rising real yields
    dur_risk = _safe(bonds, "duration_risk", "level")
    ry_trend = _safe(bonds, "real_yields", "10y_real", "trend")
    if dur_risk and ry_trend:
        # Rising real yields → moderate-high or high duration risk
        consistent = (ry_trend == "rising" and dur_risk in ("moderate-high", "high")) or \
                     (ry_trend != "rising")
        report.add(Check("GR-06", "grounding", "bonds",
                         "Duration risk label ↔ real yield trend",
                         consistent,
                         f"Duration risk: '{dur_risk}', Real yield trend: '{ry_trend}'",
                         severity="medium"))

    # GR-07: Fed stance ↔ rate level
    fed_rate = _safe(bonds, "fed_policy", "effective_rate")
    fed_stance = _safe(bonds, "fed_policy", "stance", default="")
    y10_val = _safe(bonds, "yield_curve", "nominal_yields", "10y", "latest_value")
    if fed_rate and y10_val and fed_stance:
        says_accommodative = "accommodative" in fed_stance.lower()
        is_below_10y = fed_rate < y10_val
        report.add(Check("GR-07", "grounding", "bonds",
                         "Fed stance ↔ funds rate vs 10Y",
                         says_accommodative == is_below_10y or not says_accommodative,
                         f"Fed: {fed_rate}%, 10Y: {y10_val}%, Stance: '{fed_stance}'",
                         severity="medium"))

    # GR-08: Labor power "weakening" ↔ quits rate
    power = _safe(labor, "labor_market_power", "power_level")
    quits = _safe(labor, "labor_market_power", "quits_rate")
    if power and quits:
        # "weakening" at 2.0% quits rate — historically low quits = weakening power
        report.add(Check("GR-08", "grounding", "labor",
                         "Labor power label ↔ quits rate (informational)",
                         True,
                         f"Power: '{power}', Quits rate: {quits}%",
                         severity="low"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 4: LLM JUDGE
# ═════════════════════════════════════════════════════════════════════

LLM_RUBRIC = {
    "macro_bonds_stress": {
        "name": "Macro Suite (/macro, /bonds, /stress, /latecycle)",
        "dimensions": [
            {"name": "Regime Classification Quality", "weight": 20,
             "prompt": "Are regime classifications (inflation, growth, employment, credit) accurate and well-justified by the underlying data?"},
            {"name": "Data Completeness", "weight": 15,
             "prompt": "Are all expected data fields populated? Are there missing sections or data_unavailable entries?"},
            {"name": "Signal Coherence", "weight": 20,
             "prompt": "Are signals logically consistent across commands? Do stress, late-cycle, and macro signals align?"},
            {"name": "Quantitative Accuracy", "weight": 15,
             "prompt": "Are calculations correct (spreads, ratios, scores)? Are units consistent?"},
            {"name": "Analytical Depth", "weight": 15,
             "prompt": "Does the output go beyond raw data to provide interpretation, implications, and second-order effects?"},
            {"name": "Actionability", "weight": 15,
             "prompt": "Can a portfolio manager use this to make investment decisions? Are there clear risk signals and positioning implications?"},
        ],
    },
    "consumer_housing_labor": {
        "name": "Consumer/Housing/Labor Suite",
        "dimensions": [
            {"name": "Component Coverage", "weight": 20,
             "prompt": "Are all key sub-indicators covered for each domain (consumer: savings, credit, delinquencies; housing: starts, permits, sales, affordability; labor: productivity, hires, quits, wages)?"},
            {"name": "Data Availability", "weight": 15,
             "prompt": "How many data fields are null, unavailable, or showing errors?"},
            {"name": "Composite Score Logic", "weight": 20,
             "prompt": "Do the composite scores and classifications (stable, distressed, etc.) follow logically from the component data?"},
            {"name": "Leading Indicator Value", "weight": 20,
             "prompt": "Does the analysis provide forward-looking signals? Can you anticipate economic direction from these outputs?"},
            {"name": "Cross-Domain Integration", "weight": 15,
             "prompt": "Do the three domains (consumer, housing, labor) paint a coherent economic picture when viewed together?"},
            {"name": "Professional Quality", "weight": 10,
             "prompt": "Is the output organized, using proper economic terminology, with appropriate detail levels?"},
        ],
    },
    "graham_valuation_vix": {
        "name": "Valuation Suite (/graham, /valuation, /vixanalysis)",
        "dimensions": [
            {"name": "Valuation Framework Quality", "weight": 25,
             "prompt": "Are Graham metrics (Graham Number, Defensive Criteria, Net-Net) and Yardeni frameworks (Rule of 20/24) correctly computed and meaningfully interpreted?"},
            {"name": "Data Freshness", "weight": 20,
             "prompt": "Is the underlying data current? Are there stale inputs that undermine the analysis?"},
            {"name": "Risk Assessment", "weight": 20,
             "prompt": "Does VIX analysis provide useful risk context? Are opportunity/complacency signals calibrated?"},
            {"name": "Actionability", "weight": 20,
             "prompt": "Can an investor act on these outputs? Are there clear buy/sell/hold implications?"},
            {"name": "Internal Consistency", "weight": 10,
             "prompt": "Do all numbers add up? Are labels consistent with values?"},
            {"name": "Completeness", "weight": 5,
             "prompt": "Are there missing sections or insufficient_data entries that limit the analysis?"},
        ],
    },
}


def run_llm_judge(d, report):
    try:
        from openai import OpenAI
    except ImportError:
        return {}

    try:
        from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
    except ImportError:
        LLM_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
        LLM_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")
        LLM_BASE_URL = "https://api.minimax.io/v1"

    if not LLM_API_KEY:
        return {}

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    print(f"  Using LLM: {LLM_MODEL}")

    scores = {}

    cmd_groups = {
        "macro_bonds_stress": {k: d[k] for k in ["macro", "bonds", "stress", "latecycle"] if k in d},
        "consumer_housing_labor": {k: d[k] for k in ["consumer", "housing", "labor"] if k in d},
        "graham_valuation_vix": {k: d[k] for k in ["graham_NVDA", "valuation", "vixanalysis"] if k in d},
    }

    for group_key, group_data in cmd_groups.items():
        rubric = LLM_RUBRIC[group_key]
        data_str = json.dumps(group_data, indent=2, default=str)[:8000]
        dim_descs = "\n".join(
            f"  {i+1}. **{dm['name']}** ({dm['weight']}%): {dm['prompt']}"
            for i, dm in enumerate(rubric["dimensions"])
        )

        prompt = f"""You are a CFA-level financial analyst evaluating the quality of a financial analysis tool suite.

TOOL OUTPUTS ({rubric['name']}):
```json
{data_str}
```

Score on EACH dimension (1-10):
{dim_descs}

1-3: Poor | 4-5: Below average | 6-7: Adequate | 8-9: Good | 10: Exceptional

Respond with EXACTLY this JSON:
{{
  "scores": {{
    "{rubric['dimensions'][0]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][1]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][2]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][3]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][4]['name']}": {{"score": N, "critique": "..."}},
    "{rubric['dimensions'][5]['name']}": {{"score": N, "critique": "..."}}
  }}
}}"""

        try:
            print(f"  Calling LLM for {rubric['name']}...")
            t0 = time.time()
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": "You are a financial analysis quality evaluator. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3, max_tokens=2000,
            )
            raw = resp.choices[0].message.content.strip()
            print(f"  Responded in {time.time()-t0:.1f}s")

            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            result = json.loads(raw)
            dim_scores = result.get("scores", result)
            cmd_scores = {}

            for dm in rubric["dimensions"]:
                nm = dm["name"]
                if nm in dim_scores:
                    s = dim_scores[nm]
                    cmd_scores[nm] = {"score": int(s.get("score", 0)), "weight": dm["weight"],
                                      "critique": s.get("critique", "")}
                else:
                    cmd_scores[nm] = {"score": 0, "weight": dm["weight"], "critique": "Not scored"}

        except Exception as e:
            print(f"  LLM error: {e}")
            cmd_scores = {dm["name"]: {"score": 0, "weight": dm["weight"], "critique": f"Error: {e}"}
                          for dm in rubric["dimensions"]}

        tw = sum(v["weight"] for v in cmd_scores.values())
        ws = round(sum(v["score"] * v["weight"] for v in cmd_scores.values()) / tw, 1) if tw else 0
        cmd_scores["_weighted_score"] = ws
        scores[group_key] = cmd_scores
        print(f"  {rubric['name']}: {ws}/10")

        report.add(Check(f"LLM-{group_key[:8].upper()}", "llm_judge", group_key,
                         f"LLM Judge: {rubric['name']}",
                         ws >= 5.0, f"Weighted score: {ws}/10",
                         "≥ 5.0", ws, "high"))

    return scores


# ═════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═════════════════════════════════════════════════════════════════════

def generate_markdown(report, llm_scores):
    s = report.summary
    lines = [
        "# Command Batch 2 Taste Evaluation Report", "",
        f"**Date**: {datetime.now().isoformat()}",
        "**Commands**: /macro, /bonds, /stress, /latecycle, /consumer, /housing, /labor, /graham NVDA, /valuation, /vixanalysis", "",
        "## Summary", "",
        "| Metric | Value |", "|--------|-------|",
        f"| Total Checks | {s['total_checks']} |",
        f"| Passed | {s['passed']} |",
        f"| Failed | {s['failed']} |",
        f"| Pass Rate | {s['rate']} |",
        f"| Critical Failures | {s['critical_failures']} |", "",
    ]

    lines += ["## By Category", "", "| Category | Total | Passed | Failed | Rate |",
              "|----------|-------|--------|--------|------|"]
    for cat, st in sorted(s["by_category"].items()):
        r = f"{st['passed']/st['total']*100:.0f}%" if st['total'] else "N/A"
        lines.append(f"| {cat} | {st['total']} | {st['passed']} | {st['failed']} | {r} |")

    lines += ["", "## By Command", "", "| Command | Total | Passed | Failed | Rate |",
              "|---------|-------|--------|--------|------|"]
    for cmd, st in sorted(s["by_command"].items()):
        r = f"{st['passed']/st['total']*100:.0f}%" if st['total'] else "N/A"
        lines.append(f"| {cmd} | {st['total']} | {st['passed']} | {st['failed']} | {r} |")

    failures = [c for c in report.checks if not c.passed]
    if failures:
        lines += ["", "## Failures", ""]
        for f in failures:
            lines += [
                f"### {f.check_id}: {f.check_name} [{f.severity.upper()}]",
                f"- **Command**: {f.command}", f"- **Detail**: {f.detail}",
            ]
            if f.expected is not None:
                lines.append(f"- **Expected**: {f.expected}")
            if f.actual is not None:
                lines.append(f"- **Actual**: {f.actual}")
            lines.append("")

    if llm_scores:
        lines += ["", "## LLM Judge Scores", ""]
        for grp, dims in llm_scores.items():
            ws = dims.pop("_weighted_score", 0)
            lines += [f"### {grp} — Weighted: {ws}/10", "",
                      "| Dimension | Weight | Score | Critique |",
                      "|-----------|--------|-------|----------|"]
            for nm, v in dims.items():
                if nm.startswith("_"):
                    continue
                lines.append(f"| {nm} | {v['weight']}% | {v['score']} | {v['critique'][:100]} |")
            lines.append("")

    lines += ["", "## All Checks", "",
              "| ID | Cat | Cmd | Check | Status | Sev |",
              "|----|-----|-----|-------|--------|-----|"]
    for c in report.checks:
        lines.append(f"| {c.check_id} | {c.category} | {c.command} | {c.check_name[:60]} | {'PASS' if c.passed else 'FAIL'} | {c.severity} |")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def collect_live():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_FA_ROOT, ".env"))
    from tools.macro_market_analysis import analyze_macro_regime, analyze_bond_market
    from tools.market_regime_enhanced import analyze_financial_stress, detect_late_cycle_signals, get_enhanced_vix_analysis
    from tools.consumer_housing_analysis import analyze_consumer_health, analyze_housing_market, analyze_labor_deep_dive
    from tools.graham_analysis import graham_value_analysis
    from tools.yardeni_frameworks import analyze_yardeni_valuation

    fns = {
        "macro": analyze_macro_regime,
        "bonds": analyze_bond_market,
        "stress": analyze_financial_stress,
        "latecycle": detect_late_cycle_signals,
        "consumer": analyze_consumer_health,
        "housing": analyze_housing_market,
        "labor": analyze_labor_deep_dive,
        "graham_NVDA": lambda: graham_value_analysis("NVDA"),
        "valuation": analyze_yardeni_valuation,
        "vixanalysis": get_enhanced_vix_analysis,
    }
    data = {}
    for name, fn in fns.items():
        print(f"Collecting {name}...")
        data[name] = json.loads(fn())
    return data


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
    print(f"BATCH 2 EVALUATION RESULTS")
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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _RECORDS_DIR / f"batch2_eval_{ts}.json"
    md_path = _RECORDS_DIR / f"batch2_eval_{ts}.md"

    record = {
        "timestamp": datetime.now().isoformat(),
        "commands": list(data.keys()),
        "summary": s,
        "failures": [c.to_dict() for c in report.checks if not c.passed],
        "all_checks": [c.to_dict() for c in report.checks],
        "llm_scores": llm_scores,
    }
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    with open(md_path, "w") as f:
        f.write(generate_markdown(report, llm_scores))

    print(f"\nSaved: {json_path}")
    print(f"       {md_path}")


if __name__ == "__main__":
    main()
