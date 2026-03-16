"""
Approach 2: Internal Coherence & Contradiction Detection

Checks whether the Financial Agent's outputs are logically consistent
with each other. This is pure domain-logic checking — no LLM needed.

When the macro regime says "reflationary" but financial stress flags
"bank systemic risk", that's an incoherence. When credit spreads at
313bps are called "tight and supportive", that contradicts financial
reality. This module catches those.

Usage:
    python coherence_checker.py                       # Run against live agent
    python coherence_checker.py --input report.json   # Run against saved output
"""

import sys, os, json, time, argparse
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_TASTE_DIR = _THIS_DIR.parent
_TESTING_ROOT = _TASTE_DIR.parent
_RECORDS_DIR = _THIS_DIR / "records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)

# Financial Agent imports
_FA_ROOT = os.environ.get(
    "FINANCIAL_AGENT_ROOT",
    str(Path(_TESTING_ROOT).parent.parent / "Financial_Agent")
)
sys.path.insert(0, _FA_ROOT)


# ═════════════════════════════════════════════════════════════════════
# COHERENCE RESULT TYPES
# ═════════════════════════════════════════════════════════════════════

class CoherenceResult:
    """A single coherence check result."""
    def __init__(self, rule_id: str, rule_name: str, passed: bool,
                 left_claim: str, right_claim: str, explanation: str,
                 severity: str = "medium"):
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.passed = passed
        self.left_claim = left_claim   # What tool A says
        self.right_claim = right_claim  # What tool B says (contradicts A)
        self.explanation = explanation   # Why this matters
        self.severity = severity        # critical, high, medium, low
        self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "passed": self.passed,
            "left_claim": self.left_claim,
            "right_claim": self.right_claim,
            "explanation": self.explanation,
            "severity": self.severity,
            "timestamp": self.timestamp,
        }


class CoherenceReport:
    """Collects all coherence check results."""
    def __init__(self):
        self.results: list[CoherenceResult] = []
        self.start_time = time.time()

    def add(self, result: CoherenceResult):
        self.results.append(result)
        icon = "\u2705" if result.passed else "\u274c"
        if not result.passed:
            print(f"  {icon} [{result.severity.upper():8s}] {result.rule_name}")
            print(f"      Left:  {result.left_claim}")
            print(f"      Right: {result.right_claim}")
            print(f"      Why:   {result.explanation}")
        else:
            print(f"  {icon} [{result.severity.upper():8s}] {result.rule_name}")

    @property
    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        contradictions = [r for r in self.results if not r.passed]
        return {
            "total_checks": total,
            "coherent": passed,
            "contradictions": total - passed,
            "coherence_rate": f"{passed/total*100:.1f}%" if total else "N/A",
            "critical_contradictions": sum(1 for r in contradictions if r.severity in ("critical", "high")),
            "elapsed": f"{time.time() - self.start_time:.1f}s",
        }

    def to_dict(self):
        return {
            "summary": self.summary,
            "contradictions": [r.to_dict() for r in self.results if not r.passed],
            "all_checks": [r.to_dict() for r in self.results],
        }


# ═════════════════════════════════════════════════════════════════════
# COHERENCE RULES
# ═════════════════════════════════════════════════════════════════════

