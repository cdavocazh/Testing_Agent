"""
Test Coverage Tracker for Taste Evaluation Suite

Enumerates all /full_report tools, their output fields, and signals,
then checks which are covered by each evaluation approach.

Usage:
    python coverage_tracker.py                        # Print coverage report
    python coverage_tracker.py --input report.json    # Scan actual report JSON for field coverage
"""

import sys, os, json, argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

_THIS_DIR = Path(__file__).resolve().parent
_RECORDS_DIR = _THIS_DIR / "coverage_records"
_RECORDS_DIR.mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════
# TOOL & FIELD REGISTRY — What the test suite SHOULD cover
# ═════════════════════════════════════════════════════════════════════

# 8 /full_report tools + 1 synthesis tool
FULL_REPORT_TOOLS = {
    "scan_all_indicators": {
        "description": "Macro indicator scan (27 indicators)",
        "key_fields": [
            "flagged_count", "total_indicators", "flagged_indicators",
            "follow_up_suggestions",
        ],
    },
    "analyze_macro_regime": {
        "description": "Regime classification (6 dimensions)",
        "key_fields": [
            "composite_outlook", "regimes.growth", "regimes.inflation",
            "regimes.employment", "regimes.rates", "regimes.credit",
            "regimes.housing", "signals", "inflation_detail",
        ],
    },
    "analyze_financial_stress": {
        "description": "Financial stress score (8 components)",
        "key_fields": [
            "composite_score", "stress_level", "summary", "signals",
            "components.nfci", "components.hy_oas", "components.vix",
            "components.yield_curve_2s10s", "components.initial_claims",
            "components.sahm_rule", "components.consumer_sentiment",
            "components.consumer_credit_stress",
            "supplemental.private_credit_proxy",
            "supplemental.bank_equity_vs_credit",
        ],
    },
    "detect_late_cycle_signals": {
        "description": "13-signal late-cycle framework",
        "key_fields": [
            "count", "confidence_level", "signals_fired", "signals",
        ],
    },
    "analyze_equity_drivers": {
        "description": "Equity index drivers (ERP, real yields, credit, DXY, VIX)",
        "key_fields": [
            "summary", "signals", "real_yield_impact", "equity_risk_premium",
            "credit_equity_link", "dxy_impact", "inflation_rotation",
            "vix_framework", "rolling_correlations",
        ],
    },
    "analyze_bond_market": {
        "description": "Bond market analysis",
        "key_fields": [
            "summary", "signals", "yield_curve", "real_yields",
            "breakevens", "credit_spreads", "fed_policy", "term_premium",
        ],
    },
    "analyze_consumer_health": {
        "description": "Consumer health dashboard (4 components)",
        "key_fields": [
            "composite_score", "consumer_health_level", "signals",
            "components.savings_rate", "components.credit_growth",
            "components.delinquency_rate", "components.bank_lending",
        ],
    },
    "analyze_housing_market": {
        "description": "Housing market analysis",
        "key_fields": [
            "assessment", "signals", "housing_cycle_phase",
            "starts", "permits", "existing_sales", "affordability",
            "home_prices", "leading_indicator_signal",
        ],
    },
}

SYNTHESIS_TOOL = {
    "synthesize_macro_view": {
        "description": "Cross-tool macro synthesis",
        "key_fields": [
            "regime_summary", "contradictions", "contradiction_count",
            "coherence_status", "historical_analogues", "so_what_chains",
            "recommendations", "executive_summary",
        ],
    },
}

TA_TOOLS = {
    "murphy_technical_analysis": {
        "description": "13 TA frameworks composite",
        "key_fields": ["composite_signal", "confidence", "framework_breakdown"],
    },
    "calculate_rsi": {
        "description": "RSI calculator",
        "key_fields": ["rsi_values", "zone", "divergence", "actionable_signal"],
    },
    "find_support_resistance": {
        "description": "S/R level finder",
        "key_fields": ["levels", "position_assessment", "nearest_support", "nearest_resistance"],
    },
    "analyze_breakout": {
        "description": "Breakout detection",
        "key_fields": ["breakout_detected", "direction", "confidence", "confirmations"],
    },
    "quick_ta_snapshot": {
        "description": "RSI + S/R + breakout combined",
        "key_fields": ["rsi", "support_resistance", "breakout", "actionable_summary"],
    },
    "fundamental_ta_synthesis": {
        "description": "Fundamental + TA alignment",
        "key_fields": ["alignment", "conviction", "fundamental", "technical"],
    },
}


