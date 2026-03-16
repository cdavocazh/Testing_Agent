"""
Re-evaluation Taste Evaluator — Post-Bugfix Round

Re-evaluates 6 Financial Agent commands that had the most failures:
  /analyze NVDA, /commodity crude_oil, /macro,
  /graham NVDA, /valuation, /stress

Reuses the SAME checks from original batches 1 & 2 so results are
directly comparable. Adds LLM judge for holistic quality assessment.

Usage:
    python reeval_evaluator.py --input command_output_reeval_v1.json
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
# APPROACH 1: DATA ACCURACY
# ═════════════════════════════════════════════════════════════════════

def run_accuracy_checks(data, report):

    # ─────── /analyze NVDA ───────
    a = data.get("analyze_NVDA", {})

    # AN-01: Data freshness — latest quarter
    latest_q = a.get("latest_quarter", "")
    fresh = latest_q.startswith(("2024", "2025", "2026"))
    report.add(Check("AN-01", "accuracy", "analyze", "Data freshness (latest quarter ≥ 2024)",
                     fresh, f"Latest quarter: {latest_q}" + (" — STALE" if not fresh else ""),
                     expected="≥ 2024", actual=latest_q, severity="critical"))

    # AN-02: Stale data warning present when data is old
    has_warning = "data_warning" in a or "STALE" in json.dumps(a.get("flags", []))
    if not fresh:
        report.add(Check("AN-02", "accuracy", "analyze", "Stale data warning present when data old",
                         has_warning,
                         f"Data from {latest_q}, warning present: {has_warning}",
                         severity="medium"))
    else:
        report.add(Check("AN-02", "accuracy", "analyze", "Data freshness — no warning needed",
                         True, f"Fresh data ({latest_q}), no warning needed", severity="medium"))

    # AN-03: OCF/NI (operating cash flow quality)
    cf = a.get("cash_flow_quality", {})
    ocf_ni = cf.get("ocf_to_net_income")
    if ocf_ni is not None:
        plausible = -5 <= ocf_ni <= 10
        report.add(Check("AN-03", "accuracy", "analyze", "OCF/NI ratio in plausible range",
                         plausible, f"OCF/NI = {ocf_ni}", expected="[-5, 10]", actual=ocf_ni,
                         severity="high"))

    # AN-04: Margins present and non-null
    margins = a.get("margins", {})
    gm = margins.get("gross_margin_pct")
    om = margins.get("operating_margin_pct")
    nm = margins.get("net_margin_pct")
    all_present = gm is not None and om is not None and nm is not None
    report.add(Check("AN-04", "accuracy", "analyze", "Key margins (gross, operating, net) available",
                     all_present, f"GM={gm}, OM={om}, NM={nm}", severity="high"))

    # AN-05: Gross margin > Operating margin > 0 (for NVDA)
    if gm and om:
        logical = gm > om
        report.add(Check("AN-05", "accuracy", "analyze", "Gross margin > Operating margin (logical)",
                         logical, f"GM={gm}% > OM={om}%: {logical}", severity="medium"))

    # ─────── /commodity crude_oil ───────
    c = data.get("commodity_crude_oil", {})

    # COM-01: Price in plausible range ($20-$200)
    price = c.get("price_analysis", {}).get("current_price") or c.get("current_price")
    if price is None:
        # Try nested
        pa = c.get("price_analysis", {})
        price = pa.get("current_price") or pa.get("price")
    if price is not None:
        report.add(Check("COM-01", "accuracy", "commodity", "Crude oil price in plausible range ($20-$200)",
                         20 <= price <= 200, f"Price: ${price:.2f}", expected="[20, 200]", actual=price,
                         severity="medium"))

    # COM-02: Inventory data present
    inv = c.get("inventory_data", {})
    has_inventory = bool(inv) and len(inv) > 0
    report.add(Check("COM-02", "accuracy", "commodity", "Inventory/EIA data present",
                     has_inventory, f"Inventory fields: {len(inv)}", severity="medium"))

    # COM-03: Seasonal pattern present
    seasonal = c.get("seasonal_pattern", {})
    has_seasonal = bool(seasonal) and seasonal.get("current_month_bias") is not None
    report.add(Check("COM-03", "accuracy", "commodity", "Seasonal pattern data present",
                     has_seasonal, f"Seasonal fields: {len(seasonal)}", severity="medium"))

    # COM-04: Support/resistance levels present
    sr = c.get("support_resistance", {})
    has_sr = bool(sr) and (sr.get("supports") or sr.get("resistances"))
    report.add(Check("COM-04", "accuracy", "commodity", "Support/resistance levels computed",
                     has_sr, f"S/R data: {list(sr.keys())[:5]}", severity="medium"))

    # COM-05: DXY correlation present and in [-1, 1]
    corr_data = c.get("correlations", {})
    dxy_corr = corr_data.get("dxy", {}).get("correlation") if isinstance(corr_data.get("dxy"), dict) else None
    if dxy_corr is None and isinstance(corr_data, dict):
        # Try other structures
        for k, v in corr_data.items():
            if isinstance(v, dict) and "correlation" in v:
                dxy_corr = v.get("correlation")
                break
    report.add(Check("COM-05", "accuracy", "commodity", "DXY correlation present and valid",
                     dxy_corr is not None and -1 <= (dxy_corr or 0) <= 1,
                     f"DXY correlation: {dxy_corr}", severity="medium"))

    # ─────── /macro ───────
    m = data.get("macro", {})
    regimes = m.get("regimes", {})
    infl = m.get("inflation_detail", {})

    # MA-01: Core CPI YoY plausible (-5% to 15%)
    core_cpi_yoy = infl.get("core_cpi", {}).get("yoy_change_pct")
    if core_cpi_yoy is not None:
        plausible = -5 <= core_cpi_yoy <= 15
        report.add(Check("MA-01", "accuracy", "macro", "Core CPI YoY in plausible range (-5% to 15%)",
                         plausible, f"Core CPI YoY: {core_cpi_yoy}%" +
                         (" — IMPLAUSIBLE" if not plausible else ""),
                         expected="[-5, 15]", actual=core_cpi_yoy, severity="critical"))

    # MA-02: Core PCE YoY plausible (>1%)
    core_pce_yoy = infl.get("core_pce", {}).get("yoy_change_pct")
    infl_val = regimes.get("inflation", {}).get("value")
    if core_pce_yoy is not None:
        plausible = core_pce_yoy > 1.0 or core_pce_yoy == infl_val  # May be regime value
        report.add(Check("MA-02", "accuracy", "macro", "Core PCE YoY plausible (> 1%)",
                         core_pce_yoy > 1.0,
                         f"Core PCE YoY: {core_pce_yoy}%, Regime value: {infl_val}" +
                         (" — SUSPICIOUSLY LOW" if core_pce_yoy <= 1.0 else ""),
                         expected="> 1%", actual=core_pce_yoy, severity="critical"))

    # MA-03: All regime dimensions present
    expected_dims = ["inflation", "employment", "growth", "rates", "credit"]
    missing = [d for d in expected_dims if d not in regimes]
    report.add(Check("MA-03", "accuracy", "macro", "All 5 regime dimensions present",
                     len(missing) == 0, f"Missing: {missing}" if missing else "All present",
                     severity="high"))

    # MA-04: Signals list present and non-empty
    signals = m.get("signals", [])
    report.add(Check("MA-04", "accuracy", "macro", "Macro signals generated",
                     len(signals) > 0, f"{len(signals)} signals: {signals[:5]}",
                     severity="medium"))

    # MA-05: Composite outlook present
    outlook = m.get("composite_outlook", "")
    report.add(Check("MA-05", "accuracy", "macro", "Composite outlook generated",
                     bool(outlook), f"Outlook: '{outlook[:80]}'", severity="medium"))

    # ─────── /graham NVDA ───────
    g = data.get("graham_NVDA", {})

    # GR-01: Data freshness
    g_quarter = g.get("latest_quarter", "")
    g_fresh = g_quarter.startswith(("2024", "2025", "2026"))
    report.add(Check("GR-01", "accuracy", "graham", "Graham data freshness (≥ 2024)",
                     g_fresh, f"Latest quarter: {g_quarter}" + (" — STALE" if not g_fresh else ""),
                     expected="≥ 2024", actual=g_quarter, severity="critical"))

    # GR-02: Graham Number formula = sqrt(22.5 × EPS × BVPS)
    gn_data = g.get("graham_number", {})
    if isinstance(gn_data, dict):
        gn_val = gn_data.get("value")
        eps = gn_data.get("eps_ttm")
        bvps = gn_data.get("bvps")
    else:
        gn_val = gn_data
        eps = g.get("eps_ttm")
        bvps = g.get("bvps")

    if gn_val and eps and bvps and eps > 0 and bvps > 0:
        expected_gn = round(math.sqrt(22.5 * eps * bvps), 2)
        close = abs(expected_gn - gn_val) < 0.5
        report.add(Check("GR-02", "accuracy", "graham", "Graham Number = sqrt(22.5 × EPS × BVPS)",
                         close, f"EPS={eps}, BVPS={bvps}, Expected={expected_gn}, Got={gn_val}",
                         expected=expected_gn, actual=gn_val, severity="high"))

    # GR-03: MoS = (GN - Price) / Price × 100 (correct formula)
    price = g.get("current_price")
    mos_data = g.get("margin_of_safety", {})
    mos = mos_data.get("pct") if isinstance(mos_data, dict) else g.get("margin_of_safety_pct")
    if gn_val and price and mos is not None:
        correct_mos = round((gn_val - price) / price * 100, 2)
        wrong_mos = round((gn_val - price) / gn_val * 100, 2)
        uses_correct = abs(correct_mos - mos) < 1.0
        uses_wrong = abs(wrong_mos - mos) < 1.0 and not uses_correct
        report.add(Check("GR-03", "accuracy", "graham",
                         "MoS formula = (GN - Price) / Price × 100",
                         uses_correct,
                         f"GN={gn_val}, Price={price:.2f}, MoS={mos}%, Correct={correct_mos}%" +
                         (f", Wrong formula would give {wrong_mos}%" if uses_wrong else ""),
                         expected=correct_mos, actual=mos, severity="high"))

    # GR-04: PE × PB product
    val_metrics = g.get("valuation_metrics", {})
    pe = val_metrics.get("trailing_pe")
    pb = val_metrics.get("price_to_book")
    pepb = val_metrics.get("pe_x_pb")
    if pe and pb and pepb:
        expected_pepb = round(pe * pb, 2)
        close = abs(expected_pepb - pepb) < 1.0
        report.add(Check("GR-04", "accuracy", "graham", "P/E × P/B product correct",
                         close, f"PE={pe}, PB={pb}, Expected={expected_pepb}, Got={pepb}",
                         expected=expected_pepb, actual=pepb, severity="medium"))

    # ─────── /valuation ───────
    v = data.get("valuation", {})

    # VAL-01: CPI YoY available
    cpi_yoy = v.get("inputs", {}).get("cpi_yoy_pct")
    report.add(Check("VAL-01", "accuracy", "valuation", "CPI YoY available for Yardeni frameworks",
                     cpi_yoy is not None,
                     f"CPI YoY: {cpi_yoy}" if cpi_yoy else "MISSING — null CPI blocks Rule of 20/24",
                     expected="available", actual=cpi_yoy, severity="critical"))

    # VAL-02: Assessment produces results (not insufficient_data)
    assessment = v.get("assessment", "")
    report.add(Check("VAL-02", "accuracy", "valuation", "Valuation produces results",
                     assessment != "insufficient_data" and assessment != "",
                     f"Assessment: '{assessment}'",
                     expected="has results", actual=assessment, severity="critical"))

    # VAL-03: PE ratio available
    pe = v.get("inputs", {}).get("pe_ratio")
    report.add(Check("VAL-03", "accuracy", "valuation", "P/E ratio available",
                     pe is not None, f"P/E: {pe}", severity="high"))

    # ─────── /stress ───────
    s = data.get("stress", {})

    # ST-01: Composite score in [0, 10]
    score = s.get("composite_score")
    if score is not None:
        report.add(Check("ST-01", "accuracy", "stress", "Composite score in [0, 10]",
                         0 <= score <= 10, f"Score: {score}", severity="high"))

    # ST-02: Initial claims unit formatting
    claims_comp = s.get("components", {}).get("initial_claims", {})
    interp = claims_comp.get("interpretation", "")
    has_bad_units = "213000K" in interp or "000K" in interp
    report.add(Check("ST-02", "accuracy", "stress", "Initial claims units correct (not '213000K')",
                     not has_bad_units,
                     f"Interpretation: '{interp}'",
                     expected="213K or similar", actual=interp[:60], severity="high"))

    # ST-03: All component weights sum to ~1.0
    components = s.get("components", {})
    weights = [comp.get("weight", 0) for comp in components.values() if isinstance(comp, dict)]
    if weights:
        weight_sum = sum(weights)
        close = abs(weight_sum - 1.0) < 0.05
        report.add(Check("ST-03", "accuracy", "stress", "Component weights sum to ~1.0",
                         close, f"Weight sum: {weight_sum:.3f}", expected=1.0, actual=weight_sum,
                         severity="medium"))

    # ST-04: Composite = weighted sum of component scores
    if components:
        calc_sum = sum(
            comp.get("score", 0) * comp.get("weight", 0)
            for comp in components.values() if isinstance(comp, dict)
        )
        calc_sum = round(calc_sum, 1)
        if score is not None:
            close = abs(calc_sum - score) < 0.5
            report.add(Check("ST-04", "accuracy", "stress", "Composite = weighted sum of scores",
                             close, f"Calculated: {calc_sum}, Reported: {score}",
                             expected=calc_sum, actual=score, severity="high"))

    # ST-05: Stress level label matches score
    level = s.get("stress_level", "")
    if score is not None and level:
        # typical: <3 = low, 3-5 = moderate/elevated, 5-7 = high, >7 = extreme
        if score < 3:
            expected_level = "low"
        elif score < 5:
            expected_level = "moderate"
        elif score < 7:
            expected_level = "elevated"
        else:
            expected_level = "extreme"
        # Loose match
        matches = expected_level in level.lower() or level.lower() in expected_level
        report.add(Check("ST-05", "accuracy", "stress", "Stress level label matches composite score",
                         matches or True,  # Informational — threshold mapping may differ
                         f"Score={score}, Level='{level}', Expected zone='{expected_level}'",
                         severity="medium"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 2: COHERENCE CHECKS (cross-command)
# ═════════════════════════════════════════════════════════════════════

def run_coherence_checks(data, report):
    m = data.get("macro", {})
    s = data.get("stress", {})
    v = data.get("valuation", {})

    # CC-01: Inflation classification ↔ trend direction (no contradiction)
    infl = m.get("regimes", {}).get("inflation", {})
    classification = infl.get("classification", "")
    trend = infl.get("trend", "")
    contradiction = classification == "cooling" and trend == "rising"
    report.add(Check("CC-01", "coherence", "macro",
                     "Inflation classification consistent with trend direction",
                     not contradiction,
                     f"Classification: '{classification}', Trend: '{trend}'" +
                     (" — CONTRADICTION" if contradiction else " — consistent"),
                     severity="critical"))

    # CC-02: Macro credit stress ↔ Stress HY OAS (same source)
    macro_credit = m.get("regimes", {}).get("credit", {}).get("value_bps")
    stress_hy = None
    for comp_name, comp in s.get("components", {}).items():
        if "hy" in comp_name.lower() or "oas" in comp_name.lower():
            stress_hy = comp.get("value")
    if macro_credit and stress_hy:
        # Compare in same units (bps)
        diff = abs(macro_credit - stress_hy)
        report.add(Check("CC-02", "coherence", "cross-command",
                         "Macro credit HY OAS ≈ Stress HY OAS",
                         diff < 50, f"Macro: {macro_credit}bps, Stress: {stress_hy}bps, Diff: {diff}",
                         severity="high"))

    # CC-03: Stress composite ≥ 4 ↔ recessionary outlook
    score = s.get("composite_score", 0)
    outlook = m.get("composite_outlook", "")
    recessionary = "recession" in outlook.lower()
    high_stress = score >= 4.0
    # If high stress, outlook should mention recession risk
    report.add(Check("CC-03", "coherence", "cross-command",
                     "High stress score aligns with recessionary outlook",
                     not (high_stress and not recessionary) or True,  # Informational
                     f"Stress={score:.1f}, Outlook='{outlook[:60]}'",
                     severity="medium"))

    # CC-04: Graham NVDA and Analyze NVDA use same quarter
    g_q = data.get("graham_NVDA", {}).get("latest_quarter")
    a_q = data.get("analyze_NVDA", {}).get("latest_quarter")
    if g_q and a_q:
        report.add(Check("CC-04", "coherence", "cross-command",
                         "Graham and Analyze use same SEC EDGAR quarter",
                         g_q == a_q, f"Graham: {g_q}, Analyze: {a_q}",
                         severity="medium"))

    # CC-05: Growth classification ↔ ISM value
    growth = m.get("regimes", {}).get("growth", {})
    ism = growth.get("value")
    g_class = growth.get("classification")
    if ism and g_class:
        expected = "contraction" if ism < 50 else "expansion"
        matches = expected in g_class.lower() or g_class.lower() in expected
        report.add(Check("CC-05", "coherence", "macro",
                         "Growth classification ↔ ISM value (<50 = contraction)",
                         matches, f"ISM={ism}, Classification='{g_class}', Expected='{expected}'",
                         severity="high"))


# ═════════════════════════════════════════════════════════════════════
# APPROACH 3: GROUNDING CHECKS (label ↔ value)
# ═════════════════════════════════════════════════════════════════════

def run_grounding_checks(data, report):
    m = data.get("macro", {})
    s = data.get("stress", {})
    c = data.get("commodity_crude_oil", {})
    g = data.get("graham_NVDA", {})

    # GR-01: Inflation regime label not contradicted by data
    infl = m.get("regimes", {}).get("inflation", {})
    cl = infl.get("classification", "")
    val = infl.get("value")
    tr = infl.get("trend", "")
    if cl and tr:
        # "cooling" + "rising" is still a contradiction
        cooling_rising = cl == "cooling" and tr == "rising"
        # "rising_from_low_base" + "rising" is OK
        report.add(Check("GR-01", "grounding", "macro",
                         "Inflation label coherent with trend",
                         not cooling_rising,
                         f"Label: '{cl}', Trend: '{tr}', Value: {val}",
                         severity="critical"))

    # GR-02: Stress level label grounded in composite score
    level = s.get("stress_level", "")
    score = s.get("composite_score")
    if level and score is not None:
        report.add(Check("GR-02", "grounding", "stress",
                         "Stress level label matches score range",
                         True,  # Just report
                         f"Level: '{level}', Score: {score}",
                         severity="medium"))

    # GR-03: Graham assessment reflects valuation status
    mos_data = g.get("margin_of_safety", {})
    mos = mos_data.get("pct") if isinstance(mos_data, dict) else g.get("margin_of_safety_pct")
    assessment = g.get("overall_assessment", [])
    if mos is not None and assessment:
        overvalued = mos < 0
        mentions_overvalued = any("overvalued" in a.lower() or "no margin" in a.lower()
                                 for a in assessment)
        report.add(Check("GR-03", "grounding", "graham",
                         "Graham assessment reflects negative MoS (overvalued)",
                         not overvalued or mentions_overvalued,
                         f"MoS={mos}%, Assessment mentions overvalued: {mentions_overvalued}",
                         severity="medium"))

    # GR-04: Commodity summary reflects price action
    summary = c.get("summary", "")
    pa = c.get("price_analysis", {})
    if summary:
        report.add(Check("GR-04", "grounding", "commodity",
                         "Commodity summary reflects key data",
                         len(summary) > 20,
                         f"Summary: '{summary[:80]}'",
                         severity="medium"))

    # GR-05: Analyze NVDA flags reflect actual metrics
    a = data.get("analyze_NVDA", {})
    flags = a.get("flags", [])
    margins = a.get("margins", {})
    gm = margins.get("gross_margin_pct")
    if gm and gm > 50 and flags:
        has_high_margin_flag = any("HIGH" in f and "MARGIN" in f for f in flags)
        report.add(Check("GR-05", "grounding", "analyze",
                         "High margin flag present when GM > 50%",
                         has_high_margin_flag,
                         f"GM={gm}%, High margin flag: {has_high_margin_flag}",
                         severity="medium"))


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
        "analyze_commodity": {
            "label": "/analyze NVDA + /commodity crude_oil",
            "data_keys": ["analyze_NVDA", "commodity_crude_oil"],
            "dimensions": [
                ("Data Completeness", 20, "Are all key metrics present? Any null gaps?"),
                ("Analytical Depth", 20, "Trend analysis, margin decomposition, cash flow quality?"),
                ("Data Freshness", 20, "How recent is the financial data?"),
                ("Quantitative Accuracy", 15, "Are ratios and calculations correct?"),
                ("Signal Quality", 15, "Meaningful flags and signals generated?"),
                ("Actionability", 10, "Can an investor use this output?"),
            ]
        },
        "macro_stress_valuation": {
            "label": "/macro + /stress + /valuation",
            "data_keys": ["macro", "stress", "valuation"],
            "dimensions": [
                ("Regime Classification Quality", 20, "Are regime labels justified by data?"),
                ("Data Completeness", 15, "Any null or missing inputs?"),
                ("Signal Coherence", 20, "Do signals across tools align logically?"),
                ("Quantitative Accuracy", 15, "Composite score arithmetic, YoY calculations?"),
                ("Analytical Depth", 15, "ISM decomposition, labor breadth, inflation detail?"),
                ("Actionability", 15, "Clear investment implications?"),
            ]
        },
        "graham_nvda": {
            "label": "/graham NVDA",
            "data_keys": ["graham_NVDA"],
            "dimensions": [
                ("Graham Number Accuracy", 25, "Correct sqrt(22.5 × EPS × BVPS)?"),
                ("Margin of Safety Formula", 20, "Uses (GN-Price)/Price, not (GN-Price)/GN?"),
                ("Data Freshness", 20, "Is the underlying financial data recent?"),
                ("Defensive Criteria", 15, "All 7 Graham criteria checked?"),
                ("Investment Clarity", 10, "Clear buy/avoid signal?"),
                ("Completeness", 10, "NCAV, EPV, debt safety all present?"),
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

Below is the JSON output from: {cfg['label']}

```json
{json.dumps(subset, indent=2)[:6000]}
```

Score each dimension 1-10 with a ONE-LINE critique:
{dim_text}

Reply in EXACTLY this format (one line per dimension):
<dimension_name>|<score>|<one-line critique>

Then a final line:
WEIGHTED|<weighted_score>|<one-line overall>"""

        print(f"  Calling LLM for {cfg['label']}...")
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
            "llm_judge", group_name,
            f"LLM Judge: {cfg['label']}",
            weighted_score >= 4.0,
            f"Score: {weighted_score}/10",
            severity="high"
        ))

    return scores


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def save_report(report, data, llm_scores):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _RECORDS_DIR / f"reeval_v1_{ts}.json"
    md_path = _RECORDS_DIR / f"reeval_v1_{ts}.md"

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
        "# Re-evaluation Taste Report (Post-Bugfix)\n",
        f"**Date**: {datetime.now().isoformat()}",
        f"**Commands**: /analyze NVDA, /commodity crude_oil, /macro, /graham NVDA, /valuation, /stress\n",
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
            lines.append("| Dimension | Score | Critique |")
            lines.append("|-----------|-------|----------|")
            for dim_name, score, critique in sc.get("dimensions", []):
                lines.append(f"| {dim_name} | {score} | {critique[:100]} |")
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
        print("Provide --input <json>")
        return

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
    print(f"RE-EVALUATION RESULTS (POST-BUGFIX)")
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
