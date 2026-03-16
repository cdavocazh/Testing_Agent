"""
Approach 3: Narrative-vs-Data Grounding (Hallucination Detection)

Extracts every factual claim from the Financial Agent's narrative fields,
then verifies each claim against the raw numeric data in the same output.

When the narrative says "credit spreads are tight and supportive" but the
data shows HY OAS = 313bps, that's a grounding failure — the narrative
isn't supported by (or contradicts) the underlying data.

Uses an LLM to decompose narratives into atomic claims, then applies
a financial threshold dictionary for verification.

Usage:
    python grounding_evaluator.py                       # Run against live agent
    python grounding_evaluator.py --input report.json   # Run against saved output
"""

import sys, os, json, time, re, argparse
from datetime import datetime
from pathlib import Path

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

from dotenv import load_dotenv
load_dotenv(os.path.join(_TESTING_ROOT, ".env"))
_fa_env = os.path.join(_FA_ROOT, ".env")
if os.path.exists(_fa_env):
    load_dotenv(_fa_env, override=False)

from agent.shared.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL


# ═════════════════════════════════════════════════════════════════════
# FINANCIAL THRESHOLD DICTIONARY
# ═════════════════════════════════════════════════════════════════════

THRESHOLDS = {
    "hy_oas_bps": {
        "tight":      (0, 150),
        "normal":     (150, 300),
        "wide":       (300, 500),
        "stressed":   (500, 800),
        "distressed": (800, 5000),
    },
    "vix": {
        "complacent": (0, 12),
        "calm":       (12, 16),
        "normal":     (16, 20),
        "elevated":   (20, 25),
        "fearful":    (25, 35),
        "panic":      (35, 100),
    },
    "rsi": {
        "oversold":           (0, 30),
        "bearish_momentum":   (30, 45),
        "neutral":            (45, 55),
        "bullish_momentum":   (55, 70),
        "overbought":         (70, 100),
    },
    "stress_score": {
        "low":      (0, 2.5),
        "moderate": (2.5, 5),
        "elevated": (5, 7),
        "high":     (7, 9),
        "extreme":  (9, 10),
    },
    "real_yield_10y_pct": {
        "deeply_negative": (-5, -0.5),
        "negative":        (-0.5, 0),
        "low":             (0, 1.0),
        "moderate":        (1.0, 2.0),
        "high":            (2.0, 3.0),
        "very_high":       (3.0, 10.0),
    },
    "fed_funds_pct": {
        "near_zero":   (0, 0.5),
        "accommodative": (0.5, 2.0),
        "neutral":     (2.0, 3.5),
        "restrictive": (3.5, 5.5),
        "very_restrictive": (5.5, 10.0),
    },
    "cpi_yoy_pct": {
        "deflationary": (-5, 0),
        "low":          (0, 2.0),
        "target":       (2.0, 2.5),
        "above_target": (2.5, 3.5),
        "hot":          (3.5, 5.0),
        "very_hot":     (5.0, 20.0),
    },
    "unemployment_pct": {
        "very_tight": (0, 3.5),
        "tight":      (3.5, 4.5),
        "normal":     (4.5, 5.5),
        "loose":      (5.5, 7.0),
        "weak":       (7.0, 20.0),
    },
    "late_cycle_count": {
        "early_cycle":    (0, 3),
        "mid_cycle":      (3, 6),
        "late_cycle":     (6, 10),
        "pre_recession":  (10, 14),
    },
}


# ═════════════════════════════════════════════════════════════════════
# CLAIM EXTRACTION (rule-based — no LLM needed for structured data)
# ═════════════════════════════════════════════════════════════════════

class GroundingClaim:
    """A single claim extracted from a narrative, with verification result."""
    def __init__(self, source_tool: str, source_field: str, claim_text: str,
                 metric_name: str, asserted_label: str,
                 actual_value=None, actual_label: str = "",
                 grounded: bool = True, explanation: str = ""):
        self.source_tool = source_tool
        self.source_field = source_field
        self.claim_text = claim_text
        self.metric_name = metric_name
        self.asserted_label = asserted_label
        self.actual_value = actual_value
        self.actual_label = actual_label
        self.grounded = grounded
        self.explanation = explanation
        self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        return {
            "source_tool": self.source_tool,
            "source_field": self.source_field,
            "claim_text": self.claim_text,
            "metric_name": self.metric_name,
            "asserted_label": self.asserted_label,
            "actual_value": self.actual_value,
            "actual_label": self.actual_label,
            "grounded": self.grounded,
            "explanation": self.explanation,
        }