# ═════════════════════════════════════════════════════════════════════
# APPROACH COVERAGE MAP — What each approach actually tests
# ═════════════════════════════════════════════════════════════════════

APPROACH_COVERAGE = {
    "approach_2_coherence": {
        "description": "14 cross-tool coherence rules (incl. 3 synthesis rules)",
        "tools_covered": [
            "scan_all_indicators", "analyze_macro_regime",
            "analyze_financial_stress", "detect_late_cycle_signals",
            "analyze_equity_drivers", "analyze_bond_market",
            "analyze_consumer_health", "analyze_housing_market",
            "synthesize_macro_view",
        ],
        "fields_checked": [
            "analyze_macro_regime/composite_outlook",
            "analyze_macro_regime/regimes.growth",
            "analyze_macro_regime/regimes.rates",
            "analyze_financial_stress/composite_score",
            "analyze_financial_stress/stress_level",
            "analyze_financial_stress/components.vix",
            "detect_late_cycle_signals/count",
            "analyze_equity_drivers/real_yield_impact",
            "analyze_equity_drivers/credit_equity_link",
            "analyze_bond_market/yield_curve",
            "analyze_bond_market/credit_spreads",
            "analyze_consumer_health/consumer_health_level",
            "analyze_consumer_health/composite_score",
            "analyze_housing_market/signals",
            "scan_all_indicators/flagged_count",
            "synthesize_macro_view/contradictions",
            "synthesize_macro_view/contradiction_count",
            "synthesize_macro_view/coherence_status",
            "synthesize_macro_view/recommendations",
        ],
        "check_count": 14,
    },
    "approach_3_grounding": {
        "description": "7 narrative-vs-data grounding checks",
        "tools_covered": [
            "analyze_macro_regime", "analyze_financial_stress",
            "detect_late_cycle_signals", "analyze_equity_drivers",
            "analyze_bond_market", "analyze_consumer_health",
        ],
        "fields_checked": [
            "analyze_bond_market/credit_spreads",
            "analyze_equity_drivers/credit_equity_link",
            "analyze_financial_stress/composite_score",
            "analyze_financial_stress/stress_level",
            "analyze_financial_stress/components.vix",
            "analyze_macro_regime/regimes.inflation",
            "analyze_macro_regime/inflation_detail",
            "detect_late_cycle_signals/count",
            "detect_late_cycle_signals/confidence_level",
            "analyze_equity_drivers/real_yield_impact",
            "analyze_consumer_health/composite_score",
            "analyze_consumer_health/consumer_health_level",
        ],
        "check_count": 7,
    },
    "approach_4_comparative": {
        "description": "LLM-as-judge 7-dimension rubric",
        "tools_covered": [
            "analyze_macro_regime", "analyze_financial_stress",
            "detect_late_cycle_signals", "analyze_equity_drivers",
            "analyze_bond_market", "analyze_consumer_health",
            "analyze_housing_market",
        ],
        "fields_checked": [
            # LLM judge reads formatted text — hard to pinpoint exact fields
            "analyze_macro_regime/composite_outlook",
            "analyze_macro_regime/regimes",
            "analyze_financial_stress/composite_score",
            "analyze_financial_stress/stress_level",
            "detect_late_cycle_signals/count",
            "analyze_equity_drivers/summary",
            "analyze_bond_market/summary",
            "analyze_consumer_health/composite_score",
            "analyze_housing_market/assessment",
        ],
        "check_count": 7,
    },
    "approach_5_backtesting": {
        "description": "Forward-looking signal verification (30+ signal defs)",
        "tools_covered": [
            "scan_all_indicators", "analyze_macro_regime",
            "analyze_financial_stress", "detect_late_cycle_signals",
            "analyze_equity_drivers", "analyze_bond_market",
            "analyze_consumer_health", "analyze_housing_market",
        ],
        "fields_checked": [
            "*/signals",  # All tools' signals arrays
            "analyze_financial_stress/composite_score",
            "analyze_financial_stress/components.vix",
            "analyze_equity_drivers/credit_equity_link",
            "analyze_equity_drivers/real_yield_impact",
            "analyze_macro_regime/inflation_detail",
            "analyze_consumer_health/composite_score",
        ],
        "check_count": 30,  # signal definitions
    },
    "approach_6_data_accuracy": {
        "description": "8-category arithmetic/consistency/range/synthesis checks",
        "tools_covered": [
            "scan_all_indicators", "analyze_macro_regime",
            "analyze_financial_stress", "detect_late_cycle_signals",
            "analyze_equity_drivers", "analyze_bond_market",
            "analyze_consumer_health", "analyze_housing_market",
            "synthesize_macro_view",
        ],
        "fields_checked": [
            "analyze_bond_market/yield_curve",
            "analyze_bond_market/real_yields",
            "analyze_bond_market/breakevens",
            "analyze_bond_market/credit_spreads",
            "analyze_bond_market/term_premium",
            "analyze_equity_drivers/real_yield_impact",
            "analyze_equity_drivers/credit_equity_link",
            "analyze_financial_stress/composite_score",
            "analyze_financial_stress/components",
            "analyze_consumer_health/composite_score",
            "analyze_consumer_health/consumer_health_level",
            "analyze_consumer_health/components",
            "detect_late_cycle_signals/count",
            "scan_all_indicators/flagged_count",
            "analyze_housing_market/housing_cycle_phase",
            "analyze_housing_market/signals",
            "analyze_housing_market/starts",
            "analyze_housing_market/permits",
            "synthesize_macro_view/recommendations",
            "synthesize_macro_view/contradictions",
            "synthesize_macro_view/historical_analogues",
            "synthesize_macro_view/executive_summary",
        ],
        "check_count": 70,
    },
    "approach_7_ta_evaluation": {
        "description": "TA tool internal consistency & cross-tool checks",
        "tools_covered": [
            "murphy_technical_analysis", "calculate_rsi",
            "find_support_resistance", "analyze_breakout",
            "quick_ta_snapshot", "fundamental_ta_synthesis",
        ],
        "fields_checked": [
            "calculate_rsi/rsi", "calculate_rsi/zone",
            "calculate_rsi/signal", "calculate_rsi/multi_period",
            "find_support_resistance/supports", "find_support_resistance/resistances",
            "find_support_resistance/position", "find_support_resistance/nearest_support",
            "find_support_resistance/nearest_resistance",
            "analyze_breakout/breakout_detected", "analyze_breakout/breakout_type",
            "analyze_breakout/confidence", "analyze_breakout/confirmations_met",
            "analyze_breakout/false_breakout_warning",
            "quick_ta_snapshot/rsi", "quick_ta_snapshot/support_resistance",
            "quick_ta_snapshot/breakout", "quick_ta_snapshot/action",
            "murphy_technical_analysis/composite_signal",
            "fundamental_ta_synthesis/synthesis.alignment",
            "fundamental_ta_synthesis/synthesis.conviction",
        ],
        "check_count": 25,
    },
}