def run_coherence_checks(report_data: dict) -> CoherenceReport:
    """Run all coherence rules against a full_report output."""
    cr = CoherenceReport()

    scan = report_data.get("scan_all_indicators", {})
    regime = report_data.get("analyze_macro_regime", {})
    stress = report_data.get("analyze_financial_stress", {})
    late = report_data.get("detect_late_cycle_signals", {})
    equity = report_data.get("analyze_equity_drivers", {})
    bond = report_data.get("analyze_bond_market", {})
    consumer = report_data.get("analyze_consumer_health", {})
    housing = report_data.get("analyze_housing_market", {})

    regimes = regime.get("regimes", {})
    signals_all = set()
    for tool_data in report_data.values():
        if isinstance(tool_data, dict):
            for s in tool_data.get("signals", []):
                if isinstance(s, str):
                    signals_all.add(s)

    # ── RULE C-01: Macro regime vs. financial stress level ──────────
    stress_score = stress.get("composite_score")
    stress_level = stress.get("stress_level", "")
    outlook = regime.get("composite_outlook", "")

    if stress_score is not None and outlook:
        # Reflationary/goldilocks → stress should be low-moderate
        if any(w in outlook.lower() for w in ["reflationary", "goldilocks"]):
            ok = stress_score < 6
            cr.add(CoherenceResult(
                "C-01", "Macro regime vs. stress level",
                ok,
                f"Macro regime: \"{outlook[:80]}\"",
                f"Stress score: {stress_score:.1f}/10 ({stress_level})",
                "Reflationary/goldilocks regimes should have stress < 6. "
                "If stress is elevated during easing, it suggests the regime classification "
                "is missing something (e.g., banking sector stress despite rate cuts).",
                severity="high",
            ))
        # Recessionary/stagflation → stress should be elevated
        if any(w in outlook.lower() for w in ["recession", "stagflat", "crisis"]):
            ok = stress_score > 4
            cr.add(CoherenceResult(
                "C-01b", "Recessionary regime implies elevated stress",
                ok,
                f"Macro regime: \"{outlook[:80]}\"",
                f"Stress score: {stress_score:.1f}/10 ({stress_level})",
                "Recessionary regimes should show stress > 4. Low stress during recession "
                "would indicate the regime classification or stress model is broken.",
                severity="high",
            ))

    # ── RULE C-02: Credit spread interpretation vs. actual level ────
    cs = bond.get("credit_spreads", {})
    hy_oas = None
    cs_interpretation = ""
    if isinstance(cs, dict):
        for k, v in cs.items():
            if isinstance(v, dict):
                if "hy" in k.lower() or "high_yield" in k.lower():
                    hy_oas = v.get("latest", v.get("value", v.get("spread_bps")))
                    cs_interpretation = v.get("interpretation", v.get("assessment", ""))
            elif isinstance(v, (int, float)) and "hy" in k.lower():
                hy_oas = v

    # Also check in equity drivers
    if hy_oas is None:
        cel = equity.get("credit_equity_link", {})
        if isinstance(cel, dict):
            hy_oas = cel.get("hy_oas_bps")
            cs_interpretation = cel.get("interpretation", "")

    if hy_oas is not None:
        # HY OAS thresholds: <150 tight, 150-300 normal, 300-500 wide, >500 distressed
        if hy_oas > 250 and any(w in cs_interpretation.lower() for w in ["tight", "supportive", "benign"]):
            cr.add(CoherenceResult(
                "C-02", "Credit spread level vs. interpretation",
                False,
                f"HY OAS = {hy_oas} bps (>250 = widening/stressed)",
                f"Interpretation: \"{cs_interpretation[:100]}\"",
                f"At {hy_oas}bps, HY OAS is NOT tight. Tight = <150bps. "
                "The narrative contradicts the data — this misleads investors about credit risk.",
                severity="critical",
            ))
        elif hy_oas <= 250 and any(w in cs_interpretation.lower() for w in ["wide", "stress", "distress"]):
            cr.add(CoherenceResult(
                "C-02b", "Credit spread level vs. interpretation (reverse)",
                False,
                f"HY OAS = {hy_oas} bps (<250 = normal/tight)",
                f"Interpretation: \"{cs_interpretation[:100]}\"",
                "At this level, spreads are NOT wide or stressed.",
                severity="high",
            ))
        else:
            cr.add(CoherenceResult(
                "C-02", "Credit spread level vs. interpretation",
                True,
                f"HY OAS = {hy_oas} bps",
                f"Interpretation: \"{cs_interpretation[:60]}\"",
                "Credit spread interpretation is consistent with the level.",
                severity="critical",
            ))

    # ── RULE C-03: Yield curve shape vs. late-cycle count ───────────
    yc = bond.get("yield_curve", {})
    yc_shape = yc.get("shape", yc.get("curve_shape", ""))
    if isinstance(yc_shape, dict):
        yc_shape = yc_shape.get("classification", yc_shape.get("shape", ""))
    lc_count = late.get("count", 0)

    if isinstance(yc_shape, str) and yc_shape:
        if "invert" in yc_shape.lower() and lc_count < 3:
            cr.add(CoherenceResult(
                "C-03", "Inverted yield curve vs. low late-cycle count",
                False,
                f"Yield curve: \"{yc_shape}\" (inverted)",
                f"Late-cycle signals: {lc_count}/13",
                "An inverted yield curve is a classic late-cycle signal. Having <3 late-cycle "
                "signals with an inverted curve suggests the late-cycle model is missing this input.",
                severity="high",
            ))
        elif "normal" in yc_shape.lower() and lc_count > 8:
            cr.add(CoherenceResult(
                "C-03b", "Normal yield curve vs. high late-cycle count",
                False,
                f"Yield curve: \"{yc_shape}\" (normal)",
                f"Late-cycle signals: {lc_count}/13",
                "A normal yield curve with many late-cycle signals is unusual. Either the curve "
                "model or the late-cycle model needs investigation.",
                severity="medium",
            ))
        else:
            cr.add(CoherenceResult(
                "C-03", "Yield curve shape vs. late-cycle count",
                True,
                f"Yield curve: \"{yc_shape}\"",
                f"Late-cycle signals: {lc_count}/13",
                "Yield curve shape and late-cycle count are consistent.",
                severity="high",
            ))

    # ── RULE C-04: Housing collapse vs. consumer health ─────────────
    ch_level = consumer.get("consumer_health_level", "")
    ch_score = consumer.get("composite_score")
    housing_signals = housing.get("signals", [])
    housing_assessment = str(housing.get("assessment", ""))

    housing_distressed = any(
        "plunging" in str(s).lower() or "collaps" in str(s).lower() or "crisis" in str(s).lower()
        for s in housing_signals
    ) or "plunging" in housing_assessment.lower()

    if housing_distressed and isinstance(ch_level, str) and ch_level.lower() in ("healthy",):
        cr.add(CoherenceResult(
            "C-04", "Housing distress vs. consumer health",
            False,
            f"Housing signals: {[s for s in housing_signals if 'PLUNGING' in str(s).upper() or 'COLLAPS' in str(s).upper()][:3]}",
            f"Consumer health: \"{ch_level}\" (score={ch_score})",
            "Housing is a major component of consumer wealth. Plunging housing metrics "
            "should pull consumer health below 'healthy'.",
            severity="high",
        ))
    else:
        cr.add(CoherenceResult(
            "C-04", "Housing signals vs. consumer health",
            True,
            f"Housing distressed={housing_distressed}",
            f"Consumer health: \"{ch_level}\"",
            "Housing and consumer health assessments are broadly consistent.",
            severity="high",
        ))

    # ── RULE C-05: VIX level vs. stress level ──────────────────────
    vix_comp = stress.get("components", {}).get("vix", {})
    vix_value = vix_comp.get("value") if isinstance(vix_comp, dict) else None

    if vix_value is not None and stress_level:
        if vix_value > 25 and stress_level.lower() == "low":
            cr.add(CoherenceResult(
                "C-05", "VIX level vs. stress classification",
                False,
                f"VIX = {vix_value} (>25 = elevated volatility)",
                f"Stress level: \"{stress_level}\"",
                "VIX > 25 indicates significant market fear. Stress level should be "
                "at least 'moderate', not 'low'.",
                severity="high",
            ))
        elif vix_value < 15 and stress_level.lower() in ("high", "extreme"):
            cr.add(CoherenceResult(
                "C-05b", "Low VIX vs. high stress classification",
                False,
                f"VIX = {vix_value} (<15 = complacent)",
                f"Stress level: \"{stress_level}\"",
                "VIX < 15 indicates market complacency. Hard to justify 'high' or 'extreme' stress.",
                severity="medium",
            ))
        else:
            cr.add(CoherenceResult(
                "C-05", "VIX level vs. stress classification",
                True,
                f"VIX = {vix_value}",
                f"Stress level: \"{stress_level}\"",
                "VIX level and stress classification are consistent.",
                severity="high",
            ))

    # ── RULE C-06: Growth regime vs. ISM signal ────────────────────
    growth_regime = regimes.get("growth", "")
    if isinstance(growth_regime, dict):
        growth_regime = growth_regime.get("classification", str(growth_regime))

    ism_signal = any("ISM_CONTRACTION" in str(s) for s in signals_all)

    if isinstance(growth_regime, str):
        if growth_regime.lower() == "expansion" and ism_signal:
            cr.add(CoherenceResult(
                "C-06", "Growth regime 'expansion' vs. ISM contraction signal",
                False,
                f"Growth regime: \"{growth_regime}\"",
                "Signal: ISM_CONTRACTION is firing",
                "ISM Manufacturing below 50 (contraction territory) contradicts an 'expansion' "
                "growth classification. The regime model and signal model disagree.",
                severity="high",
            ))
        elif growth_regime.lower() in ("contraction", "recession") and not ism_signal:
            # Not necessarily a contradiction — growth can contract without ISM
            cr.add(CoherenceResult(
                "C-06b", "Growth contraction without ISM signal",
                True,
                f"Growth regime: \"{growth_regime}\"",
                "ISM_CONTRACTION not firing",
                "Growth contraction can occur without ISM < 50 (services-led slowdown). "
                "Not a contradiction, but worth noting.",
                severity="low",
            ))
        else:
            cr.add(CoherenceResult(
                "C-06", "Growth regime vs. ISM signal",
                True,
                f"Growth regime: \"{growth_regime}\"",
                f"ISM_CONTRACTION firing: {ism_signal}",
                "Growth regime and ISM signal are consistent.",
                severity="high",
            ))

    # ── RULE C-07: Contradictory signals across tools ──────────────
    signal_pairs = [
        ("CREDIT_LOOSE", "CREDIT_TIGHT"),
        ("INFLATION_HOT", "INFLATION_COOLING"),
        ("GROWTH_EXPANSION", "GROWTH_CONTRACTION"),
        ("FED_TIGHTENING", "FED_EASING"),
        ("STRESS_LOW", "STRESS_ELEVATED"),
        ("STRESS_LOW", "STRESS_HIGH"),
    ]
    for sig_a, sig_b in signal_pairs:
        has_a = sig_a in signals_all
        has_b = sig_b in signals_all
        if has_a and has_b:
            cr.add(CoherenceResult(
                "C-07", f"Contradictory signals: {sig_a} vs {sig_b}",
                False,
                f"Signal A: {sig_a} (present)",
                f"Signal B: {sig_b} (present)",
                f"Both {sig_a} and {sig_b} are firing simultaneously across tools. "
                "These are mutually exclusive conditions — one must be wrong.",
                severity="critical",
            ))

    # If no contradictory signals found, record that
    contradictory_found = any(
        not r.passed and r.rule_id == "C-07" for r in cr.results
    )
    if not contradictory_found:
        cr.add(CoherenceResult(
            "C-07", "No contradictory signal pairs found",
            True, "All signals checked", "No mutual exclusions detected",
            "Signals across all tools are internally consistent.",
            severity="critical",
        ))

    # ── RULE C-08: Bank stress signal vs. consumer credit assessment ─
    bank_stress = any("BANK" in str(s).upper() and "STRESS" in str(s).upper() for s in signals_all)
    cc_comp = consumer.get("components", {}).get("credit_growth", {})
    cc_assessment = ""
    if isinstance(cc_comp, dict):
        cc_assessment = cc_comp.get("assessment", cc_comp.get("interpretation", ""))

    if bank_stress and isinstance(cc_assessment, str) and any(
        w in cc_assessment.lower() for w in ["healthy", "strong", "robust"]
    ):
        cr.add(CoherenceResult(
            "C-08", "Bank systemic stress vs. consumer credit health",
            False,
            "Signal: BANK_SYSTEMIC_STRESS detected",
            f"Consumer credit: \"{cc_assessment[:80]}\"",
            "Bank stress typically tightens lending standards and slows credit growth. "
            "Consumer credit shouldn't be 'healthy' during bank stress.",
            severity="high",
        ))
    else:
        cr.add(CoherenceResult(
            "C-08", "Bank stress signal vs. consumer credit",
            True,
            f"Bank stress signal: {bank_stress}",
            f"Consumer credit assessment: \"{str(cc_assessment)[:60]}\"",
            "Bank stress and consumer credit assessments are consistent.",
            severity="high",
        ))

    # ── RULE C-09: Real yield direction vs. equity narrative ────────
    ryi = equity.get("real_yield_impact", {})
    if isinstance(ryi, dict):
        ry_trend = ryi.get("trend", "")
        ry_interp = ryi.get("interpretation", "")
        ry_value = ryi.get("real_yield_10y")

        eq_summary = equity.get("summary", "")

        if isinstance(ry_trend, str) and ry_trend.lower() == "rising" and ry_value and ry_value > 2.0:
            # Rising real yields > 2% should be called out as headwind
            mentions_headwind = any(
                w in str(eq_summary).lower()
                for w in ["headwind", "pressure", "compress", "drag", "negative", "challenge"]
            )
            cr.add(CoherenceResult(
                "C-09", "Rising real yields vs. equity outlook tone",
                mentions_headwind,
                f"Real yield: {ry_value}% and rising",
                f"Equity summary mentions valuation headwind: {mentions_headwind}",
                "Real yields > 2% and rising compress equity valuations (higher discount rate). "
                "The equity outlook should flag this as a headwind.",
                severity="medium",
            ))
        elif isinstance(ry_trend, str) and ry_trend.lower() == "rising":
            cr.add(CoherenceResult(
                "C-09", "Real yield trend vs. equity narrative",
                True,
                f"Real yield: {ry_value}%, trend: {ry_trend}",
                f"Equity interpretation: \"{str(ry_interp)[:80]}\"",
                "Real yield level is moderate — rising trend noted but not critical.",
                severity="medium",
            ))

    # ── RULE C-10: Fed policy signal vs. rate regime ────────────────
    rate_regime = regimes.get("rates", "")
    if isinstance(rate_regime, dict):
        rate_regime = rate_regime.get("classification", str(rate_regime))

    fed_signals = [s for s in signals_all if "FED" in str(s).upper()]

    if isinstance(rate_regime, str):
        if "easing" in rate_regime.lower() and any("TIGHTEN" in s.upper() for s in fed_signals):
            cr.add(CoherenceResult(
                "C-10", "Rate regime 'easing' vs. FED_TIGHTENING signal",
                False,
                f"Rate regime: \"{rate_regime}\"",
                f"Fed signals: {fed_signals}",
                "Rate regime says easing but Fed tightening signal is active. "
                "One model is lagged or using different data.",
                severity="high",
            ))
        elif "tightening" in rate_regime.lower() and any("EASING" in s.upper() for s in fed_signals):
            cr.add(CoherenceResult(
                "C-10b", "Rate regime 'tightening' vs. FED_EASING signal",
                False,
                f"Rate regime: \"{rate_regime}\"",
                f"Fed signals: {fed_signals}",
                "Rate regime says tightening but Fed easing signal is active.",
                severity="high",
            ))
        else:
            cr.add(CoherenceResult(
                "C-10", "Rate regime vs. Fed policy signals",
                True,
                f"Rate regime: \"{rate_regime}\"",
                f"Fed signals: {fed_signals}",
                "Rate regime and Fed signals are consistent.",
                severity="high",
            ))

    # ── RULE C-11: Scan flagged count vs. stress level ──────────────
    flagged = scan.get("flagged_count", 0)
    total_ind = scan.get("total_indicators", 1)

    if flagged and total_ind and stress_level:
        flag_pct = flagged / total_ind * 100
        if flag_pct > 70 and stress_level.lower() == "low":
            cr.add(CoherenceResult(
                "C-11", "High flag rate vs. low stress",
                False,
                f"Scan: {flagged}/{total_ind} indicators flagged ({flag_pct:.0f}%)",
                f"Stress level: \"{stress_level}\"",
                "Over 70% of indicators flagged but stress is 'low'. The scan may be "
                "too sensitive, or the stress model is missing scan inputs.",
                severity="medium",
            ))
        else:
            cr.add(CoherenceResult(
                "C-11", "Scan flag rate vs. stress level",
                True,
                f"Scan: {flagged}/{total_ind} flagged ({flag_pct:.0f}%)",
                f"Stress level: \"{stress_level}\"",
                "Scan flag rate and stress level are broadly consistent.",
                severity="medium",
            ))

    # ── RULE C-12: Synthesis contradiction detection vs. tool outputs ──
    # If synthesize_macro_view is present, check its contradictions make sense
    synthesis = report_data.get("synthesize_macro_view", {})
    if synthesis and isinstance(synthesis, dict):
        contradictions = synthesis.get("contradictions", [])
        coherence_status = synthesis.get("coherence_status", "")
        contradiction_count = synthesis.get("contradiction_count", 0)

        # Contradiction count should match list length
        if isinstance(contradictions, list):
            actual_count = len(contradictions)
            if actual_count != contradiction_count:
                cr.add(CoherenceResult(
                    "C-12a", "Synthesis contradiction count mismatch",
                    False,
                    f"contradiction_count field: {contradiction_count}",
                    f"Actual contradictions list length: {actual_count}",
                    "The contradiction_count field should match the length of the "
                    "contradictions list.",
                    severity="medium",
                ))
            else:
                cr.add(CoherenceResult(
                    "C-12a", "Synthesis contradiction count consistent",
                    True,
                    f"contradiction_count: {contradiction_count}",
                    f"contradictions list length: {actual_count}",
                    "Contradiction count matches list length.",
                    severity="medium",
                ))

        # Coherence status should align with contradiction severity
        if isinstance(coherence_status, str) and isinstance(contradictions, list):
            has_critical = any(
                c.get("severity", "").upper() in ("CRITICAL", "HIGH")
                for c in contradictions if isinstance(c, dict)
            )
            if has_critical and coherence_status.lower() in ("coherent", "fully_coherent"):
                cr.add(CoherenceResult(
                    "C-12b", "Synthesis coherence status vs. critical contradictions",
                    False,
                    f"Coherence status: '{coherence_status}'",
                    f"Has critical/high contradictions: {has_critical}",
                    "Coherence status should not be 'coherent' when critical "
                    "contradictions are present.",
                    severity="high",
                ))
            else:
                cr.add(CoherenceResult(
                    "C-12b", "Synthesis coherence status consistency",
                    True,
                    f"Coherence status: '{coherence_status}'",
                    f"Critical contradictions: {has_critical}",
                    "Coherence status aligns with contradiction severity.",
                    severity="high",
                ))

        # Conviction should be penalized by contradictions
        recs = synthesis.get("recommendations", {})
        conviction = recs.get("conviction", "") if isinstance(recs, dict) else ""
        if isinstance(conviction, str) and has_critical and conviction.upper() == "HIGH":
            cr.add(CoherenceResult(
                "C-12c", "Synthesis conviction vs. contradictions",
                False,
                f"Conviction: '{conviction}'",
                f"Critical contradictions present",
                "Conviction should not be HIGH when critical contradictions exist.",
                severity="high",
            ))
        elif isinstance(conviction, str) and conviction:
            cr.add(CoherenceResult(
                "C-12c", "Synthesis conviction vs. contradictions",
                True,
                f"Conviction: '{conviction}'",
                f"Critical contradictions: {has_critical}",
                "Conviction level appropriately reflects contradiction status.",
                severity="high",
            ))

    return cr


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION (run live against Financial Agent)
# ═════════════════════════════════════════════════════════════════════