def classify_value(metric_name: str, value) -> str:
    """Classify a numeric value into its threshold label."""
    if metric_name not in THRESHOLDS or value is None:
        return "unknown"
    for label, (lo, hi) in THRESHOLDS[metric_name].items():
        if lo <= value < hi:
            return label
    return "out_of_range"


def extract_and_verify_claims(report_data: dict) -> list[GroundingClaim]:
    """Extract factual claims from narratives and verify against data."""
    claims = []

    # ── Helper: scan a text for threshold-label words ──
    label_words = {
        "tight": ["tight", "compressed", "narrow"],
        "wide": ["wide", "widening", "elevated spread"],
        "stressed": ["stressed", "strained", "distressed"],
        "supportive": ["supportive", "benign"],
        "complacent": ["complacent"],
        "calm": ["calm", "subdued"],
        "fearful": ["fear", "fearful", "anxious"],
        "panic": ["panic", "extreme fear", "capitulation"],
        "low": ["low"],
        "moderate": ["moderate", "modest"],
        "elevated": ["elevated", "rising concern"],
        "high": ["high", "significant"],
        "extreme": ["extreme", "crisis"],
        "hot": ["hot", "overheating", "surging"],
        "cooling": ["cooling", "easing", "declining", "falling"],
        "stable": ["stable", "anchored"],
        "oversold": ["oversold"],
        "overbought": ["overbought"],
    }

    # Words that describe Fed policy, NOT credit conditions.
    # "accommodative" describes monetary policy stance; it must not
    # be mapped to credit-spread labels like "supportive/tight".
    fed_policy_words = {"accommodative", "restrictive", "hawkish", "dovish"}

    def find_labels_in_text(text: str, context: str = "") -> list[str]:
        """Find all threshold-label words present in text.

        Args:
            text: narrative text to scan.
            context: optional hint (e.g. "credit") to filter out
                     Fed-policy words that don't apply to credit spreads.
        """
        text_lower = text.lower()
        found = []
        for label, words in label_words.items():
            for w in words:
                if w in text_lower:
                    found.append(label)
                    break
        # When scanning for credit-spread labels, strip any hit that was
        # actually a Fed-policy word (e.g. "accommodative" ≠ "supportive").
        if context == "credit":
            cleaned = []
            for lbl in found:
                trigger_words = label_words.get(lbl, [])
                # Keep the label only if at least one non-Fed-policy word matched
                has_non_fed = any(
                    w in text_lower and w not in fed_policy_words
                    for w in trigger_words
                )
                if has_non_fed:
                    cleaned.append(lbl)
            found = cleaned
        return found

    # ── 1. Credit spread interpretation ──
    bond = report_data.get("analyze_bond_market", {})
    equity = report_data.get("analyze_equity_drivers", {})

    # Find HY OAS value
    hy_oas = None
    cs = bond.get("credit_spreads", {})
    if isinstance(cs, dict):
        for k, v in cs.items():
            if isinstance(v, dict) and ("hy" in k.lower() or "high_yield" in k.lower()):
                hy_oas = v.get("latest", v.get("value", v.get("spread_bps")))
    if hy_oas is None:
        cel = equity.get("credit_equity_link", {})
        if isinstance(cel, dict):
            hy_oas = cel.get("hy_oas_bps")

    # Check credit interpretation texts
    for tool_name, data in [("analyze_bond_market", bond), ("analyze_equity_drivers", equity)]:
        for field_name in ["summary", "interpretation"]:
            text = ""
            if isinstance(data, dict):
                text = str(data.get(field_name, ""))
                # Also check nested dicts
                for k, v in data.items():
                    if isinstance(v, dict):
                        text += " " + str(v.get("interpretation", ""))

            if hy_oas is not None and text:
                actual_label = classify_value("hy_oas_bps", hy_oas)
                text_labels = find_labels_in_text(text, context="credit")
                for asserted in text_labels:
                    if asserted in ("tight", "supportive") and actual_label in ("wide", "stressed", "distressed"):
                        claims.append(GroundingClaim(
                            tool_name, field_name,
                            f"Narrative says credit is '{asserted}' but HY OAS = {hy_oas}bps",
                            "hy_oas_bps", asserted, hy_oas, actual_label,
                            grounded=False,
                            explanation=f"At {hy_oas}bps, HY OAS is '{actual_label}', not '{asserted}'. "
                            f"Threshold: tight=<150bps, normal=150-300, wide=300-500.",
                        ))
                    elif asserted in ("wide", "stressed") and actual_label in ("tight", "normal"):
                        claims.append(GroundingClaim(
                            tool_name, field_name,
                            f"Narrative says credit is '{asserted}' but HY OAS = {hy_oas}bps",
                            "hy_oas_bps", asserted, hy_oas, actual_label,
                            grounded=False,
                            explanation=f"At {hy_oas}bps, HY OAS is '{actual_label}', not '{asserted}'.",
                        ))
                    elif asserted in ("tight", "supportive", "wide", "stressed"):
                        claims.append(GroundingClaim(
                            tool_name, field_name,
                            f"Credit described as '{asserted}', HY OAS = {hy_oas}bps",
                            "hy_oas_bps", asserted, hy_oas, actual_label,
                            grounded=True,
                            explanation=f"HY OAS at {hy_oas}bps is classified as '{actual_label}', "
                            f"consistent with '{asserted}'.",
                        ))

    # ── 2. Stress level vs. composite score ──
    stress = report_data.get("analyze_financial_stress", {})
    stress_score = stress.get("composite_score")
    stress_level = stress.get("stress_level", "")
    stress_summary = str(stress.get("summary", ""))

    if stress_score is not None and stress_level:
        actual_label = classify_value("stress_score", stress_score)
        if actual_label != stress_level.lower() and actual_label != "unknown":
            claims.append(GroundingClaim(
                "analyze_financial_stress", "stress_level",
                f"Stress labeled '{stress_level}' but score = {stress_score:.1f}",
                "stress_score", stress_level.lower(), stress_score, actual_label,
                grounded=False,
                explanation=f"Score {stress_score:.1f} maps to '{actual_label}' in our thresholds, "
                f"but the tool says '{stress_level}'.",
            ))
        else:
            claims.append(GroundingClaim(
                "analyze_financial_stress", "stress_level",
                f"Stress labeled '{stress_level}', score = {stress_score:.1f}",
                "stress_score", stress_level.lower(), stress_score, actual_label,
                grounded=True,
                explanation=f"Stress level '{stress_level}' is consistent with score {stress_score:.1f}.",
            ))

    # ── 3. VIX value vs. narrative characterization ──
    vix_comp = stress.get("components", {}).get("vix", {})
    vix_value = vix_comp.get("value") if isinstance(vix_comp, dict) else None

    if vix_value is not None:
        actual_label = classify_value("vix", vix_value)
        # Check all narratives for VIX characterizations
        for tool_name, data in report_data.items():
            if not isinstance(data, dict):
                continue
            for field_name in ["summary", "interpretation", "assessment", "composite_outlook"]:
                text = str(data.get(field_name, ""))
                if "vix" in text.lower():
                    text_labels = find_labels_in_text(text)
                    for asserted in text_labels:
                        if asserted in THRESHOLDS.get("vix", {}):
                            asserted_range = THRESHOLDS["vix"][asserted]
                            if not (asserted_range[0] <= vix_value < asserted_range[1]):
                                claims.append(GroundingClaim(
                                    tool_name, field_name,
                                    f"VIX described as '{asserted}' but VIX = {vix_value}",
                                    "vix", asserted, vix_value, actual_label,
                                    grounded=False,
                                    explanation=f"VIX at {vix_value} is '{actual_label}', "
                                    f"not '{asserted}' ({asserted_range[0]}-{asserted_range[1]}).",
                                ))

    # ── 4. Inflation characterization vs. CPI data ──
    regime = report_data.get("analyze_macro_regime", {})
    inf_detail = regime.get("inflation_detail", {})
    cpi_data = inf_detail.get("cpi", {}) if isinstance(inf_detail, dict) else {}
    cpi_value = cpi_data.get("latest_value") if isinstance(cpi_data, dict) else None

    if cpi_value is not None:
        actual_label = classify_value("cpi_yoy_pct", cpi_value)
        regimes = regime.get("regimes", {})
        inf_regime = regimes.get("inflation", "")
        if isinstance(inf_regime, dict):
            inf_regime = inf_regime.get("classification", str(inf_regime))

        if isinstance(inf_regime, str) and inf_regime:
            # Map regime labels to threshold labels
            regime_to_threshold = {
                "hot": ["hot", "very_hot"],
                "cooling": ["above_target", "target", "low"],
                "stable": ["target", "low"],
            }
            expected = regime_to_threshold.get(inf_regime.lower(), [])
            is_grounded = actual_label in expected or not expected
            claims.append(GroundingClaim(
                "analyze_macro_regime", "regimes.inflation",
                f"Inflation regime: '{inf_regime}', CPI = {cpi_value:.2f}%",
                "cpi_yoy_pct", inf_regime.lower(), cpi_value, actual_label,
                grounded=is_grounded,
                explanation=f"CPI at {cpi_value:.2f}% is classified as '{actual_label}'. "
                f"Regime '{inf_regime}' {'matches' if is_grounded else 'may not match'} this level.",
            ))

    # ── 5. Late-cycle characterization vs. count ──
    late = report_data.get("detect_late_cycle_signals", {})
    lc_count = late.get("count")
    lc_confidence = late.get("confidence_level", "")

    if lc_count is not None and isinstance(lc_confidence, str):
        actual_label = classify_value("late_cycle_count", lc_count)
        # Check if confidence label matches count
        confidence_to_count = {
            "early/mid cycle": ["early_cycle", "mid_cycle"],
            "early_mid": ["early_cycle", "mid_cycle"],
            "early or mid-cycle": ["early_cycle", "mid_cycle"],
            "transitioning": ["mid_cycle", "late_cycle"],
            "late": ["late_cycle"],
            "late_cycle": ["late_cycle"],
            "pre_recessionary": ["pre_recession"],
            "pre-recessionary": ["pre_recession"],
        }
        expected = confidence_to_count.get(lc_confidence.lower(), [])
        is_grounded = actual_label in expected or not expected
        claims.append(GroundingClaim(
            "detect_late_cycle_signals", "confidence_level",
            f"Confidence: '{lc_confidence}', count = {lc_count}/13",
            "late_cycle_count", lc_confidence.lower(), lc_count, actual_label,
            grounded=is_grounded,
            explanation=f"With {lc_count} signals firing, the cycle stage is '{actual_label}'. "
            f"Confidence '{lc_confidence}' {'matches' if is_grounded else 'may not match'}.",
        ))

    # ── 6. Real yield characterization ──
    ryi = equity.get("real_yield_impact", {})
    if isinstance(ryi, dict):
        ry_value = ryi.get("real_yield_10y")
        ry_interp = ryi.get("interpretation", "")

        if ry_value is not None and isinstance(ry_interp, str):
            actual_label = classify_value("real_yield_10y_pct", ry_value)
            text_labels = find_labels_in_text(ry_interp)

            for asserted in text_labels:
                if asserted in THRESHOLDS.get("real_yield_10y_pct", {}):
                    asserted_range = THRESHOLDS["real_yield_10y_pct"][asserted]
                    grounded = asserted_range[0] <= ry_value < asserted_range[1]
                    claims.append(GroundingClaim(
                        "analyze_equity_drivers", "real_yield_impact.interpretation",
                        f"Real yield described as '{asserted}', actual = {ry_value}%",
                        "real_yield_10y_pct", asserted, ry_value, actual_label,
                        grounded=grounded,
                        explanation=f"Real yield at {ry_value}% is '{actual_label}'. "
                        f"'{asserted}' range is {asserted_range[0]}-{asserted_range[1]}%.",
                    ))

    # ── 7. Consumer health level vs. score ──
    consumer = report_data.get("analyze_consumer_health", {})
    ch_score = consumer.get("composite_score")
    ch_level = consumer.get("consumer_health_level", "")

    if ch_score is not None and isinstance(ch_level, str):
        # Consumer health: 0-3 = critical, 3-5 = stressed, 5-7 = stable, 7-10 = healthy
        ch_thresholds = {"critical": (0,3), "stressed": (3,5), "cautious": (4,6),
                         "stable": (5,7), "healthy": (7,10)}
        actual_label = "unknown"
        for label, (lo, hi) in ch_thresholds.items():
            if lo <= ch_score < hi:
                actual_label = label
                break

        grounded = actual_label == ch_level.lower() or actual_label == "unknown"
        claims.append(GroundingClaim(
            "analyze_consumer_health", "consumer_health_level",
            f"Consumer health: '{ch_level}', score = {ch_score:.1f}",
            "consumer_health_score", ch_level.lower(), ch_score, actual_label,
            grounded=grounded,
            explanation=f"Score {ch_score:.1f} maps to '{actual_label}'. "
            f"Label '{ch_level}' {'matches' if grounded else 'may not match'}.",
        ))

    return claims