# ═════════════════════════════════════════════════════════════════════
# COVERAGE COMPUTATION
# ═════════════════════════════════════════════════════════════════════

def compute_coverage() -> dict:
    """Compute coverage statistics across all approaches."""

    # Tool coverage
    all_tools = set(FULL_REPORT_TOOLS.keys())
    synthesis_tools = set(SYNTHESIS_TOOL.keys())
    ta_tools = set(TA_TOOLS.keys())

    covered_by_approach = {}
    for approach, info in APPROACH_COVERAGE.items():
        covered_by_approach[approach] = set(info["tools_covered"])

    tools_covered = set()
    for approach_tools in covered_by_approach.values():
        tools_covered |= approach_tools

    tools_uncovered = all_tools - tools_covered
    synthesis_covered = synthesis_tools & tools_covered
    ta_covered = ta_tools & tools_covered

    # Field coverage (approximate — based on declared fields)
    all_fields = set()
    for tool, info in FULL_REPORT_TOOLS.items():
        for field in info["key_fields"]:
            all_fields.add(f"{tool}/{field}")

    fields_checked = set()
    for approach, info in APPROACH_COVERAGE.items():
        for f in info["fields_checked"]:
            if f.startswith("*/"):
                # Wildcard — applies to all tools
                suffix = f[2:]
                for tool in all_tools:
                    fields_checked.add(f"{tool}/{suffix}")
            else:
                fields_checked.add(f)

    fields_uncovered = all_fields - fields_checked

    # Per-approach stats
    approach_stats = {}
    for approach, info in APPROACH_COVERAGE.items():
        approach_stats[approach] = {
            "description": info["description"],
            "tools_covered": len(info["tools_covered"]),
            "tools_total": len(all_tools),
            "fields_checked": len(info["fields_checked"]),
            "check_count": info["check_count"],
        }

    # Total checks
    total_checks = sum(info["check_count"] for info in APPROACH_COVERAGE.values())

    return {
        "timestamp": datetime.now().isoformat(),
        "tool_coverage": {
            "full_report_tools": {
                "total": len(all_tools),
                "covered": len(tools_covered),
                "uncovered": sorted(tools_uncovered),
                "coverage_pct": f"{len(tools_covered)/len(all_tools)*100:.0f}%",
            },
            "synthesis_tools": {
                "total": len(synthesis_tools),
                "covered": len(synthesis_covered),
                "uncovered": sorted(synthesis_tools - synthesis_covered),
                "coverage_pct": f"{len(synthesis_covered)/max(len(synthesis_tools),1)*100:.0f}%",
            },
            "ta_tools": {
                "total": len(ta_tools),
                "covered": len(ta_covered),
                "uncovered": sorted(ta_tools - ta_covered),
                "coverage_pct": f"{len(ta_covered)/max(len(ta_tools),1)*100:.0f}%",
            },
        },
        "field_coverage": {
            "total_fields": len(all_fields),
            "covered_fields": len(fields_checked & all_fields),
            "uncovered_fields": sorted(fields_uncovered),
            "coverage_pct": f"{len(fields_checked & all_fields)/max(len(all_fields),1)*100:.0f}%",
        },
        "approach_stats": approach_stats,
        "total_checks": total_checks,
    }