def collect_full_report(include_synthesis: bool = False) -> dict:
    """Execute all 8 /full_report tools and return combined output.

    Args:
        include_synthesis: If True, also run synthesize_macro_view() and
            include its output under the 'synthesize_macro_view' key.
    """
    import json as _json

    from tools.macro_data import scan_all_indicators
    from tools.macro_market_analysis import (
        analyze_macro_regime, analyze_bond_market, analyze_equity_drivers)
    from tools.market_regime_enhanced import (
        analyze_financial_stress, detect_late_cycle_signals)
    from tools.consumer_housing_analysis import (
        analyze_consumer_health, analyze_housing_market)

    print("  Collecting /full_report data from Financial Agent...")
    report = {}
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
    for name, fn in tools:
        t0 = time.time()
        raw = fn()
        elapsed = time.time() - t0
        report[name] = _json.loads(raw)
        print(f"    {name}: {elapsed:.1f}s")

    if include_synthesis:
        from tools.macro_synthesis import synthesize_macro_view
        t0 = time.time()
        raw = synthesize_macro_view()
        elapsed = time.time() - t0
        report["synthesize_macro_view"] = _json.loads(raw)
        print(f"    synthesize_macro_view: {elapsed:.1f}s")

    return report


# ═════════════════════════════════════════════════════════════════════
# RECORD KEEPING
# ═════════════════════════════════════════════════════════════════════

