"""
Approach 6: Data Accuracy Verification

Unlike Approach 3 (narrative grounding — do labels match numbers?), this
approach verifies whether the NUMBERS THEMSELVES are correct:

  - Are computed fields (spreads, ratios, composite scores) arithmetically
    consistent with their component inputs?
  - Do the same metrics reported across different tools agree?
  - Do flags and thresholds match the actual data values?
  - Are values within historically plausible ranges?
  - Are period-over-period calculations (MoM, WoW, YoY) mathematically sound?

Inspired by macro_2's dual-source comparison and cross-validation patterns.

Usage:
    python data_accuracy_checker.py                        # Run against live agent
    python data_accuracy_checker.py --input report.json    # Run against saved output
"""

import sys, os, json, time, re, argparse, math
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ── Path setup ────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_TASTE_DIR = _THIS_DIR.parent
_TESTING_ROOT = _TASTE_DIR.parent
_RECORDS_DIR = _THIS_DIR / "records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)

_FA_ROOT = os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    str(Path(_TESTING_ROOT).parent.parent / "Financial_Agent")
)
sys.path.insert(0, _FA_ROOT)


# ═════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ═════════════════════════════════════════════════════════════════════

class AccuracyCheck:
    """A single data accuracy verification result."""
    def __init__(self, check_id: str, category: str, check_name: str,
                 passed: bool, expected, actual, detail: str,
                 severity: str = "medium", tolerance: float = 0.0):
        self.check_id = check_id
        self.category = category
        self.check_name = check_name
        self.passed = passed
        self.expected = expected
        self.actual = actual
        self.detail = detail
        self.severity = severity
        self.tolerance = tolerance
        self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        return {
            "check_id": self.check_id,
            "category": self.category,
            "check_name": self.check_name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
            "severity": self.severity,
            "tolerance": self.tolerance,
        }


class AccuracyReport:
    """Collects all accuracy check results."""
    def __init__(self):
        self.checks: list[AccuracyCheck] = []
        self.start_time = time.time()

    def add(self, check: AccuracyCheck):
        self.checks.append(check)
        icon = "\u2705" if check.passed else "\u274c"
        if not check.passed:
            print(f"  {icon} [{check.severity.upper():8s}] {check.check_name}")
            print(f"      Expected: {check.expected}")
            print(f"      Actual:   {check.actual}")
            print(f"      Detail:   {check.detail}")
        else:
            print(f"  {icon} [{check.severity.upper():8s}] {check.check_name}")

    @property
    def summary(self):
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        failed = [c for c in self.checks if not c.passed]
        by_category = defaultdict(lambda: {"passed": 0, "failed": 0})
        for c in self.checks:
            if c.passed:
                by_category[c.category]["passed"] += 1
            else:
                by_category[c.category]["failed"] += 1
        return {
            "total_checks": total,
            "passed": passed,
            "failed": total - passed,
            "accuracy_rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_failures": sum(1 for c in failed if c.severity in ("critical", "high")),
            "by_category": dict(by_category),
            "elapsed": f"{time.time() - self.start_time:.1f}s",
        }

    def to_dict(self):
        return {
            "summary": self.summary,
            "failures": [c.to_dict() for c in self.checks if not c.passed],
            "all_checks": [c.to_dict() for c in self.checks],
        }


# ═════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════

def _approx_eq(a, b, tolerance=0.02):
    """Check if two numbers are approximately equal (within tolerance ratio)."""
    if a is None or b is None:
        return a is None and b is None
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return abs(a - b) < 0.01
    return abs(a - b) / max(abs(a), abs(b)) <= tolerance


def _abs_close(a, b, threshold=0.5):
    """Check if two numbers are within an absolute threshold."""
    if a is None or b is None:
        return False
    return abs(a - b) <= threshold