def scan_actual_report(report_data: dict) -> dict:
    """Scan an actual report JSON for field presence (null vs populated)."""
    field_status = {}
    null_count = 0
    populated_count = 0

    for tool_name, data in report_data.items():
        if not isinstance(data, dict):
            continue
        tool_info = FULL_REPORT_TOOLS.get(tool_name, {})
        for field in tool_info.get("key_fields", []):
            key = f"{tool_name}/{field}"
            # Navigate dotted paths
            parts = field.split(".")
            val = data
            for p in parts:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    val = None
                    break
            if val is None or val == "data_unavailable":
                field_status[key] = "null/unavailable"
                null_count += 1
            else:
                field_status[key] = "populated"
                populated_count += 1

    return {
        "total_fields_scanned": null_count + populated_count,
        "populated": populated_count,
        "null_or_unavailable": null_count,
        "data_availability_pct": f"{populated_count/max(null_count+populated_count,1)*100:.0f}%",
        "null_fields": {k: v for k, v in field_status.items() if v != "populated"},
    }


# ═════════════════════════════════════════════════════════════════════
# OUTPUT
# ═════════════════════════════════════════════════════════════════════

def print_coverage(coverage: dict, data_scan: dict | None = None):
    """Pretty-print coverage report."""
    print("=" * 70)
    print("  TASTE EVALUATION: TEST COVERAGE STATISTICS")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    tc = coverage["tool_coverage"]
    print(f"\n  TOOL COVERAGE")
    print(f"  ├── /full_report tools: {tc['full_report_tools']['covered']}/{tc['full_report_tools']['total']} ({tc['full_report_tools']['coverage_pct']})")
    print(f"  ├── Synthesis tools:    {tc['synthesis_tools']['covered']}/{tc['synthesis_tools']['total']} ({tc['synthesis_tools']['coverage_pct']})")
    print(f"  └── TA tools:           {tc['ta_tools']['covered']}/{tc['ta_tools']['total']} ({tc['ta_tools']['coverage_pct']})")

    if tc["synthesis_tools"]["uncovered"]:
        print(f"\n  Uncovered synthesis tools: {', '.join(tc['synthesis_tools']['uncovered'])}")
    if tc["ta_tools"]["uncovered"]:
        print(f"  Uncovered TA tools: {', '.join(tc['ta_tools']['uncovered'])}")

    fc = coverage["field_coverage"]
    print(f"\n  FIELD COVERAGE")
    print(f"  {fc['covered_fields']}/{fc['total_fields']} key fields checked ({fc['coverage_pct']})")
    if fc["uncovered_fields"]:
        print(f"  Uncovered fields:")
        for f in fc["uncovered_fields"][:15]:
            print(f"    - {f}")
        if len(fc["uncovered_fields"]) > 15:
            print(f"    ... and {len(fc['uncovered_fields']) - 15} more")

    print(f"\n  APPROACH STATISTICS")
    print(f"  {'Approach':<28s} {'Tools':>5s} {'Fields':>6s} {'Checks':>6s}")
    print(f"  {'─' * 50}")
    for approach, stats in coverage["approach_stats"].items():
        label = approach.replace("approach_", "#").replace("_", " ")
        print(f"  {label:<28s} {stats['tools_covered']:>5d} {stats['fields_checked']:>6d} {stats['check_count']:>6d}")
    print(f"  {'─' * 50}")
    print(f"  {'TOTAL':<28s} {'':>5s} {'':>6s} {coverage['total_checks']:>6d}")

    if data_scan:
        print(f"\n  DATA AVAILABILITY (from actual report)")
        print(f"  Populated: {data_scan['populated']}/{data_scan['total_fields_scanned']} ({data_scan['data_availability_pct']})")
        if data_scan["null_fields"]:
            print(f"  Null/unavailable fields:")
            for f, status in data_scan["null_fields"].items():
                print(f"    - {f}: {status}")