def save_record(report_data: dict, coherence_report: CoherenceReport):
    """Save coherence check results to records directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "timestamp": datetime.now().isoformat(),
        "input_snapshot": {k: list(v.keys()) if isinstance(v, dict) else type(v).__name__
                          for k, v in report_data.items()},
        "coherence_results": coherence_report.to_dict(),
    }
    path = _RECORDS_DIR / f"coherence_{ts}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    print(f"\n  Record saved: {path}")
    return path


def generate_markdown_report(coherence_report: CoherenceReport) -> str:
    """Generate a markdown report of coherence findings."""
    s = coherence_report.summary
    contradictions = [r for r in coherence_report.results if not r.passed]

    lines = [
        f"# Coherence & Contradiction Report",
        f"",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Checks**: {s['total_checks']} | **Coherent**: {s['coherent']} | "
        f"**Contradictions**: {s['contradictions']} | "
        f"**Rate**: {s['coherence_rate']}",
        f"",
    ]

    if contradictions:
        lines.append("## Contradictions Found\n")
        for r in contradictions:
            lines.append(f"### {r.rule_id}: {r.rule_name} [{r.severity.upper()}]\n")
            lines.append(f"- **Left claim**: {r.left_claim}")
            lines.append(f"- **Right claim**: {r.right_claim}")
            lines.append(f"- **Why this matters**: {r.explanation}")
            lines.append("")
    else:
        lines.append("## No Contradictions Found\n")
        lines.append("All coherence checks passed.")

    lines.append("\n## All Checks\n")
    lines.append("| # | Rule | Status | Severity |")
    lines.append("|---|------|--------|----------|")
    for r in coherence_report.results:
        icon = "\u2705" if r.passed else "\u274c"
        lines.append(f"| {r.rule_id} | {r.rule_name} | {icon} | {r.severity} |")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Approach 2: Coherence & Contradiction Detection")
    parser.add_argument("--input", type=str, help="Path to saved full_report JSON (skip live collection)")
    parser.add_argument("--synthesis", action="store_true",
                        help="Also run synthesize_macro_view() and check its coherence")
    args = parser.parse_args()

    print("=" * 70)
    print("  APPROACH 2: INTERNAL COHERENCE & CONTRADICTION DETECTION")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Collect or load data
    if args.input:
        with open(args.input) as f:
            report_data = json.load(f)
        print(f"\n  Loaded from: {args.input}")
    else:
        report_data = collect_full_report(include_synthesis=args.synthesis)

    # Run coherence checks
    print(f"\n{'─' * 70}")
    print("  Running coherence checks...")
    print(f"{'─' * 70}\n")

    cr = run_coherence_checks(report_data)

    # Summary
    s = cr.summary
    print(f"\n{'=' * 70}")
    print(f"  COHERENCE RESULTS")
    print(f"  Checks: {s['total_checks']} | Coherent: {s['coherent']} | "
          f"Contradictions: {s['contradictions']} | Rate: {s['coherence_rate']}")
    if s['critical_contradictions'] > 0:
        print(f"  \u26a0\ufe0f  Critical/High contradictions: {s['critical_contradictions']}")
    print(f"{'=' * 70}")

    # Save records
    record_path = save_record(report_data, cr)

    # Save markdown report
    md = generate_markdown_report(cr)
    md_path = _RECORDS_DIR / f"coherence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Markdown: {md_path}")