def _safe_round(val, decimals=2):
    """Safely round a value."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return round(val, decimals)


def _extract_number_from_flag(flag_text: str) -> float | None:
    """Extract a numeric value from a flag string."""
    # Patterns: "+18 bps", "-99.86%", "6.05%", "$800B"
    patterns = [
        r'([+-]?\d+\.?\d*)\s*bps',
        r'([+-]?\d+\.?\d*)%',
        r'([+-]?\d+\.?\d*)\s*WoW',
        r'([+-]?\d+\.?\d*)\s*MoM',
        r'\$([+-]?\d+\.?\d*)',
        r'at\s+([+-]?\d+\.?\d*)',
        r'above\s+(\d+\.?\d*)',
        r'below\s+(\d+\.?\d*)',
        r'\((\d+\.?\d*)\)',
    ]
    for p in patterns:
        m = re.search(p, flag_text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 1: ARITHMETIC VERIFICATION
# Re-derive computed fields from their component inputs
# ═════════════════════════════════════════════════════════════════════

def check_arithmetic(report_data: dict, ar: AccuracyReport):
    """Verify computed values are arithmetically correct."""
    bond = report_data.get("analyze_bond_market", {})
    equity = report_data.get("analyze_equity_drivers", {})
    housing = report_data.get("analyze_housing_market", {})

    # ── A-01: 2s10s spread = 10Y - 2Y ──
    nominal = bond.get("yield_curve", {}).get("nominal_yields", {})
    y2 = nominal.get("2y", {}).get("latest_value")
    y10 = nominal.get("10y", {}).get("latest_value")
    reported_2s10s = bond.get("yield_curve", {}).get("spreads", {}).get(
        "2s10s", {}).get("latest_value")

    if y2 is not None and y10 is not None and reported_2s10s is not None:
        expected = _safe_round(y10 - y2, 2)
        ar.add(AccuracyCheck(
            "A-01", "arithmetic", "2s10s spread = 10Y - 2Y",
            _abs_close(expected, reported_2s10s, 0.02),
            expected, reported_2s10s,
            f"10Y ({y10}) - 2Y ({y2}) = {expected}, reported: {reported_2s10s}",
            severity="high",
        ))

    # ── A-02: Term premium = nominal_10y - real_10y - breakeven_10y ──
    tp = bond.get("term_premium", {})
    tp_comps = tp.get("components", {})
    tp_reported = tp.get("term_premium_pct")
    nom10 = tp_comps.get("nominal_10y")
    real10 = tp_comps.get("real_10y")
    be10 = tp_comps.get("breakeven_10y")

    if all(v is not None for v in [tp_reported, nom10, real10, be10]):
        expected = _safe_round(nom10 - real10 - be10, 2)
        ar.add(AccuracyCheck(
            "A-02", "arithmetic", "Term premium = nominal - real - breakeven",
            _abs_close(expected, tp_reported, 0.02),
            expected, tp_reported,
            f"{nom10} - {real10} - {be10} = {expected}, reported: {tp_reported}",
            severity="medium",
        ))

    # ── A-03: HY-IG differential = HY OAS - IG OAS ──
    cs = bond.get("credit_spreads", {})
    hy_bps = cs.get("high_yield_oas", {}).get("latest_value_bps")
    ig_bps = cs.get("ig_corporate_oas", {}).get("latest_value_bps")
    diff_reported = cs.get("hy_ig_differential", {}).get("value_bps")

    if all(v is not None for v in [hy_bps, ig_bps, diff_reported]):
        expected = hy_bps - ig_bps
        ar.add(AccuracyCheck(
            "A-03", "arithmetic", "HY-IG differential = HY OAS - IG OAS",
            expected == diff_reported,
            expected, diff_reported,
            f"HY ({hy_bps}bps) - IG ({ig_bps}bps) = {expected}, reported: {diff_reported}",
            severity="medium",
        ))

    # ── A-04: OAS pct ↔ bps consistency (value * 100 ≈ bps) ──
    for name, spread_data in cs.items():
        if not isinstance(spread_data, dict):
            continue
        pct_val = spread_data.get("latest_value")
        bps_val = spread_data.get("latest_value_bps")
        if pct_val is not None and bps_val is not None:
            expected_bps = round(pct_val * 100)
            ar.add(AccuracyCheck(
                "A-04", "arithmetic", f"{name}: pct * 100 = bps",
                abs(expected_bps - bps_val) <= 1,
                expected_bps, bps_val,
                f"{name}: {pct_val}% * 100 = {expected_bps}bps, reported: {bps_val}bps",
                severity="medium",
            ))

    # ── A-05: Permits-to-starts ratio ──
    starts = housing.get("starts_momentum", {}).get("latest_value")
    permits = housing.get("permits_pipeline", {}).get("latest_value")
    ratio_reported = housing.get("permits_pipeline", {}).get("permits_to_starts_ratio")

    if all(v is not None for v in [starts, permits, ratio_reported]) and starts > 0:
        expected = _safe_round(permits / starts, 2)
        ar.add(AccuracyCheck(
            "A-05", "arithmetic", "Permits/starts ratio",
            _abs_close(expected, ratio_reported, 0.02),
            expected, ratio_reported,
            f"{permits} / {starts} = {expected}, reported: {ratio_reported}",
            severity="low",
        ))

    # ── A-06: Monthly interest payment ≈ price * rate / 12 ──
    aff = housing.get("affordability", {})
    rate = aff.get("mortgage_rate_pct")
    price = aff.get("median_price_usd")
    payment_reported = aff.get("monthly_interest_payment_usd")

    if all(v is not None for v in [rate, price, payment_reported]) and rate > 0:
        # Simple interest approximation: price * (rate/100) / 12
        expected = round(price * (rate / 100) / 12)
        ar.add(AccuracyCheck(
            "A-06", "arithmetic", "Monthly interest payment ≈ price × rate / 12",
            abs(expected - payment_reported) <= 10,  # $10 tolerance
            expected, payment_reported,
            f"${price:,.0f} × {rate}% / 12 = ${expected:,}, reported: ${payment_reported:,}",
            severity="low",
        ))

    # ── A-07: Breakeven = nominal - real (TIPS spread identity) ──
    real_yields = bond.get("real_yields", {})
    breakevens = bond.get("breakevens", {})
    real_10y_val = real_yields.get("10y_real", {}).get("latest_value")
    nom_10y_val = nominal.get("10y", {}).get("latest_value")
    be_10y_val = breakevens.get("t10yie", {}).get("latest_value")

    if all(v is not None for v in [real_10y_val, nom_10y_val, be_10y_val]):
        expected_be = _safe_round(nom_10y_val - real_10y_val, 2)
        ar.add(AccuracyCheck(
            "A-07", "arithmetic", "10Y breakeven ≈ nominal_10Y - real_10Y",
            _abs_close(expected_be, be_10y_val, 0.05),
            expected_be, be_10y_val,
            f"{nom_10y_val} - {real_10y_val} = {expected_be}, reported BE: {be_10y_val}",
            severity="high",
        ))

    # Check 5Y as well
    real_5y_val = real_yields.get("5y_real", {}).get("latest_value")
    nom_5y_val = nominal.get("5y", {}).get("latest_value")
    be_5y_val = breakevens.get("t5yie", {}).get("latest_value")

    if all(v is not None for v in [real_5y_val, nom_5y_val, be_5y_val]):
        expected_be = _safe_round(nom_5y_val - real_5y_val, 2)
        ar.add(AccuracyCheck(
            "A-07b", "arithmetic", "5Y breakeven ≈ nominal_5Y - real_5Y",
            _abs_close(expected_be, be_5y_val, 0.05),
            expected_be, be_5y_val,
            f"{nom_5y_val} - {real_5y_val} = {expected_be}, reported BE: {be_5y_val}",
            severity="high",
        ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 2: CROSS-TOOL VALUE CONSISTENCY
# Same metric across different tools should agree
# ═════════════════════════════════════════════════════════════════════

def check_cross_tool_consistency(report_data: dict, ar: AccuracyReport):
    """Verify the same metric is reported consistently across tools."""
    scan = report_data.get("scan_all_indicators", {})
    regime = report_data.get("analyze_macro_regime", {})
    stress = report_data.get("analyze_financial_stress", {})
    equity = report_data.get("analyze_equity_drivers", {})
    bond = report_data.get("analyze_bond_market", {})

    # Build a lookup from scan data
    scan_values = {}
    for ind in scan.get("flagged_indicators", []):
        if isinstance(ind, dict):
            scan_values[ind.get("key", "")] = ind.get("latest")

    # ── X-01: VIX across scan, stress, equity ──
    vix_scan = scan_values.get("vix_move")  # VIX/MOVE combined key
    vix_stress = stress.get("components", {}).get("vix", {}).get("value")
    vix_equity = equity.get("volatility_regime", {}).get("vix")

    vix_values = {"stress": vix_stress, "equity": vix_equity}
    vix_ref = vix_stress or vix_equity  # Use as reference

    if vix_stress is not None and vix_equity is not None:
        ar.add(AccuracyCheck(
            "X-01", "cross_tool", "VIX: stress vs equity",
            _abs_close(vix_stress, vix_equity, 0.5),
            vix_stress, vix_equity,
            f"Stress VIX={vix_stress}, Equity VIX={vix_equity}",
            severity="medium",
        ))

    # ── X-02: HY OAS across macro, stress, equity, bond ──
    hy_macro = None
    credit_regime = regime.get("regimes", {}).get("credit", {})
    if isinstance(credit_regime, dict):
        hy_macro = credit_regime.get("value")
    hy_stress = stress.get("components", {}).get("hy_oas", {}).get("value")
    hy_equity_pct = equity.get("credit_equity_link", {}).get("hy_oas_pct")
    hy_equity_bps = equity.get("credit_equity_link", {}).get("hy_oas_bps")
    hy_bond_pct = bond.get("credit_spreads", {}).get("high_yield_oas", {}).get("latest_value")
    hy_bond_bps = bond.get("credit_spreads", {}).get("high_yield_oas", {}).get("latest_value_bps")

    # All pct values should match
    hy_pct_sources = {}
    if hy_macro is not None:
        hy_pct_sources["macro_regime"] = hy_macro
    if hy_stress is not None:
        hy_pct_sources["stress"] = hy_stress
    if hy_equity_pct is not None:
        hy_pct_sources["equity"] = hy_equity_pct
    if hy_bond_pct is not None:
        hy_pct_sources["bond"] = hy_bond_pct

    if len(hy_pct_sources) >= 2:
        vals = list(hy_pct_sources.values())
        all_match = all(_abs_close(v, vals[0], 0.05) for v in vals)
        ar.add(AccuracyCheck(
            "X-02", "cross_tool", "HY OAS pct across tools",
            all_match,
            f"all ≈ {vals[0]}", hy_pct_sources,
            f"HY OAS (pct) across tools: {hy_pct_sources}",
            severity="high",
        ))

    # ── X-03: Real yield 10Y across equity and bond ──
    ry_equity = equity.get("real_yield_impact", {}).get("real_yield_10y")
    ry_bond = bond.get("real_yields", {}).get("10y_real", {}).get("latest_value")

    if ry_equity is not None and ry_bond is not None:
        ar.add(AccuracyCheck(
            "X-03", "cross_tool", "Real yield 10Y: equity vs bond",
            _abs_close(ry_equity, ry_bond, 0.05),
            ry_equity, ry_bond,
            f"Equity real_yield_10y={ry_equity}, Bond 10y_real={ry_bond}",
            severity="medium",
        ))

    # ── X-04: Fed funds rate across macro and bond ──
    ff_macro = regime.get("regimes", {}).get("rates", {}).get("value") if isinstance(
        regime.get("regimes", {}).get("rates"), dict) else None
    ff_bond = bond.get("fed_policy", {}).get("effective_rate")

    if ff_macro is not None and ff_bond is not None:
        ar.add(AccuracyCheck(
            "X-04", "cross_tool", "Fed funds rate: macro vs bond",
            _abs_close(ff_macro, ff_bond, 0.05),
            ff_macro, ff_bond,
            f"Macro fed_funds={ff_macro}, Bond effective_rate={ff_bond}",
            severity="medium",
        ))

    # ── X-05: Nominal 10Y across equity and bond ──
    nom10_bond = bond.get("yield_curve", {}).get("nominal_yields", {}).get(
        "10y", {}).get("latest_value")
    tp_nom10 = bond.get("term_premium", {}).get("components", {}).get("nominal_10y")

    if nom10_bond is not None and tp_nom10 is not None:
        ar.add(AccuracyCheck(
            "X-05", "cross_tool", "Nominal 10Y: yield curve vs term premium",
            _abs_close(nom10_bond, tp_nom10, 0.01),
            nom10_bond, tp_nom10,
            f"Yield curve 10Y={nom10_bond}, Term premium comp={tp_nom10}",
            severity="low",
        ))

    # ── X-06: Credit spread direction across tools ──
    dir_equity = equity.get("credit_equity_link", {}).get("spread_direction")
    dir_bond = bond.get("credit_spreads", {}).get("high_yield_oas", {}).get("spread_direction")
    dir_macro = regime.get("regimes", {}).get("credit", {}).get("spread_direction") if isinstance(
        regime.get("regimes", {}).get("credit"), dict) else None

    directions = {}
    if dir_equity:
        directions["equity"] = dir_equity
    if dir_bond:
        directions["bond"] = dir_bond
    if dir_macro:
        directions["macro"] = dir_macro

    if len(directions) >= 2:
        vals = list(directions.values())
        all_match = all(v == vals[0] for v in vals)
        ar.add(AccuracyCheck(
            "X-06", "cross_tool", "Credit spread direction across tools",
            all_match,
            f"all = {vals[0]}", directions,
            f"Spread direction: {directions}",
            severity="medium",
        ))

    # ── X-07: Mortgage rate across tools ──
    mr_macro = regime.get("regimes", {}).get("housing", {}).get("mortgage_rate") if isinstance(
        regime.get("regimes", {}).get("housing"), dict) else None
    mr_housing = report_data.get("analyze_housing_market", {}).get(
        "affordability", {}).get("mortgage_rate_pct")

    if mr_macro is not None and mr_housing is not None:
        ar.add(AccuracyCheck(
            "X-07", "cross_tool", "Mortgage rate: macro vs housing",
            _abs_close(mr_macro, mr_housing, 0.1),
            mr_macro, mr_housing,
            f"Macro mortgage={mr_macro}, Housing mortgage={mr_housing}",
            severity="low",
        ))

    # ── X-08: HY OAS narrative classification across tools ──
    # This is crucial: different tools should use the same label for the same value
    class_equity = equity.get("credit_equity_link", {}).get("interpretation", "")
    class_bond_hy = bond.get("credit_spreads", {}).get("high_yield_oas", {}).get("stress_level", "")
    class_macro = regime.get("regimes", {}).get("credit", {}).get("classification", "") if isinstance(
        regime.get("regimes", {}).get("credit"), dict) else ""

    classifications = {}
    if class_equity:
        classifications["equity_interp"] = class_equity[:60]
    if class_bond_hy:
        classifications["bond_stress_level"] = class_bond_hy
    if class_macro:
        classifications["macro_classification"] = class_macro

    if len(classifications) >= 2:
        # Check for contradictory labels
        tight_words = {"tight", "supportive", "benign", "loose"}
        wide_words = {"wide", "widening", "stressed", "elevated"}
        has_tight = any(any(w in str(v).lower() for w in tight_words) for v in classifications.values())
        has_wide = any(any(w in str(v).lower() for w in wide_words) for v in classifications.values())

        ar.add(AccuracyCheck(
            "X-08", "cross_tool", "Credit classification consistency across tools",
            not (has_tight and has_wide),
            "consistent labels", classifications,
            f"Labels: {classifications}. Tight signals: {has_tight}, Wide signals: {has_wide}",
            severity="critical",
        ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 3: COMPOSITE SCORE DECOMPOSITION
# Verify weighted scores match their component inputs
# ═════════════════════════════════════════════════════════════════════

def check_composite_scores(report_data: dict, ar: AccuracyReport):
    """Verify composite scores can be re-derived from components."""
    stress = report_data.get("analyze_financial_stress", {})
    consumer = report_data.get("analyze_consumer_health", {})

    # ── S-01: Financial stress composite score ──
    stress_components = stress.get("components", {})
    stress_reported = stress.get("composite_score")

    if stress_components and stress_reported is not None:
        weighted_sum = 0.0
        total_weight = 0.0
        details = []

        for name, comp in stress_components.items():
            if not isinstance(comp, dict):
                continue
            score = comp.get("score", 0)
            weight = comp.get("weight", 0)
            value = comp.get("value")

            # Only count components with available data (non-null value or non-zero score)
            if value is not None or score > 0:
                weighted_sum += score * weight
                total_weight += weight
                details.append(f"{name}: {score}×{weight}={score * weight:.3f}")

        if total_weight > 0:
            expected = _safe_round(weighted_sum / total_weight, 2)
            ar.add(AccuracyCheck(
                "S-01", "composite_score", "Financial stress composite score decomposition",
                _abs_close(expected, stress_reported, 0.05),
                expected, stress_reported,
                f"Weighted sum={weighted_sum:.3f}, available weight={total_weight:.2f}, "
                f"rescaled={expected}. Components: {'; '.join(details)}",
                severity="high",
            ))

    # ── S-02: Consumer health composite score ──
    consumer_components = consumer.get("components", {})
    consumer_reported = consumer.get("composite_score")

    if consumer_components and consumer_reported is not None:
        weighted_sum = 0.0
        total_weight = 0.0
        details = []

        for name, comp in consumer_components.items():
            if not isinstance(comp, dict):
                continue
            score = comp.get("score", 0)
            weight = comp.get("weight", 0)
            value = comp.get("value")

            if value is not None or score > 0:
                weighted_sum += score * weight
                total_weight += weight
                details.append(f"{name}: {score}×{weight}={score * weight:.3f}")

        if total_weight > 0:
            expected = _safe_round(weighted_sum / total_weight, 2)
            ar.add(AccuracyCheck(
                "S-02", "composite_score", "Consumer health composite score decomposition",
                _abs_close(expected, consumer_reported, 0.05),
                expected, consumer_reported,
                f"Weighted sum={weighted_sum:.3f}, available weight={total_weight:.2f}, "
                f"rescaled={expected}. Components: {'; '.join(details)}",
                severity="high",
            ))

    # ── S-03: Late-cycle count matches firing signals ──
    late = report_data.get("detect_late_cycle_signals", {})
    reported_count = late.get("count")
    signals_list = late.get("signals_firing", [])

    if reported_count is not None and signals_list:
        actual_firing = sum(1 for s in signals_list
                          if isinstance(s, dict) and s.get("status") == "firing")
        ar.add(AccuracyCheck(
            "S-03", "composite_score", "Late-cycle count matches firing signals",
            reported_count == actual_firing,
            actual_firing, reported_count,
            f"Counted {actual_firing} 'firing' entries, reported count: {reported_count}",
            severity="medium",
        ))

    # ── S-04: Scan flagged_count matches actual flagged indicators ──
    scan = report_data.get("scan_all_indicators", {})
    reported_flagged = scan.get("flagged_count")
    flagged_list = scan.get("flagged_indicators", [])

    if reported_flagged is not None and flagged_list:
        actual_flagged = len(flagged_list)
        ar.add(AccuracyCheck(
            "S-04", "composite_score", "Scan flagged_count matches flagged list length",
            reported_flagged == actual_flagged,
            actual_flagged, reported_flagged,
            f"Flagged indicators list has {actual_flagged} entries, "
            f"reported flagged_count: {reported_flagged}",
            severity="low",
        ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 4: FLAG-TO-DATA ALIGNMENT
# Do threshold-based flags match the actual data values?
# ═════════════════════════════════════════════════════════════════════

def check_flag_alignment(report_data: dict, ar: AccuracyReport):
    """Verify that flags and threshold labels match actual data values."""
    scan = report_data.get("scan_all_indicators", {})

    # Define expected flag conditions
    flag_rules = {
        "ELEVATED_FEAR": ("vix", lambda v: v > 20, "VIX > 20"),
        "CALM_BONDS": ("move", lambda v: v < 80, "MOVE < 80"),
        "OIL_ELEVATED": ("crude_oil", lambda v: v > 80, "Oil > $80"),
        "EXPENSIVE_CAPE": ("shiller_cape", lambda v: v > 30, "CAPE > 30"),
        "ELEVATED_CAPE": ("shiller_cape", lambda v: v > 25, "CAPE > 25"),
        "ELEVATED_PE": ("sp500_fundamentals", lambda v: v > 25, "P/E > 25"),
        "TGA_HIGH": ("tga_balance", lambda v: v > 800000, "TGA > $800B"),
        "JPY_WEAK": ("jpy", lambda v: v > 155, "USD/JPY > 155"),
        "HIGH_SKEW": ("cboe_skew", lambda v: v > 140, "SKEW > 140"),
        "ELEVATED_SKEW": ("cboe_skew", lambda v: v > 130, "SKEW > 130"),
    }

    for ind in scan.get("flagged_indicators", []):
        if not isinstance(ind, dict):
            continue
        key = ind.get("key", "")
        value = ind.get("latest")
        flags = ind.get("top_flags", [])

        if value is None:
            continue

        for flag_text in flags:
            if not isinstance(flag_text, str):
                continue

            # Check each known flag rule
            for flag_name, (expected_key, condition, description) in flag_rules.items():
                if flag_name in flag_text and key == expected_key:
                    result = condition(value)
                    ar.add(AccuracyCheck(
                        "F-01", "flag_alignment",
                        f"Flag '{flag_name}' vs actual {key}={value}",
                        result,
                        f"{description} (True)", f"{key}={value} -> {result}",
                        f"Flag says '{flag_name}' which requires {description}. "
                        f"Actual value: {value}. Match: {result}",
                        severity="medium",
                    ))

    # ── F-02: Check 52-week proximity flags ──
    for ind in scan.get("flagged_indicators", []):
        if not isinstance(ind, dict):
            continue
        value = ind.get("latest")
        key = ind.get("key", "")
        flags = ind.get("top_flags", [])

        if value is None:
            continue

        for flag_text in flags:
            if not isinstance(flag_text, str):
                continue

            # Extract 52W reference value from parentheses: "Within X% of 52-week high (VALUE)"
            paren_match = re.search(r"\(([\d.]+)\)", flag_text)
            if not paren_match:
                continue
            ref_val = float(paren_match.group(1))
            if ref_val <= 0:
                continue

            # AT_52W_HIGH / NEAR_52W_HIGH: check percentage
            if "52W_HIGH" in flag_text:
                pct_from_high = (ref_val - value) / ref_val * 100
                is_at = "AT_52W_HIGH" in flag_text
                threshold = 1.0 if is_at else 3.0
                ar.add(AccuracyCheck(
                    "F-02", "flag_alignment",
                    f"52W high proximity: {key}",
                    pct_from_high <= threshold + 0.5,  # small tolerance
                    f"within {threshold}%", f"{pct_from_high:.2f}% from high",
                    f"{key}={value}, 52w high={ref_val}, gap={pct_from_high:.2f}%. "
                    f"Flag says {'AT' if is_at else 'NEAR'} (≤{threshold}%)",
                    severity="low",
                ))

            # AT_52W_LOW / NEAR_52W_LOW
            elif "52W_LOW" in flag_text:
                pct_from_low = (value - ref_val) / ref_val * 100
                is_at = "AT_52W_LOW" in flag_text
                threshold = 1.0 if is_at else 3.0
                ar.add(AccuracyCheck(
                    "F-02", "flag_alignment",
                    f"52W low proximity: {key}",
                    pct_from_low <= threshold + 0.5,
                    f"within {threshold}%", f"{pct_from_low:.2f}% from low",
                    f"{key}={value}, 52w low={ref_val}, gap={pct_from_low:.2f}%. "
                    f"Flag says {'AT' if is_at else 'NEAR'} (≤{threshold}%)",
                    severity="low",
                ))

    # ── F-03: Check for suspicious percentage moves ──
    for ind in scan.get("flagged_indicators", []):
        if not isinstance(ind, dict):
            continue
        key = ind.get("key", "")
        flags = ind.get("top_flags", [])
        daily_pct = ind.get("daily_pct")

        for flag_text in flags:
            if not isinstance(flag_text, str):
                continue

            # Look for implausible percentage moves (>50% daily, >200% weekly)
            if "LARGE_DAILY_MOVE" in flag_text:
                pct = _extract_number_from_flag(flag_text)
                if pct is not None and abs(pct) > 50:
                    ar.add(AccuracyCheck(
                        "F-03", "flag_alignment",
                        f"Implausible daily move: {key}",
                        False,
                        "daily move < 50%", f"{pct}%",
                        f"Flag claims {key} moved {pct}% in a single day. "
                        "This is extremely unlikely and suggests a data or calculation error.",
                        severity="critical",
                    ))

            if "LARGE_MONTHLY_MOVE" in flag_text:
                pct = _extract_number_from_flag(flag_text)
                if pct is not None and abs(pct) > 100:
                    ar.add(AccuracyCheck(
                        "F-03b", "flag_alignment",
                        f"Implausible monthly move: {key}",
                        False,
                        "monthly move < 100%", f"{pct}%",
                        f"Flag claims {key} moved {pct}% in a month. "
                        "This is highly suspicious for most financial instruments.",
                        severity="high",
                    ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 5: RANGE PLAUSIBILITY
# Are values within historically realistic bounds?
# ═════════════════════════════════════════════════════════════════════

PLAUSIBLE_RANGES = {
    # (metric_name, min, max, description)
    "vix": (8, 90, "VIX historically ranges 9-80 (2008 peak ~80)"),
    "dxy": (70, 130, "DXY historically ranges 72-120"),
    "fed_funds_rate": (0, 7, "Fed funds rate 0-6.5% in modern era"),
    "cpi_yoy_pct": (-3, 15, "CPI YoY -2% to 14.8% (1980 peak)"),
    "unemployment_pct": (2, 15, "Unemployment 2.5-14.7% (2020 peak)"),
    "hy_oas_bps": (200, 2500, "HY OAS 230-2000 bps historically"),
    "ig_oas_bps": (40, 600, "IG OAS 45-600 bps historically"),
    "real_yield_10y": (-2, 5, "10Y real yield -1.5% to 4%"),
    "stress_score": (0, 10, "Composite stress score 0-10"),
    "consumer_health_score": (0, 10, "Consumer health score 0-10"),
    "late_cycle_count": (0, 13, "Late-cycle signals 0-13"),
    "cape_ratio": (10, 50, "Shiller CAPE ratio 10-50"),
    "mortgage_rate": (2, 10, "Mortgage rate 2-10% in modern era"),
    "housing_starts_k": (400, 2500, "Housing starts 400K-2200K SAAR"),
    "existing_sales": (1000000, 8000000, "Existing sales 1M-7M SAAR"),
    "savings_rate": (0, 35, "Personal savings rate 0-33%"),
    "ism_pmi": (30, 70, "ISM PMI 30-65 historically"),
    "breakeven_inflation": (0, 5, "Breakeven inflation 0-3.5% typically"),
}


def check_range_plausibility(report_data: dict, ar: AccuracyReport):
    """Verify values are within historically plausible ranges."""
    stress = report_data.get("analyze_financial_stress", {})
    regime = report_data.get("analyze_macro_regime", {})
    equity = report_data.get("analyze_equity_drivers", {})
    bond = report_data.get("analyze_bond_market", {})
    consumer = report_data.get("analyze_consumer_health", {})
    housing = report_data.get("analyze_housing_market", {})
    late = report_data.get("detect_late_cycle_signals", {})

    checks = []

    # VIX
    vix = stress.get("components", {}).get("vix", {}).get("value")
    if vix is not None:
        checks.append(("vix", vix))

    # Fed funds
    ff = bond.get("fed_policy", {}).get("effective_rate")
    if ff is not None:
        checks.append(("fed_funds_rate", ff))

    # CPI
    cpi = regime.get("inflation_detail", {}).get("cpi", {}).get("latest_value") if isinstance(
        regime.get("inflation_detail", {}).get("cpi"), dict) else None
    if cpi is not None:
        checks.append(("cpi_yoy_pct", cpi))

    # Unemployment
    emp = regime.get("regimes", {}).get("employment", {})
    unemp = emp.get("value") if isinstance(emp, dict) else None
    if unemp is not None:
        checks.append(("unemployment_pct", unemp))

    # HY OAS
    hy_bps = bond.get("credit_spreads", {}).get("high_yield_oas", {}).get("latest_value_bps")
    if hy_bps is not None:
        checks.append(("hy_oas_bps", hy_bps))

    # IG OAS
    ig_bps = bond.get("credit_spreads", {}).get("ig_corporate_oas", {}).get("latest_value_bps")
    if ig_bps is not None:
        checks.append(("ig_oas_bps", ig_bps))

    # Real yield 10Y
    ry = bond.get("real_yields", {}).get("10y_real", {}).get("latest_value")
    if ry is not None:
        checks.append(("real_yield_10y", ry))

    # Composite scores
    ss = stress.get("composite_score")
    if ss is not None:
        checks.append(("stress_score", ss))

    cs = consumer.get("composite_score")
    if cs is not None:
        checks.append(("consumer_health_score", cs))

    # Late-cycle
    lc = late.get("count")
    if lc is not None:
        checks.append(("late_cycle_count", lc))

    # Mortgage rate
    mr = housing.get("affordability", {}).get("mortgage_rate_pct")
    if mr is not None:
        checks.append(("mortgage_rate", mr))

    # Housing starts
    hs = housing.get("starts_momentum", {}).get("latest_value")
    if hs is not None:
        checks.append(("housing_starts_k", hs))

    # Existing sales
    es = housing.get("sales_trend", {}).get("latest_value")
    if es is not None:
        checks.append(("existing_sales", es))

    # ISM PMI
    ism = regime.get("regimes", {}).get("growth", {}).get("value") if isinstance(
        regime.get("regimes", {}).get("growth"), dict) else None
    if ism is not None:
        checks.append(("ism_pmi", ism))

    # Savings rate
    sr = consumer.get("components", {}).get("savings_rate", {}).get("value")
    if sr is not None:
        checks.append(("savings_rate", sr))

    # Breakeven inflation
    be = bond.get("breakevens", {}).get("t10yie", {}).get("latest_value")
    if be is not None:
        checks.append(("breakeven_inflation", be))

    # Run all range checks
    for metric_name, value in checks:
        if metric_name in PLAUSIBLE_RANGES:
            lo, hi, desc = PLAUSIBLE_RANGES[metric_name]
            in_range = lo <= value <= hi
            ar.add(AccuracyCheck(
                "R-01", "range_plausibility",
                f"{metric_name} = {value} in plausible range [{lo}, {hi}]",
                in_range,
                f"[{lo}, {hi}]", value,
                f"{desc}. Actual: {value}",
                severity="high" if not in_range else "low",
            ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 6: INTERNAL SIGNAL CONTRADICTION
# Within a single tool, contradictory signals or classifications
# ═════════════════════════════════════════════════════════════════════

def check_internal_contradictions(report_data: dict, ar: AccuracyReport):
    """Find contradictions within individual tool outputs."""

    # ── I-01: Bond signals: BREAKEVEN_RISING + BREAKEVEN_FALLING ──
    bond = report_data.get("analyze_bond_market", {})
    bond_signals = set(bond.get("signals", []))

    if "BREAKEVEN_RISING" in bond_signals and "BREAKEVEN_FALLING" in bond_signals:
        ar.add(AccuracyCheck(
            "I-01", "internal_contradiction",
            "Bond: BREAKEVEN_RISING and BREAKEVEN_FALLING simultaneously",
            False,
            "one or the other", "both present",
            "BREAKEVEN_RISING and BREAKEVEN_FALLING are mutually exclusive. "
            "Check which breakeven series (5Y, 10Y, 5Y5Y) drives each signal.",
            severity="critical",
        ))
    else:
        ar.add(AccuracyCheck(
            "I-01", "internal_contradiction",
            "Bond: no contradictory breakeven signals",
            True, "consistent", bond_signals,
            "Breakeven signals are internally consistent.",
            severity="critical",
        ))

    # ── I-02: Macro regime: CREDIT_LOOSE signal + credit regime "tight" ──
    regime = report_data.get("analyze_macro_regime", {})
    macro_signals = set(regime.get("signals", []))
    credit_class = ""
    if isinstance(regime.get("regimes", {}).get("credit"), dict):
        credit_class = regime["regimes"]["credit"].get("classification", "")

    has_loose = "CREDIT_LOOSE" in macro_signals
    has_tight_class = credit_class.lower() == "tight"

    if has_loose and has_tight_class:
        ar.add(AccuracyCheck(
            "I-02", "internal_contradiction",
            "Macro: CREDIT_LOOSE signal vs credit regime 'tight'",
            False,
            "consistent classification", f"signal=CREDIT_LOOSE, regime=tight",
            "The macro tool emits CREDIT_LOOSE as a signal but classifies the "
            "credit regime as 'tight'. These are contradictory.",
            severity="critical",
        ))
    else:
        ar.add(AccuracyCheck(
            "I-02", "internal_contradiction",
            "Macro: credit signal vs regime classification",
            True, "consistent",
            f"signal_loose={has_loose}, class_tight={has_tight_class}",
            "Credit signal and regime classification are consistent.",
            severity="critical",
        ))

    # ── I-03: Equity: CREDIT_TAILWIND signal vs "tight spreads" narrative ──
    equity = report_data.get("analyze_equity_drivers", {})
    eq_signals = set(equity.get("signals", []))
    cel_interp = equity.get("credit_equity_link", {}).get("interpretation", "")
    hy_bps = equity.get("credit_equity_link", {}).get("hy_oas_bps")

    if "CREDIT_TAILWIND" in eq_signals and hy_bps and hy_bps > 300:
        ar.add(AccuracyCheck(
            "I-03", "internal_contradiction",
            "Equity: CREDIT_TAILWIND signal at HY OAS > 300bps",
            False,
            "tailwind at tight spreads (<300bps)", f"HY OAS = {hy_bps}bps",
            "CREDIT_TAILWIND implies spreads are tightening (improving), but "
            f"HY OAS at {hy_bps}bps is wide. A tailwind at wide spreads is dubious.",
            severity="high",
        ))

    # ── I-04: Housing: SALES_PLUNGING + NO_WARNING leading indicator ──
    housing = report_data.get("analyze_housing_market", {})
    h_signals = set(housing.get("signals", []))
    leading = housing.get("leading_indicator_signal", {}).get("signal", "")

    if ("SALES_PLUNGING" in h_signals or "EXISTING_SALES_PLUNGING" in h_signals) and leading == "NO_WARNING":
        ar.add(AccuracyCheck(
            "I-04", "internal_contradiction",
            "Housing: SALES_PLUNGING + NO_WARNING leading indicator",
            False,
            "plunging sales should trigger warning", f"signal={h_signals}, leading={leading}",
            "Existing home sales are plunging but the leading indicator model says "
            "'NO_WARNING'. Sales collapse IS a leading indicator of economic weakness.",
            severity="high",
        ))

    # ── I-05: Consumer health label vs score range ──
    consumer = report_data.get("analyze_consumer_health", {})
    ch_score = consumer.get("composite_score")
    ch_level = consumer.get("consumer_health_level", "")

    if ch_score is not None and ch_level:
        # The score should align with the label
        score_ranges = {
            "critical": (0, 2.5), "stressed": (2.5, 4.5),
            "cautious": (4, 5.5), "stable": (5, 7),
            "healthy": (7, 10),
        }
        expected_range = score_ranges.get(ch_level.lower())
        if expected_range:
            in_range = expected_range[0] <= ch_score <= expected_range[1]
            ar.add(AccuracyCheck(
                "I-05", "internal_contradiction",
                f"Consumer health '{ch_level}' vs score {ch_score}",
                in_range,
                f"score in [{expected_range[0]}, {expected_range[1]}]", ch_score,
                f"Label '{ch_level}' implies score range {expected_range}, actual: {ch_score}",
                severity="high",
            ))

    # ── I-06: Stress level label vs composite score ──
    stress = report_data.get("analyze_financial_stress", {})
    s_score = stress.get("composite_score")
    s_level = stress.get("stress_level", "")

    if s_score is not None and s_level:
        stress_ranges = {
            "low": (0, 2.5), "moderate": (2.5, 5),
            "elevated": (5, 7), "high": (7, 9),
            "extreme": (9, 10),
        }
        expected_range = stress_ranges.get(s_level.lower())
        if expected_range:
            in_range = expected_range[0] <= s_score <= expected_range[1]
            ar.add(AccuracyCheck(
                "I-06", "internal_contradiction",
                f"Stress level '{s_level}' vs score {s_score}",
                in_range,
                f"score in [{expected_range[0]}, {expected_range[1]}]", s_score,
                f"Label '{s_level}' implies score range {expected_range}, actual: {s_score}",
                severity="high",
            ))

    # ── I-07: Housing cycle phase vs signals ──
    h_phase = housing.get("housing_cycle_phase", {})
    phase = h_phase.get("phase") if isinstance(h_phase, dict) else str(h_phase)
    if isinstance(phase, str) and phase.lower() == "mixed":
        distress_signals = {"SALES_PLUNGING", "AFFORDABILITY_STRESSED",
                            "EXISTING_SALES_PLUNGING"} & h_signals
        if len(distress_signals) >= 2:
            ar.add(AccuracyCheck(
                "I-07", "internal_contradiction",
                "Housing: 'mixed' phase with multiple distress signals",
                False,
                "distressed or declining phase", f"phase=mixed, signals={distress_signals}",
                f"Multiple distress signals ({distress_signals}) firing but cycle phase "
                "is labeled 'mixed'. Should be 'declining' or 'distressed'.",
                severity="medium",
            ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 7: DATA FRESHNESS & TEMPORAL CONSISTENCY
# ═════════════════════════════════════════════════════════════════════

def check_temporal_consistency(report_data: dict, ar: AccuracyReport):
    """Verify all timestamps are recent and consistent across tools."""
    timestamps = {}

    for tool_name, data in report_data.items():
        if not isinstance(data, dict):
            continue
        ts = data.get("timestamp") or data.get("as_of") or data.get("scan_time")
        if ts:
            timestamps[tool_name] = str(ts)[:10]  # Just date portion

    # ── T-01: All tools report the same date ──
    unique_dates = set(timestamps.values())
    if len(unique_dates) > 1:
        ar.add(AccuracyCheck(
            "T-01", "temporal", "All tools report same date",
            False,
            "single date", timestamps,
            f"Tools report {len(unique_dates)} different dates: {timestamps}",
            severity="medium",
        ))
    elif len(unique_dates) == 1:
        ar.add(AccuracyCheck(
            "T-01", "temporal", "All tools report same date",
            True,
            unique_dates.pop(), timestamps,
            "All tool timestamps are consistent.",
            severity="medium",
        ))

    # ── T-02: Check for 'unavailable' data that might be stale ──
    unavailable_count = 0
    unavailable_details = []
    for tool_name, data in report_data.items():
        if not isinstance(data, dict):
            continue
        _count_unavailable(data, tool_name, "", unavailable_details)

    unavailable_count = len(unavailable_details)
    if unavailable_count > 3:
        ar.add(AccuracyCheck(
            "T-02", "temporal", "Data availability (unavailable fields)",
            False,
            "< 3 unavailable fields", f"{unavailable_count} unavailable",
            f"Found {unavailable_count} 'data_unavailable' or null fields: "
            f"{unavailable_details[:5]}...",
            severity="medium",
        ))
    else:
        ar.add(AccuracyCheck(
            "T-02", "temporal", "Data availability",
            True,
            "< 3 unavailable", f"{unavailable_count} unavailable",
            f"{unavailable_count} unavailable fields found (acceptable).",
            severity="medium",
        ))


# ═════════════════════════════════════════════════════════════════════
# CATEGORY 8: SYNTHESIS STRUCTURAL CHECKS
# Verify macro_synthesis output structure and internal consistency
# ═════════════════════════════════════════════════════════════════════

def check_synthesis(report_data: dict, ar: AccuracyReport):
    """Verify synthesis output structural integrity and value consistency."""
    synthesis = report_data.get("synthesize_macro_view", {})
    if not synthesis:
        return  # synthesis not included in this run

    # ── SY-01: Recommendations structure ──
    recs = synthesis.get("recommendations", {})
    if isinstance(recs, dict):
        required_keys = {"equity_positioning", "conviction"}
        has_keys = required_keys & set(recs.keys())
        ar.add(AccuracyCheck(
            "SY-01", "synthesis", "Recommendations has required fields",
            has_keys == required_keys,
            required_keys, has_keys,
            f"Expected keys: {required_keys}, found: {has_keys}",
            severity="medium",
        ))

    # ── SY-02: Contradiction list items have required fields ──
    contradictions = synthesis.get("contradictions", [])
    if isinstance(contradictions, list) and len(contradictions) > 0:
        bad_items = []
        for i, c in enumerate(contradictions):
            if not isinstance(c, dict):
                bad_items.append(f"item {i}: not a dict")
                continue
            needed = {"observation", "contradiction"}
            missing = needed - set(c.keys())
            if missing:
                bad_items.append(f"item {i} missing: {missing}")

        ar.add(AccuracyCheck(
            "SY-02", "synthesis", "Contradiction items have required fields",
            len(bad_items) == 0,
            "all items well-formed", bad_items or "all OK",
            f"Checked {len(contradictions)} contradictions, {len(bad_items)} malformed",
            severity="medium",
        ))

    # ── SY-03: Cause-effect chains have 4 required fields ──
    chains = synthesis.get("cause_effect_chains", [])
    if isinstance(chains, list) and len(chains) > 0:
        chain_fields = {"observation", "because", "so_what", "portfolio_action"}
        bad_chains = []
        for i, ch in enumerate(chains):
            if not isinstance(ch, dict):
                bad_chains.append(f"chain {i}: not a dict")
                continue
            missing = chain_fields - set(ch.keys())
            if missing:
                bad_chains.append(f"chain {i} missing: {missing}")

        ar.add(AccuracyCheck(
            "SY-03", "synthesis", "Cause-effect chains have all 4 fields",
            len(bad_chains) == 0,
            "all chains well-formed", bad_chains or "all OK",
            f"Checked {len(chains)} chains, {len(bad_chains)} malformed",
            severity="medium",
        ))

    # ── SY-04: Historical analogues have required structure ──
    analogues = synthesis.get("historical_analogues", [])
    if isinstance(analogues, list) and len(analogues) > 0:
        analogue_fields = {"period", "similarity_score"}
        bad_analogues = []
        for i, a in enumerate(analogues):
            if not isinstance(a, dict):
                bad_analogues.append(f"analogue {i}: not a dict")
                continue
            missing = analogue_fields - set(a.keys())
            if missing:
                bad_analogues.append(f"analogue {i} missing: {missing}")
            # Similarity score should be 0-1
            sim = a.get("similarity_score")
            if isinstance(sim, (int, float)) and not (0 <= sim <= 1):
                bad_analogues.append(f"analogue {i}: similarity_score={sim} out of [0,1]")

        ar.add(AccuracyCheck(
            "SY-04", "synthesis", "Historical analogues well-formed",
            len(bad_analogues) == 0,
            "all analogues valid", bad_analogues or "all OK",
            f"Checked {len(analogues)} analogues, {len(bad_analogues)} issues",
            severity="low",
        ))

    # ── SY-05: Executive summary present and non-empty ──
    exec_summary = synthesis.get("executive_summary", "")
    ar.add(AccuracyCheck(
        "SY-05", "synthesis", "Executive summary present and non-empty",
        isinstance(exec_summary, str) and len(exec_summary) > 20,
        "> 20 chars", f"{len(exec_summary) if isinstance(exec_summary, str) else 'not a string'} chars",
        "Executive summary should be a substantive text string.",
        severity="medium",
    ))

    # ── SY-06: Conviction level is valid enum ──
    conviction = recs.get("conviction", "") if isinstance(recs, dict) else ""
    valid_convictions = {"HIGH", "MODERATE", "LOW", "VERY_LOW"}
    if conviction:
        ar.add(AccuracyCheck(
            "SY-06", "synthesis", "Conviction is valid enum",
            conviction.upper() in valid_convictions,
            valid_convictions, conviction,
            f"Conviction '{conviction}' should be one of {valid_convictions}",
            severity="low",
        ))


def _count_unavailable(data, tool_name, prefix, results):
    """Recursively count 'data_unavailable' fields."""
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, str) and "unavailable" in v.lower():
                results.append(f"{tool_name}/{path}")
            elif isinstance(v, dict) and v.get("status") == "data_unavailable":
                results.append(f"{tool_name}/{path}")
            elif v is None:
                results.append(f"{tool_name}/{path}=null")
            elif isinstance(v, dict):
                _count_unavailable(v, tool_name, path, results)


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def collect_full_report(include_synthesis: bool = False) -> dict:
    """Execute all 8 /full_report tools.

    Args:
        include_synthesis: If True, also run synthesize_macro_view() and
            include its output under the 'synthesize_macro_view' key.
    """
    from tools.macro_data import scan_all_indicators
    from tools.macro_market_analysis import (
        analyze_macro_regime, analyze_bond_market, analyze_equity_drivers)
    from tools.market_regime_enhanced import (
        analyze_financial_stress, detect_late_cycle_signals)
    from tools.consumer_housing_analysis import (
        analyze_consumer_health, analyze_housing_market)

    print("  Collecting /full_report data...")
    tools = [
        ("scan_all_indicators", lambda: scan_all_indicators("short")),
        ("analyze_macro_regime", analyze_macro_regime),
        ("analyze_financial_stress", analyze_financial_stress),
        ("detect_late_cycle_signals", detect_late_cycle_signals),
        ("analyze_equity_drivers", lambda: analyze_equity_drivers("both")),
        ("analyze_bond_market", analyze_bond_market),
        ("analyze_consumer_health", analyze_consumer_health),
        ("analyze_housing_market", analyze_housing_market),
    ]
    report = {}
    for name, fn in tools:
        report[name] = json.loads(fn())
        print(f"    {name}: OK")

    if include_synthesis:
        from tools.macro_synthesis import synthesize_macro_view
        report["synthesize_macro_view"] = json.loads(synthesize_macro_view())
        print(f"    synthesize_macro_view: OK")

    return report


# ═════════════════════════════════════════════════════════════════════
# RECORD KEEPING
# ═════════════════════════════════════════════════════════════════════

def save_record(ar: AccuracyReport, report_data: dict) -> Path:
    """Save data accuracy results to records directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    record = {
        "timestamp": datetime.now().isoformat(),
        "input_tools": list(report_data.keys()),
        "results": ar.to_dict(),
    }
    json_path = _RECORDS_DIR / f"data_accuracy_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    print(f"\n  Record saved: {json_path}")

    md = generate_markdown_report(ar)
    md_path = _RECORDS_DIR / f"data_accuracy_{ts}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Markdown: {md_path}")

    return json_path