# ═════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═════════════════════════════════════════════════════════════════════

def collect_full_report() -> dict:
    """Execute all 8 /full_report tools."""
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
    return report


# ═════════════════════════════════════════════════════════════════════
# REPORT GENERATION & RECORDS
# ═════════════════════════════════════════════════════════════════════

def save_record(claims: list[GroundingClaim], report_data: dict):
    """Save grounding results to records directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    grounded = sum(1 for c in claims if c.grounded)
    ungrounded = sum(1 for c in claims if not c.grounded)

    record = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_claims": len(claims),
            "grounded": grounded,
            "ungrounded": ungrounded,
            "grounding_rate": f"{grounded/len(claims)*100:.1f}%" if claims else "N/A",
        },
        "ungrounded_claims": [c.to_dict() for c in claims if not c.grounded],
        "all_claims": [c.to_dict() for c in claims],
    }

    path = _RECORDS_DIR / f"grounding_{ts}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    print(f"\n  Record saved: {path}")

    # Also save markdown
    md_lines = [
        f"# Narrative Grounding Report",
        f"",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Claims checked**: {len(claims)}",
        f"**Grounded**: {grounded} | **Ungrounded**: {ungrounded}",
        f"",
    ]
    if ungrounded > 0:
        md_lines.append("## Grounding Failures\n")
        for c in claims:
            if not c.grounded:
                md_lines.append(f"### {c.source_tool} / {c.source_field}\n")
                md_lines.append(f"- **Claim**: {c.claim_text}")
                md_lines.append(f"- **Metric**: `{c.metric_name}` = {c.actual_value}")
                md_lines.append(f"- **Asserted**: \"{c.asserted_label}\" | **Actual**: \"{c.actual_label}\"")
                md_lines.append(f"- **Explanation**: {c.explanation}")
                md_lines.append("")

    md_lines.append("## All Claims\n")
    md_lines.append("| Tool | Metric | Asserted | Actual Value | Actual Label | Grounded |")
    md_lines.append("|------|--------|----------|-------------|--------------|----------|")
    for c in claims:
        icon = "\u2705" if c.grounded else "\u274c"
        md_lines.append(f"| {c.source_tool} | {c.metric_name} | {c.asserted_label} | {c.actual_value} | {c.actual_label} | {icon} |")

    md_path = _RECORDS_DIR / f"grounding_{ts}.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"  Markdown: {md_path}")

    return path


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Approach 3: Narrative-vs-Data Grounding")
    parser.add_argument("--input", type=str, help="Path to saved full_report JSON")
    args = parser.parse_args()

    print("=" * 70)
    print("  APPROACH 3: NARRATIVE-VS-DATA GROUNDING")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if args.input:
        with open(args.input) as f:
            report_data = json.load(f)
        print(f"\n  Loaded from: {args.input}")
    else:
        report_data = collect_full_report()

    print(f"\n{'─' * 70}")
    print("  Extracting and verifying claims...")
    print(f"{'─' * 70}\n")

    claims = extract_and_verify_claims(report_data)

    grounded = sum(1 for c in claims if c.grounded)
    ungrounded = sum(1 for c in claims if not c.grounded)

    for c in claims:
        icon = "\u2705" if c.grounded else "\u274c"
        print(f"  {icon} [{c.source_tool}] {c.claim_text}")
        if not c.grounded:
            print(f"      \u2192 {c.explanation}")

    print(f"\n{'=' * 70}")
    print(f"  GROUNDING RESULTS")
    print(f"  Claims: {len(claims)} | Grounded: {grounded} | Ungrounded: {ungrounded}")
    print(f"  Grounding Rate: {grounded/len(claims)*100:.1f}%" if claims else "  No claims found")
    print(f"{'=' * 70}")

    save_record(claims, report_data)