def save_coverage(coverage: dict, data_scan: dict | None = None):
    """Save coverage report to records."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {**coverage}
    if data_scan:
        record["data_availability"] = data_scan

    path = _RECORDS_DIR / f"coverage_{ts}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    print(f"\n  Coverage report saved: {path}")

    # Markdown
    md_lines = [
        "# Test Coverage Report",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Tool Coverage",
        "",
        f"| Category | Covered | Total | % |",
        f"|----------|---------|-------|---|",
        f"| /full_report tools | {coverage['tool_coverage']['full_report_tools']['covered']} | {coverage['tool_coverage']['full_report_tools']['total']} | {coverage['tool_coverage']['full_report_tools']['coverage_pct']} |",
        f"| Synthesis tools | {coverage['tool_coverage']['synthesis_tools']['covered']} | {coverage['tool_coverage']['synthesis_tools']['total']} | {coverage['tool_coverage']['synthesis_tools']['coverage_pct']} |",
        f"| TA tools | {coverage['tool_coverage']['ta_tools']['covered']} | {coverage['tool_coverage']['ta_tools']['total']} | {coverage['tool_coverage']['ta_tools']['coverage_pct']} |",
        "",
        "## Field Coverage",
        "",
        f"**{coverage['field_coverage']['covered_fields']}/{coverage['field_coverage']['total_fields']}** key fields checked ({coverage['field_coverage']['coverage_pct']})",
        "",
        "## Approach Statistics",
        "",
        "| Approach | Tools | Fields | Checks |",
        "|----------|-------|--------|--------|",
    ]
    for approach, stats in coverage["approach_stats"].items():
        label = approach.replace("approach_", "#").replace("_", " ")
        md_lines.append(f"| {label} | {stats['tools_covered']} | {stats['fields_checked']} | {stats['check_count']} |")
    md_lines.append(f"| **TOTAL** | | | **{coverage['total_checks']}** |")

    if data_scan and data_scan["null_fields"]:
        md_lines.extend(["", "## Data Availability Gaps", ""])
        for f, status in data_scan["null_fields"].items():
            md_lines.append(f"- `{f}`: {status}")

    md_path = _RECORDS_DIR / f"coverage_{ts}.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"  Markdown: {md_path}")


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Coverage Tracker")
    parser.add_argument("--input", type=str, help="Actual report JSON to scan for data availability")
    args = parser.parse_args()

    coverage = compute_coverage()

    data_scan = None
    if args.input:
        with open(args.input) as f:
            report_data = json.load(f)
        data_scan = scan_actual_report(report_data)

    print_coverage(coverage, data_scan)
    save_coverage(coverage, data_scan)