def generate_markdown_report(ar: AccuracyReport) -> str:
    """Generate markdown report from accuracy check results."""
    s = ar.summary
    failures = [c for c in ar.checks if not c.passed]

    lines = [
        "# Data Accuracy Verification Report",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Checks**: {s['total_checks']} | **Passed**: {s['passed']} | "
        f"**Failed**: {s['failed']} | **Rate**: {s['accuracy_rate']}",
        "",
    ]

    # Category breakdown
    lines.append("## Results by Category\n")
    lines.append("| Category | Passed | Failed | Rate |")
    lines.append("|----------|--------|--------|------|")
    for cat, counts in sorted(s["by_category"].items()):
        total = counts["passed"] + counts["failed"]
        rate = f"{counts['passed']/total*100:.0f}%" if total else "N/A"
        lines.append(f"| {cat} | {counts['passed']} | {counts['failed']} | {rate} |")

    # Failures
    if failures:
        lines.append(f"\n## Failures ({len(failures)})\n")
        for c in failures:
            sev_icon = {"critical": "\U0001f534", "high": "\U0001f7e0",
                        "medium": "\U0001f7e1", "low": "\U0001f535"}.get(c.severity, "\u26aa")
            lines.append(f"### {sev_icon} {c.check_id}: {c.check_name} [{c.severity.upper()}]\n")
            lines.append(f"- **Expected**: {c.expected}")
            lines.append(f"- **Actual**: {c.actual}")
            lines.append(f"- **Detail**: {c.detail}")
            lines.append("")

    # All checks table
    lines.append("\n## All Checks\n")
    lines.append("| ID | Category | Check | Status | Severity |")
    lines.append("|----|----------|-------|--------|----------|")
    for c in ar.checks:
        icon = "\u2705" if c.passed else "\u274c"
        name = c.check_name[:60] + "..." if len(c.check_name) > 60 else c.check_name
        lines.append(f"| {c.check_id} | {c.category} | {name} | {icon} | {c.severity} |")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def run_all_checks(report_data: dict) -> AccuracyReport:
    """Run all data accuracy verification categories."""
    ar = AccuracyReport()

    print(f"\n{'─' * 70}")
    print("  Category 1: Arithmetic Verification")
    print(f"{'─' * 70}")
    check_arithmetic(report_data, ar)

    print(f"\n{'─' * 70}")
    print("  Category 2: Cross-Tool Value Consistency")
    print(f"{'─' * 70}")
    check_cross_tool_consistency(report_data, ar)

    print(f"\n{'─' * 70}")
    print("  Category 3: Composite Score Decomposition")
    print(f"{'─' * 70}")
    check_composite_scores(report_data, ar)

    print(f"\n{'─' * 70}")
    print("  Category 4: Flag-to-Data Alignment")
    print(f"{'─' * 70}")
    check_flag_alignment(report_data, ar)

    print(f"\n{'─' * 70}")
    print("  Category 5: Range Plausibility")
    print(f"{'─' * 70}")
    check_range_plausibility(report_data, ar)

    print(f"\n{'─' * 70}")
    print("  Category 6: Internal Signal Contradictions")
    print(f"{'─' * 70}")
    check_internal_contradictions(report_data, ar)

    print(f"\n{'─' * 70}")
    print("  Category 7: Temporal Consistency & Freshness")
    print(f"{'─' * 70}")
    check_temporal_consistency(report_data, ar)

    if "synthesize_macro_view" in report_data:
        print(f"\n{'─' * 70}")
        print("  Category 8: Synthesis Structural Checks")
        print(f"{'─' * 70}")
        check_synthesis(report_data, ar)

    return ar


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Approach 6: Data Accuracy Verification")
    parser.add_argument("--input", type=str,
                        help="Path to saved full_report JSON")
    parser.add_argument("--synthesis", action="store_true",
                        help="Also run synthesize_macro_view() and check its structure")
    args = parser.parse_args()

    print("=" * 70)
    print("  APPROACH 6: DATA ACCURACY VERIFICATION")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if args.input:
        with open(args.input) as f:
            report_data = json.load(f)
        print(f"\n  Loaded from: {args.input}")
    else:
        report_data = collect_full_report(include_synthesis=args.synthesis)

    ar = run_all_checks(report_data)

    # Summary
    s = ar.summary
    print(f"\n{'=' * 70}")
    print(f"  DATA ACCURACY RESULTS")
    print(f"  Checks: {s['total_checks']} | Passed: {s['passed']} | "
          f"Failed: {s['failed']} | Rate: {s['accuracy_rate']}")
    if s['critical_failures'] > 0:
        print(f"  \u26a0\ufe0f  Critical/High failures: {s['critical_failures']}")
    print(f"\n  By Category:")
    for cat, counts in sorted(s["by_category"].items()):
        total = counts["passed"] + counts["failed"]
        rate = f"{counts['passed']/total*100:.0f}%" if total else "N/A"
        icon = "\u2705" if counts["failed"] == 0 else "\u274c"
        print(f"    {icon} {cat}: {counts['passed']}/{total} ({rate})")
    print(f"{'=' * 70}")

    save_record(ar, report_data)
